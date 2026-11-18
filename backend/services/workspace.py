"""B4: the buyer workspace. Reads a stored run's requirements with everything a buyer needs to act on each one,
and records Approve and Override. The engine's decision is never changed: an action is a BuyerAction beside it
(append-only), and approving marks the run's proposed PO approved or its sourcing request issued.

Concurrency: each requirement has a row_version. Approve and Override are conditional updates
("... WHERE id = ? AND row_version = ? AND status = 'open'"); if another buyer acted first, nothing is written
and the caller gets a 409. Approving a PO approves every open requirement on it in one transaction.
D14: no action changes contract ceilings or PO history.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update

from db.models import (AuditLog, BuyerAction, Decision, Item, PoLine, PolicyVersion, PrBatch, PrLine, PurchaseOrder,
                       Requirement, Run, SourcingRequest, Supplier)
from services.snapshot import plain

ROUTE_WORDS = {
    "CONTRACT_PO": "Contract PO", "EMERGENCY_PO": "Emergency PO", "SPOT_PO": "Spot PO", "RFQ": "Request for quotation",
    "RFP": "Request for proposal", "CAPEX_SOURCING": "Capex sourcing", "NEW_ITEM_SOURCING": "New item sourcing",
}
PO_ROUTES = {"CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO"}
SOURCING_ROUTES = {"RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING"}
PRICE_SOURCE_WORDS = {
    "contract_to_be_used": "the rate of the contract that will be used (3.1a)",
    "lowest_applicable_contract_rate": "the lowest applicable contract rate (3.1a)",
    "latest_po_in_window": "the latest PO price in the last 365 days, any supplier (3.1b)",
    "standard_price": "the item master standard price (3.1c)",
    "requester_estimate": "the requester's estimate (1.2)",
}
FLAG = re.compile(r"note (F\d+): ([^;]+)")


class WorkspaceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- reading
def _summary(session, run_id, kind, started_at, started_by, batch_id):
    statuses = session.scalars(select(Requirement.status).where(Requirement.run_id == run_id)).all()
    filename = session.scalar(select(PrBatch.filename).where(PrBatch.id == batch_id)) if batch_id else None
    label = f"Batch run {run_id} ({filename})" if kind == "batch" else f"Chat requests (run {run_id})"
    return {"id": run_id, "kind": kind, "started_at": plain(started_at), "started_by": started_by, "batch_id": batch_id,
            "requirements": len(statuses), "open": sum(x == "open" for x in statuses), "label": label}


def runs(session):
    """Runs a buyer can open, newest first, with how many requirements still need action (columns only: a run's
    inputs snapshot is large and not needed here)."""
    rows = session.execute(select(Run.id, Run.kind, Run.started_at, Run.started_by, Run.batch_id)
                           .where(Run.status == "done").order_by(Run.id.desc())).all()
    return [_summary(session, *row) for row in rows]


def default_run_id(session, kind="batch"):
    return session.scalar(select(Run.id).where(Run.kind == kind, Run.status == "done").order_by(Run.id.desc()).limit(1))


def _suppliers(session):
    return {s.supplier_id: s for s in session.scalars(select(Supplier))}


def _history(session, req_ids):
    out = {}
    for a in session.scalars(select(BuyerAction).where(BuyerAction.requirement_id.in_(req_ids)).order_by(BuyerAction.id)):
        out.setdefault(a.requirement_id, []).append(
            {"action": a.action, "by": a.actor, "role": a.actor_role, "at": plain(a.at), "comment": a.comment,
             "new_route": a.new_route, "new_supplier_id": a.new_supplier_id, "new_unit_price": plain(a.new_unit_price),
             "new_suggested_supplier_ids": a.new_suggested_supplier_ids})
    return out


def workspace(session, run_id):
    row = session.execute(select(Run.id, Run.kind, Run.started_at, Run.started_by, Run.batch_id)
                          .where(Run.id == run_id)).first()
    if row is None:
        raise WorkspaceError(f"There is no run {run_id}.", 404)
    reqs = session.scalars(select(Requirement).where(Requirement.run_id == run_id).order_by(Requirement.requirement_date,
                                                                                         Requirement.id)).all()
    ids = [r.id for r in reqs]
    suppliers = _suppliers(session)
    items = {i.item_code: i for i in session.scalars(select(Item))}
    versions = {p.id: p.version for p in session.scalars(select(PolicyVersion))}
    decisions = session.scalars(select(Decision).where(Decision.run_id == run_id).order_by(Decision.row_order)).all()
    lines = {ln.id: ln for ln in session.scalars(select(PrLine).where(PrLine.id.in_([d.pr_line_id for d in decisions])))}
    by_req = {}
    for d in decisions:
        if d.requirement_id:
            by_req.setdefault(d.requirement_id, []).append((d, lines[d.pr_line_id]))
    po_of = {pl.requirement_id: pl.po_id for pl in session.scalars(select(PoLine).where(PoLine.requirement_id.in_(ids)))}
    pos = {p.id: p for p in session.scalars(select(PurchaseOrder).where(PurchaseOrder.run_id == run_id))}
    po_members = {}
    for req_id, po_id in po_of.items():
        po_members.setdefault(po_id, []).append(req_id)
    group_of = {r.id: r.group_id for r in reqs}
    sourcing = {s.requirement_id: s for s in session.scalars(select(SourcingRequest).where(SourcingRequest.run_id == run_id))}
    history = _history(session, ids)

    def supplier(sid):
        s = suppliers.get(sid)
        return {"supplier_id": sid, "name": s.name if s else sid, "status": s.status if s else "unknown",
                "on_time_pct": plain(s.on_time_pct) if s else None, "quality": plain(s.quality_rating) if s else None}

    out = []
    for r in reqs:
        members = by_req.get(r.id, [])
        flags = sorted({(code, text.strip()) for d, _ in members for code, text in FLAG.findall(d.reason)})
        preferred = r.relied_on.get("preferred", [])
        listed = {p["supplier_id"] for p in preferred}
        po = None
        if r.id in po_of:
            p = pos[po_of[r.id]]
            po = {"po_number": p.po_number, "status": p.status, "total_value": plain(p.total_value),
                  "supplier": supplier(p.supplier_id),
                  "requirements": [{"id": m, "group_id": group_of[m]} for m in sorted(po_members[p.id])]}
        item = items.get(r.item_code)
        valuation = r.relied_on.get("valuation", {})
        out.append({
            "id": r.id, "group_id": r.group_id, "version": r.row_version, "status": r.status,
            "item_code": r.item_code, "item_description": item.description if item else members[0][1].description,
            "category": item.category if item else None, "unit": item.uom if item else members[0][1].uom,
            "plant": r.plant, "requirement_date": plain(r.requirement_date), "total_quantity": plain(r.total_quantity),
            "value_inr": plain(r.value_inr), "decision": r.decision, "route": r.route, "route_words": ROUTE_WORDS.get(r.route, r.route),
            "rule_id": r.rule_id, "policy_version": versions.get(r.policy_version_id),
            "supplier": supplier(r.supplier_id) if r.supplier_id else None, "unit_price": plain(r.unit_price),
            "po": po, "contract_id": r.contract_id,
            "suggestions": [{**supplier(s), "rank": i + 1, "source": "preferred list" if s in listed else "category top-up (6.4)"}
                            for i, s in enumerate(r.suggested_supplier_ids)],
            "sourcing_request": {"status": sourcing[r.id].status} if r.id in sourcing else None,
            "why": {"reason": r.reason, "clause": r.rule_id, "price_source": valuation.get("source"),
                    "price_source_words": PRICE_SOURCE_WORDS.get(valuation.get("source"), valuation.get("source")),
                    "price_reference": valuation.get("reference"), "valuation_note": valuation.get("note"),
                    "notes": r.relied_on.get("notes", []), "missing": r.relied_on.get("missing", {})},
            "flags": [{"code": c, "text": t} for c, t in flags],
            "preferred": [{**supplier(p["supplier_id"]), "rank": p["rank"], "score": p["score"], "parts": p["parts"],
                           "reference_price": p["reference_price"], "reference": p["reference"]} for p in preferred],
            "lines": [{"pr_no": ln.pr_no, "pr_line": ln.pr_line, "description": ln.description,
                       "quantity": plain(ln.quantity), "uom": ln.uom, "need_by": plain(ln.need_by_date),
                       "urgency": ln.urgency, "requester": ln.requester, "department": ln.department,
                       "created_at": plain(ln.created_at), "source": ln.source} for _, ln in members],
            "history": history.get(r.id, []),
        })
    not_processed = [{"pr_no": d.pr_no, "pr_line": d.pr_line, "description": lines[d.pr_line_id].description,
                      "plant": lines[d.pr_line_id].plant, "quantity": plain(lines[d.pr_line_id].quantity),
                      "reason": d.reason} for d in decisions if d.route == "NOT_PROCESSED"]
    return {"run": _summary(session, *row), "requirements": out,
            "not_processed": not_processed, "plants": sorted({r.plant for r in reqs}),
            "routes": sorted({r.route for r in reqs})}


def requirement(session, req_id):
    r = session.get(Requirement, req_id)
    if r is None:
        raise WorkspaceError(f"There is no requirement {req_id}.", 404)
    return next(x for x in workspace(session, r.run_id)["requirements"] if x["id"] == req_id)


# ---------------------------------------------------------------- acting
def _now():
    return datetime.now(timezone.utc)


def _claim(session, req_id, version, status):
    """Conditional update: True only if the requirement is still open at this version."""
    result = session.execute(update(Requirement).where(Requirement.id == req_id, Requirement.row_version == version,
                                                       Requirement.status == "open")
                             .values(status=status, row_version=Requirement.row_version + 1))
    return result.rowcount == 1


def _gone(session, req_id):
    session.rollback()
    r = session.get(Requirement, req_id)
    who = session.scalars(select(BuyerAction).where(BuyerAction.requirement_id == req_id)
                          .order_by(BuyerAction.id.desc())).first()
    if who:
        done = {"approve": "approved", "override": "overridden"}[who.action]
        return WorkspaceError(f"{r.group_id} was already {done} by {who.actor}. The page has been refreshed.", 409)
    return WorkspaceError(f"{r.group_id} was changed by someone else. The page has been refreshed.", 409)


def approve(session, req_id, versions, user, role):
    """Approve a requirement; on a consolidated PO, every open requirement on it, together. `versions` maps each
    requirement id to the version the buyer saw. Returns the PO or sourcing record created."""
    r = session.get(Requirement, req_id)
    if r is None:
        raise WorkspaceError(f"There is no requirement {req_id}.", 404)
    try:
        versions = {int(k): int(v) for k, v in (versions or {}).items()}
    except (AttributeError, TypeError, ValueError):
        raise WorkspaceError("Send versions as {\"<requirement id>\": <version>, ...}.", 400) from None
    po_line = session.scalar(select(PoLine).where(PoLine.requirement_id == req_id))
    if po_line:
        po = session.get(PurchaseOrder, po_line.po_id)
        members = [pl.requirement_id for pl in session.scalars(select(PoLine).where(PoLine.po_id == po.id))]
        group = [m for m in members if session.get(Requirement, m).status == "open"]
    else:
        po, group = None, [req_id]
    if req_id not in group:
        raise _gone(session, req_id)
    missing = [m for m in group if m not in versions]
    if missing:
        raise WorkspaceError("Approving this PO approves all its requirements together; confirm them all: "
                             + ", ".join(session.get(Requirement, m).group_id for m in missing) + ".", 409)
    for m in group:
        if not _claim(session, m, versions[m], "approved"):
            raise _gone(session, m)
    for m in group:
        session.add(BuyerAction(requirement_id=m, action="approve", actor=user, actor_role=role))
    if po:
        po.status = "approved"
        record = {"kind": "po", "po_number": po.po_number, "supplier_id": po.supplier_id, "plant": po.plant,
                  "route": po.route, "status": po.status,
                  "lines": [{"group_id": session.get(Requirement, pl.requirement_id).group_id, "item_code": pl.item_code,
                             "quantity": plain(pl.quantity), "unit_price": plain(pl.unit_price), "value": plain(pl.value),
                             "approved": pl.requirement_id in group}
                            for pl in session.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no))]}
        record["total_value"] = plain(sum(Decimal(str(x["value"])) for x in record["lines"] if x["approved"]))
    else:
        sr = session.scalar(select(SourcingRequest).where(SourcingRequest.requirement_id == req_id))
        if sr:
            sr.status = "issued"
        record = {"kind": "sourcing", "route": r.route, "group_id": r.group_id, "status": "issued",
                  "suggested_supplier_ids": r.suggested_supplier_ids}
    session.add(AuditLog(actor=user, actor_role=role, action="requirement.approve", entity_type="requirement",
                         entity_id=str(req_id), details=plain({"approved": group, "record": record})))
    session.commit()
    return record


def _allowed(session, r, use):
    doc = session.get(PolicyVersion, r.policy_version_id).document
    return set(doc["parameters"]["suppliers"]["allowed_statuses"][use])


def override(session, req_id, version, user, role, route, comment, supplier_id=None, unit_price=None,
             suggested_supplier_ids=None):
    """Record a different route or supplier, with a comment. The original decision stays beside it."""
    r = session.get(Requirement, req_id)
    if r is None:
        raise WorkspaceError(f"There is no requirement {req_id}.", 404)
    if not (comment or "").strip():
        raise WorkspaceError("An override needs a comment saying why.", 422)
    if route not in PO_ROUTES | SOURCING_ROUTES:
        raise WorkspaceError(f"Choose a route: {', '.join(sorted(PO_ROUTES | SOURCING_ROUTES))}.", 422)
    suppliers = _suppliers(session)
    price = None
    if route in PO_ROUTES:
        s = suppliers.get(supplier_id or "")
        if s is None:
            raise WorkspaceError("A PO route needs a supplier.", 422)
        if s.status not in _allowed(session, r, "receive_po"):
            raise WorkspaceError(f"{s.supplier_id} {s.name} is {s.status} and cannot receive a PO.", 422)
        try:
            price = Decimal(str(unit_price))
        except (InvalidOperation, TypeError):
            raise WorkspaceError("A PO route needs a unit price.", 422) from None
        if price <= 0:
            raise WorkspaceError("The unit price must be more than zero.", 422)
        suggested = None
    else:
        suggested = [x for x in (suggested_supplier_ids or []) if x]
        allowed = _allowed(session, r, "be_suggested")
        bad = [x for x in suggested if x not in suppliers or suppliers[x].status not in allowed]
        if bad:
            raise WorkspaceError(f"These suppliers cannot be suggested (not Active): {', '.join(bad)}.", 422)
        supplier_id = None
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise WorkspaceError("Send the version of the requirement as a whole number.", 400) from None
    if not _claim(session, req_id, version, "overridden"):
        raise _gone(session, req_id)
    session.add(BuyerAction(requirement_id=req_id, action="override", new_route=route, new_supplier_id=supplier_id,
                            new_unit_price=price, new_suggested_supplier_ids=suggested, comment=comment.strip(),
                            actor=user, actor_role=role))
    session.add(AuditLog(actor=user, actor_role=role, action="requirement.override", entity_type="requirement",
                         entity_id=str(req_id), comment=comment.strip(),
                         details=plain({"from": {"route": r.route, "supplier_id": r.supplier_id},
                                        "to": {"route": route, "supplier_id": supplier_id, "unit_price": price,
                                               "suggested_supplier_ids": suggested}})))
    session.commit()
    return {"kind": "override", "route": route, "supplier_id": supplier_id, "unit_price": plain(price),
            "suggested_supplier_ids": suggested}


def suppliers_for(session, category=None):
    """Suppliers with their status, for choosing in an override (the screen disables those not allowed)."""
    out = []
    for s in session.scalars(select(Supplier).order_by(Supplier.supplier_id)):
        if category and category not in (s.categories or []):
            continue
        out.append({"supplier_id": s.supplier_id, "name": s.name, "status": s.status, "categories": s.categories,
                    "on_time_pct": plain(s.on_time_pct), "quality": plain(s.quality_rating)})
    return out
