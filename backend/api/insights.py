"""B8 and B9: read-only views for Buyer and Procurement.

GET /api/preferred-suppliers?item_code=&as_of=   the item's preferred list on that date (policy 6.1-6.3): every
                                                 member with its score, the parts of the score and its reference
                                                 price, and which ones the export takes (top 3); plus the category
                                                 top-ups used for sourcing suggestions (6.4)
GET /api/audit?actor=&action=&limit=             the audit log, newest first (read-only; the table is append-only)
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session, require_role
from db.models import AuditLog
from engine.preferred import preferred_list, topup_suppliers
from engine.versions import version_in_force
from loaders import database
from services.snapshot import plain

router = APIRouter()
BUYERS = ("Buyer", "Procurement")
EXPORT_TOP = 3


@router.get("/api/preferred-suppliers")
def preferred(request: Request, item_code: str = Query(...), as_of: str = Query(...),
              session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    try:
        on = date.fromisoformat(as_of.strip())
    except ValueError as exc:
        raise HTTPException(400, f"as_of must be a date like 2026-11-01, not {as_of!r}.") from exc
    master = database.load_master(session)
    code = item_code.strip().upper()
    if code not in master.items:
        raise HTTPException(404, f"{code} is not in the item master.")
    version = version_in_force(master.policies, on)
    if version is None:
        raise HTTPException(400, f"No approved policy version is in force on {on}.")
    params = version.document["parameters"]
    item = master.items[code]

    def supplier(sid):
        s = master.suppliers[sid]
        return {"supplier_id": sid, "name": s.name, "status": s.status, "on_time_pct": plain(s.on_time_pct),
                "quality": plain(s.quality_rating)}
    ranked = preferred_list(code, on, master, params)
    members = [{**supplier(r.supplier_id), "rank": r.rank, "score": plain(r.score), "parts": dict(plain(r.parts)),
                "inputs": plain(r.inputs), "reference_price": plain(r.reference_price), "reference": r.reference,
                "exported": r.rank <= EXPORT_TOP} for r in ranked]
    statuses = params["suppliers"]["allowed_statuses"]["be_suggested"]
    topups = [{**supplier(sid), "score": plain(score), "parts": dict(plain(parts))}
              for sid, score, parts in topup_suppliers(code, master, params, statuses, exclude={r.supplier_id for r in ranked})]
    return {"item": {"item_code": code, "description": item.description, "category": item.category, "uom": item.uom},
            "as_of": on.isoformat(), "policy_version": version.version, "weights": params["ranking"]["preferred_score"]["weights"],
            "preferred": members, "topups": topups}


@router.get("/api/audit")
def audit(request: Request, actor: str | None = None, action: str | None = None, limit: int = 500,
          session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 2000)))
    if actor:
        query = query.where(AuditLog.actor == actor)
    if action:
        query = query.where(AuditLog.action.startswith(action))
    rows = session.scalars(query).all()
    actors = sorted(set(session.scalars(select(AuditLog.actor).distinct())))
    actions = sorted(set(session.scalars(select(AuditLog.action).distinct())))
    return {"entries": [{"id": r.id, "at": plain(r.at), "actor": r.actor, "role": r.actor_role, "action": r.action,
                         "entity_type": r.entity_type, "entity_id": r.entity_id, "comment": r.comment,
                         "details": r.details} for r in rows], "actors": actors, "actions": actions}
