"""Process a batch and store the run (G1); read runs back and regenerate their export (G2).

process_batch: store the uploaded file and its lines, load the engine's inputs from the database, call the
engine, then store the run: its inputs snapshot (lines, master data, contract baseline, policy versions),
every requirement, decision row, PO with its lines, sourcing request, and the export's hash. The engine's
inputs are never changed, so processing the same file again gives a new run with identical decisions.
"""
import csv
import io
import os
import subprocess
import time
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from db.ingest import ingest_batch
from db.models import (EXPORT_COLUMNS, AuditLog, BuyerAction, Decision, PoLine, PolicyVersion, PrBatch, PrLine, PurchaseOrder,
                       Requirement, Run, SourcingRequest)
from engine.contracts import money
from engine.export import to_csv
from engine.pipeline import decide
from kitdata import NO_KIT_NOTICE
from loaders import database
from services.snapshot import plain, run_inputs, sha256_json, sha256_text


def engine_version():
    for name in ("ENGINE_VERSION", "RENDER_GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA"):
        if os.getenv(name):
            return os.environ[name]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _store_outputs(session, run, result, line_ids):
    version_ids = {v.version: v.id for v in session.scalars(select(PolicyVersion).where(PolicyVersion.status == "approved"))}
    req_ids, used_versions = {}, set()
    for d in result.requirements:
        r, o, v = d.requirement, d.outcome, d.valuation
        used_versions.add(version_ids[r.version.version])
        contract = o.uses_contract.contract.contract_id if o.uses_contract else (
            v.reference if v.source in ("contract_to_be_used", "lowest_applicable_contract_rate") else None)
        row = Requirement(
            run_id=run.id, group_id=r.group_id, item_code=r.item_code or "NEW", plant=r.plant,
            requirement_date=r.requirement_date, first_created_at=r.created_at, total_quantity=r.total_quantity,
            value_inr=v.value, valuation_source=v.source, policy_version_id=version_ids[r.version.version],
            rule_id=o.rule["id"], decision=o.decision, route=o.route, supplier_id=o.supplier_id, unit_price=o.unit_price,
            suggested_supplier_ids=list(o.suggestions), contract_id=contract,
            relied_on=plain({"valuation": {"source": v.source, "reference": v.reference, "note": v.note},
                             "preferred": [{"supplier_id": p.supplier_id, "rank": p.rank, "score": p.score,
                                            "parts": dict(p.parts), "reference_price": p.reference_price,
                                            "reference": p.reference} for p in d.preferred],
                             "missing": d.missing, "notes": d.notes, "lines": [c.index for c in r.lines]}),
            reason=next(row["reason"] for row in result.rows if row.index == r.first.index))
        session.add(row)
        session.flush()
        req_ids[r.group_id] = row.id
        if o.decision == "SOURCING_REQUEST":
            session.add(SourcingRequest(run_id=run.id, requirement_id=row.id, route=o.route,
                                        suggested_supplier_ids=list(o.suggestions),
                                        suggest_count_requested=o.suggest_requested, status="proposed"))
    for row in result.rows:
        if row["policy_version"] in version_ids:
            used_versions.add(version_ids[row["policy_version"]])
        session.add(Decision(run_id=run.id, pr_line_id=line_ids[row.index], requirement_id=req_ids.get(row["group_id"]),
                             row_order=row.index, **{c: row[c] for c in EXPORT_COLUMNS}))
    by_group = {d.requirement.group_id: d for d in result.requirements}
    for po in result.purchase_orders:
        ds = [by_group[g] for g in po.group_ids]
        values = [money(d.requirement.total_quantity * d.outcome.unit_price) for d in ds]
        row = PurchaseOrder(run_id=run.id, po_number=po.po_id, supplier_id=ds[0].outcome.supplier_id,
                            plant=ds[0].requirement.plant, route=ds[0].outcome.route,
                            first_requirement_at=po.first.created_at, total_value=sum(values), status="proposed")
        session.add(row)
        session.flush()
        for n, (d, value) in enumerate(zip(ds, values), start=1):
            session.add(PoLine(po_id=row.id, line_no=n, requirement_id=req_ids[d.requirement.group_id],
                               item_code=d.requirement.item_code, quantity=d.requirement.total_quantity,
                               unit_price=d.outcome.unit_price, value=value))
    return sorted(used_versions)


class UnknownVersion(ValueError):
    pass


class NoKitData(ValueError):
    """No master data yet: a batch would be decided against no items, suppliers or contracts."""


BY_DATE = {"mode": "by_requirement_date",
           "note": "each requirement uses the approved version in force on its requirement date"}


def pin_version(master, version):
    """H7: (master, policy_mode). With a version label, that one approved version decides every requirement
    whatever its date (its effective date is set to the earliest possible date for this run only); without
    one, versions are chosen by requirement date as usual."""
    if not version:
        return master, BY_DATE
    match = [p for p in master.policies if p.version == version]
    if not match:
        known = ", ".join(p.version for p in master.policies) or "none"
        raise UnknownVersion(f"There is no approved policy version {version!r} (approved: {known}).")
    mode = {"mode": "named_version", "version": version, "effective_from": str(match[0].effective_from),
            "note": f"every requirement decided under version {version}, whatever its date"}
    return replace(master, policies=(replace(match[-1], effective_from=date.min),)), mode


def process_batch(session, filename, csv_text, user, version=None):
    """Returns (run, result, export_text, seconds). Raises loaders.pr_csv.BatchFormatError on a bad file,
    UnknownVersion if `version` names no approved version, and NoKitData before the kit is loaded."""
    started = time.perf_counter()
    master = database.load_master(session)
    if not master.items or not master.suppliers:
        raise NoKitData(NO_KIT_NOTICE)
    master, mode = pin_version(master, version)  # before storing anything
    batch = ingest_batch(session, filename, csv_text, user)
    line_ids = [r.id for r in session.scalars(select(PrLine).where(PrLine.batch_id == batch.id).order_by(PrLine.id))]
    lines = database.load_pr_lines(session, batch.id)
    run, result, export = _record_run(session, "batch", batch.id, lines, line_ids, master, mode, user,
                                      {"batch_id": batch.id, "filename": filename, "version": version})
    return run, result, export, time.perf_counter() - started


def _record_run(session, kind, batch_id, lines, line_ids, master, mode, user, details):
    """Decide the lines, store the run with all its outputs, audit it, commit. Returns (run, result, export)."""
    result = decide(lines, master)
    export = to_csv(result)
    inputs = {**run_inputs(lines, master, result), "policy_mode": mode}
    run = Run(kind=kind, batch_id=batch_id, policy_version_ids=[], inputs=inputs, inputs_sha256=sha256_json(inputs),
              export_sha256=sha256_text(export), engine_version=engine_version(), status="running", started_by=user)
    session.add(run)
    session.flush()
    run.policy_version_ids = _store_outputs(session, run, result, line_ids)
    run.status, run.finished_at = "done", datetime.now(timezone.utc)
    session.add(AuditLog(actor=user, actor_role="api", action=f"{kind}.process", entity_type="run", entity_id=str(run.id),
                         details={**details, "lines": len(result.rows), "policy_mode": mode["mode"]}))
    session.commit()
    return run, result, export


def open_chat_line_ids(session):
    """Chat lines no buyer has acted on (D15): an approved or overridden requirement is closed, so a new chat
    line can never join it; it starts a requirement of its own."""
    actioned = select(BuyerAction.requirement_id)
    closed = select(Decision.pr_line_id).where(Decision.requirement_id.in_(actioned))
    return list(session.scalars(select(PrLine.id).where(PrLine.source == "chat", PrLine.id.not_in(closed))
                                .order_by(PrLine.id)))


def process_chat(session, user):
    """A chat run over every open chat line (D15). Returns (run, result), or (None, None) if there are none."""
    ids = open_chat_line_ids(session)
    if not ids:
        return None, None
    master = database.load_master(session)
    lines = database.load_lines(session, ids)
    run, result, _ = _record_run(session, "chat", None, lines, ids, master, BY_DATE, user, {"chat_lines": len(ids)})
    return run, result


def export_csv(session, run_id):
    """The stored run's decisions in the brief's format, regenerated from the decisions table."""
    rows = session.scalars(select(Decision).where(Decision.run_id == run_id).order_by(Decision.row_order))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for d in rows:
        writer.writerow([getattr(d, c) for c in EXPORT_COLUMNS])
    return buffer.getvalue()


def summary(session, run_id):
    counts = session.execute(select(Decision.route, func.count()).where(Decision.run_id == run_id).group_by(Decision.route))
    return dict(sorted(counts.all()))


def describe(session, run):
    batch = session.get(PrBatch, run.batch_id) if run.batch_id else None
    return {"run_id": run.id, "kind": run.kind, "status": run.status, "batch_id": run.batch_id,
            "filename": batch.filename if batch else None, "lines": batch.line_count if batch else None,
            "started_by": run.started_by, "started_at": plain(run.started_at), "finished_at": plain(run.finished_at),
            "policy_version_ids": run.policy_version_ids,
            "policy_mode": (run.inputs or {}).get("policy_mode", BY_DATE), "engine_version": run.engine_version,
            "inputs_sha256": run.inputs_sha256, "export_sha256": run.export_sha256,
            "summary_by_route": summary(session, run.id)}


def route_counts(result):
    return dict(sorted(Counter(r["route"] for r in result.rows).items()))
