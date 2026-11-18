"""H6: the amendment workflow. The LLM only drafts; code validates, explains and previews; a person with the
Procurement role approves. Approved versions are immutable (database trigger); every step is audited.

draft -> (edit, preview)* -> approve | discard;   approved -> withdrawn (with a comment)

An AI draft is made in the background: start_draft returns at once with drafting_status "drafting", and
run_draft (a background task) moves it to "ready" or to "failed" with a plain reason. A draft still drafting
after DRAFTING_TIMEOUT is marked failed when anyone next looks; drafts interrupted by a restart are marked failed
on startup. A late answer never overwrites a draft that was already failed or discarded (conditional update).
"""
import copy
import logging
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update

from amendments.drafting import DraftError, draft_from_current, draft_with_llm, next_version
from db.models import AuditLog, PolicyVersion, PrBatch
from engine.impact import impact
from engine.policy_check import validate
from engine.policy_explain import explain
from loaders import database
from llm.client import LLMError
from services.snapshot import plain

APPROVER_ROLE = "procurement"
DRAFTING_TIMEOUT = timedelta(minutes=5)
MANUAL_PATH = "Start from the current version and edit it by hand instead."
log = logging.getLogger("amendments")


class AmendmentError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _audit(session, user, role, action, row, comment=None, **details):
    session.add(AuditLog(actor=user or "anonymous", actor_role=role or "", action=action, entity_type="policy_version",
                         entity_id=str(row.id) if row is not None else "-", comment=comment, details=plain(details)))


def _get(session, version_id):
    row = session.get(PolicyVersion, version_id)
    if row is None:
        raise AmendmentError(f"There is no policy version {version_id}.", 404)
    return row


def _draft(session, version_id):
    row = _get(session, version_id)
    if row.status != "draft":
        raise AmendmentError(f"Version {row.version} is {row.status}; only a draft can be changed.", 409)
    return row


def base_version(session):
    """The latest approved version (by effective date, then approval time): what a new draft starts from."""
    rows = session.scalars(select(PolicyVersion).where(PolicyVersion.status == "approved")).all()
    if not rows:
        raise AmendmentError("There is no approved policy version to start from.", 409)
    return max(rows, key=lambda r: (r.effective_from, r.approved_at or datetime.min.replace(tzinfo=timezone.utc)))


def _labels(session):
    return set(session.scalars(select(PolicyVersion.version)))


def _sync(row, document):
    """Copy the document's metadata into the row's columns."""
    row.document = document
    row.version = str(document.get("version") or row.version)
    row.change_summary = str(document.get("change_summary") or "")
    try:
        row.effective_from = date.fromisoformat(str(document.get("effective_from"))) if document.get("effective_from") else None
    except ValueError:
        row.effective_from = None  # the validator reports the bad date


def _now():
    return datetime.now(timezone.utc)


def _aware(moment):
    return moment if moment is None or moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite drops tz


def _new_row(base, user, **fields):
    return PolicyVersion(policy_id=base.policy_id, status="draft", created_by=user, base_version_id=base.id, **fields)


def create_manual_draft(session, user):
    """A ready draft copied from the current version, for editing by hand (no AI)."""
    base = base_version(session)
    d = draft_from_current(base.document, user, _labels(session))
    row = _new_row(base, user, version=d.document["version"], document=d.document, drafted_by=d.drafted_by,
                   change_summary=d.document["change_summary"], drafting_status="ready",
                   draft_info={"not_expressed": [], "translation_notes": [], "llm_attempts": [], "mode": "manual"})
    _sync(row, d.document)
    session.add(row)
    session.flush()
    _audit(session, user, None, "policy.draft", row, drafted_by=d.drafted_by)
    session.commit()
    return row


def start_draft(session, user, client, text, source_name=None):
    """An AI draft row in drafting_status 'drafting', with the next free version label reserved. The caller
    then runs run_draft (in the background for the API)."""
    expire_stuck(session)
    if not (text or "").strip():
        raise AmendmentError("The amendment has no text to draft from.")
    if client is None:
        raise AmendmentError("No AI drafting service is configured. " + MANUAL_PATH, 503)
    base = base_version(session)
    row = _new_row(base, user, version=next_version(base.version, _labels(session)), document=None,
                   source_document_name=source_name, source_document_text=text, change_summary="",
                   drafted_by="llm (drafting)", drafting_status="drafting", drafting_started_at=_now())
    session.add(row)
    session.flush()
    _audit(session, user, None, "policy.draft_started", row, source=source_name)
    session.commit()
    return row


def _finish(session, row_id, **values):
    """Conditional update: only a draft still drafting can be finished. False if it was failed or discarded."""
    result = session.execute(update(PolicyVersion).where(
        PolicyVersion.id == row_id, PolicyVersion.drafting_status == "drafting", PolicyVersion.status == "draft")
        .values(drafting_finished_at=_now(), **values))
    return result.rowcount == 1


def run_draft(session_factory, row_id, client, clock=time.perf_counter):
    """The background part: ask the LLM, apply its draft, and mark the row ready or failed. Never raises."""
    started = clock()
    with session_factory() as session:
        row = session.get(PolicyVersion, row_id)
        if row is None or row.drafting_status != "drafting":
            return
        base = session.get(PolicyVersion, row.base_version_id)
        user, text = row.created_by, row.source_document_text
        try:
            d = draft_with_llm(text, base.document, client)
        except (LLMError, DraftError) as exc:  # visible and logged, never an empty draft (D32)
            attempts = [list(a) for a in getattr(exc, "attempts", [])]
            if _finish(session, row_id, drafting_status="failed", drafting_error=str(exc),
                       draft_info={"llm_attempts": attempts, "seconds": round(clock() - started, 1)}):
                _audit(session, user, None, "llm.failure", row, str(exc), attempts=attempts)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001 - a background task must leave the draft in a clear state
            log.exception("drafting %s failed", row_id)
            message = f"Drafting stopped because of an unexpected error ({type(exc).__name__}). {MANUAL_PATH}"
            if _finish(session, row_id, drafting_status="failed", drafting_error=message):
                _audit(session, user, None, "llm.failure", row, message)
            session.commit()
            return
        document = d.document
        proposed, reserved = str(document.get("version") or ""), row.version
        taken = _labels(session) - {reserved}
        document["version"] = proposed if proposed and proposed not in taken else reserved
        seconds = round(clock() - started, 1)
        try:
            effective = date.fromisoformat(str(document.get("effective_from"))) if document.get("effective_from") else None
        except ValueError:
            effective = None  # the validator reports the bad date
        info = {"not_expressed": d.not_expressed, "translation_notes": d.translation_notes, "llm_attempts": d.attempts,
                "proposed_version": proposed or None, "mode": d.mode, "operations": d.operations, "seconds": seconds}
        if _finish(session, row_id, drafting_status="ready", document=document, version=document["version"],
                   effective_from=effective, change_summary=str(document.get("change_summary") or ""),
                   drafted_by=d.drafted_by, draft_info=plain(info)):
            _audit(session, user, None, "policy.draft", row, drafted_by=d.drafted_by, seconds=seconds, mode=d.mode)
        session.commit()


def create_draft(session, user, client=None, text=None, source_name=None, from_current=False):
    """Synchronous convenience (scripts, tests): start the draft and make it now. Returns the finished row."""
    if from_current:
        return create_manual_draft(session, user)
    row = start_draft(session, user, client, text, source_name)
    run_draft(make_factory(session), row.id, client)
    session.expire_all()
    return session.get(PolicyVersion, row.id)


def make_factory(session):
    from db.session import make_session_factory
    return make_session_factory(session.get_bind())


def expire_stuck(session, now=None):
    """Drafts still drafting after DRAFTING_TIMEOUT become failed. Returns how many."""
    now = now or _now()
    stuck = [r for r in session.scalars(select(PolicyVersion).where(PolicyVersion.drafting_status == "drafting"))
             if _aware(r.drafting_started_at) is None or now - _aware(r.drafting_started_at) > DRAFTING_TIMEOUT]
    minutes = int(DRAFTING_TIMEOUT.total_seconds() // 60)
    for r in stuck:
        if _finish(session, r.id, drafting_status="failed",
                   drafting_error=f"The AI did not finish within {minutes} minutes. {MANUAL_PATH}"):
            _audit(session, "system", None, "llm.failure", r, "drafting timed out")
    session.commit()
    return len(stuck)


def fail_interrupted(session):
    """On startup: no background task survives a restart, so any draft still drafting has stopped."""
    rows = session.scalars(select(PolicyVersion).where(PolicyVersion.drafting_status == "drafting")).all()
    for r in rows:
        if _finish(session, r.id, drafting_status="failed",
                   drafting_error=f"The server restarted while this draft was being made. {MANUAL_PATH}"):
            _audit(session, "system", None, "llm.failure", r, "server restarted while drafting")
    session.commit()
    return len(rows)


def _ready(row):
    if row.drafting_status == "drafting":
        raise AmendmentError("The AI is still drafting this version; wait for it to finish.", 409)
    if row.drafting_status == "failed":
        raise AmendmentError(f"Drafting failed: {row.drafting_error} Discard this draft, or start from the current "
                             f"version.", 409)
    return row


def check(session, row):
    """Validation, plain-language diff against the base, and whether the draft is complete."""
    base = session.get(PolicyVersion, row.base_version_id) if row.base_version_id else None
    if row.document is None:  # still drafting, or drafting failed
        return {"errors": [], "warnings": [], "incomplete": True, "diff": [],
                "base_version": base.version if base else None}
    errors, warnings = validate(row.document, base.document if base else None)
    if not row.document.get("effective_from"):
        errors = ["effective_from: the amendment gives no effective date; enter one before approval"] + \
                 [e for e in errors if not e.startswith("effective_from")]
    return {"errors": errors, "warnings": warnings, "incomplete": not row.document.get("effective_from"),
            "diff": explain(base.document, row.document) if base else [], "base_version": base.version if base else None}


def view(session, version_id):
    expire_stuck(session)
    row = _get(session, version_id)
    info = row.draft_info or {}
    return {"id": row.id, "version": row.version, "status": row.status,
            "drafting_status": row.drafting_status, "drafting_error": row.drafting_error,
            "drafting_started_at": plain(row.drafting_started_at), "drafting_seconds": info.get("seconds"),
            "draft_mode": info.get("mode"), "operations": info.get("operations"),
            "effective_from": row.effective_from.isoformat() if row.effective_from else None,
            "change_summary": row.change_summary, "drafted_by": row.drafted_by, "created_by": row.created_by,
            "approved_by": row.approved_by, "approved_at": plain(row.approved_at), "closed_by": row.closed_by,
            "closed_at": plain(row.closed_at), "close_comment": row.close_comment,
            "not_expressed": info.get("not_expressed", []), "translation_notes": info.get("translation_notes", []),
            "llm_attempts": info.get("llm_attempts", []), "proposed_version": info.get("proposed_version"),
            "source_document_name": row.source_document_name,
            "source_document_text": row.source_document_text, "impact_summary": row.impact_summary,
            **check(session, row), "document": row.document}


def update_draft(session, version_id, document, user):
    row = _ready(_draft(session, version_id))
    if not isinstance(document, dict):
        raise AmendmentError("The edited draft must be a JSON object (the whole policy document).")
    label = str(document.get("version") or "")
    if label != row.version and label in _labels(session):
        raise AmendmentError(f"Version label {label} is already used; choose another.", 409)
    _sync(row, copy.deepcopy(document))
    _audit(session, user, None, "policy.edit", row)
    session.commit()
    return row


def latest_batch_id(session):
    return session.scalar(select(PrBatch.id).order_by(PrBatch.id.desc()).limit(1))


def preview(session, version_id, batch_id=None):
    row = _ready(_get(session, version_id))
    if not row.document.get("effective_from"):
        raise AmendmentError("Enter an effective date before previewing the impact.")
    errors = check(session, row)["errors"]
    if errors:
        raise AmendmentError("Fix the draft before previewing: " + "; ".join(errors[:5]))
    batch_id = batch_id or latest_batch_id(session)
    if not batch_id:
        return {"batch_id": None, "explanation": "No batch has been processed yet, so there is nothing to preview."}
    if not session.get(PrBatch, batch_id):
        raise AmendmentError(f"There is no batch {batch_id}.", 404)
    master = database.load_master(session)
    result = impact(database.load_pr_lines(session, batch_id), master, row.document)
    return {"batch_id": batch_id, **result}


def approve(session, version_id, user, role, batch_id=None):
    if not (user or "").strip():
        raise AmendmentError("Approval needs your name.", 403)
    if (role or "").strip().lower() != APPROVER_ROLE:
        raise AmendmentError("Only the Procurement role can approve a policy version.", 403)
    row = _ready(_draft(session, version_id))
    errors = check(session, row)["errors"]
    if errors:
        raise AmendmentError("This draft cannot be approved until these are fixed: " + "; ".join(errors), 422)
    summary = preview(session, version_id, batch_id)
    summary["changes"] = summary.get("changes", [])[:200]  # keep the stored summary a sensible size
    row.status, row.approved_by, row.approved_at = "approved", user.strip(), datetime.now(timezone.utc)
    row.impact_summary = plain(summary)
    _audit(session, user, role, "policy.approve", row, version=row.version, changed=summary.get("changed"))
    session.commit()
    return row


def discard(session, version_id, user, comment=None):
    row = _draft(session, version_id)
    row.status, row.closed_by, row.closed_at, row.close_comment = "discarded", user, datetime.now(timezone.utc), comment
    _audit(session, user, None, "policy.discard", row, comment)
    session.commit()
    return row


def withdraw(session, version_id, user, role, comment):
    if not (user or "").strip():
        raise AmendmentError("Withdrawing a version needs your name.", 403)
    if (role or "").strip().lower() != APPROVER_ROLE:
        raise AmendmentError("Only the Procurement role can withdraw a policy version.", 403)
    if not (comment or "").strip():
        raise AmendmentError("Say why the version is withdrawn.")
    row = _get(session, version_id)
    if row.status != "approved":
        raise AmendmentError(f"Version {row.version} is {row.status}; only an approved version can be withdrawn.", 409)
    others = session.scalars(select(PolicyVersion).where(PolicyVersion.status == "approved", PolicyVersion.id != row.id)).all()
    if not others:
        raise AmendmentError("This is the only approved version; approve another before withdrawing it.", 409)
    row.status, row.closed_by, row.closed_at, row.close_comment = "withdrawn", user.strip(), datetime.now(timezone.utc), comment
    _audit(session, user, role, "policy.withdraw", row, comment)
    session.commit()
    return row


def listing(session):
    expire_stuck(session)
    rows = session.scalars(select(PolicyVersion).order_by(PolicyVersion.id))
    return [{"id": r.id, "policy_id": r.policy_id, "version": r.version, "status": r.status,
             "drafting_status": r.drafting_status, "drafting_seconds": (r.draft_info or {}).get("seconds"),
             "effective_from": r.effective_from.isoformat() if r.effective_from else None,
             "change_summary": r.change_summary, "drafted_by": r.drafted_by, "approved_by": r.approved_by,
             "approved_at": plain(r.approved_at), "closed_by": r.closed_by, "base_version_id": r.base_version_id}
            for r in rows]
