"""B4: the buyer workspace over HTTP (thin handlers over services/workspace.py). Buyer or Procurement only.

GET  /api/workspace/runs                      runs to choose from, with how many requirements need action
GET  /api/workspace?run_id=                   a run's requirements (default: the latest batch run; kind=chat for
                                              the open chat requests) and its NOT_PROCESSED lines
GET  /api/requirements/{id}                   one requirement
POST /api/requirements/{id}/approve           {"versions": {"<id>": <version>, ...}}: every open requirement on
                                              its PO, as the buyer confirmed them; 409 if anyone acted first
POST /api/requirements/{id}/override          {"version", "route", "comment", "supplier_id"?, "unit_price"?,
                                              "suggested_supplier_ids"?}
GET  /api/suppliers?category=                 suppliers with status, for choosing in an override
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.deps import get_session, require_role
from services import workspace as ws

router = APIRouter()
BUYERS = ("Buyer", "Procurement")


def _fail(session, exc):
    session.rollback()
    raise HTTPException(exc.status, str(exc)) from exc


async def _body(request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "Send a JSON object.")
    return body


@router.get("/api/workspace/runs")
def runs(request: Request, session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    return ws.runs(session)


@router.get("/api/workspace")
def workspace(request: Request, run_id: int | None = None, kind: str = "batch", session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    run_id = run_id or ws.default_run_id(session, kind)
    if not run_id:
        return {"run": None, "requirements": [], "not_processed": [], "plants": [], "routes": []}
    try:
        return ws.workspace(session, run_id)
    except ws.WorkspaceError as exc:
        _fail(session, exc)


@router.get("/api/requirements/{req_id}")
def requirement(req_id: int, request: Request, session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    try:
        return ws.requirement(session, req_id)
    except ws.WorkspaceError as exc:
        _fail(session, exc)


@router.post("/api/requirements/{req_id}/approve")
async def approve(req_id: int, request: Request, session: Session = Depends(get_session)):
    user, role = require_role(request, *BUYERS)
    body = await _body(request)
    try:
        record = ws.approve(session, req_id, body.get("versions"), user, role)
    except ws.WorkspaceError as exc:
        _fail(session, exc)
    return {"record": record, "requirement": ws.requirement(session, req_id)}


@router.post("/api/requirements/{req_id}/override")
async def override(req_id: int, request: Request, session: Session = Depends(get_session)):
    user, role = require_role(request, *BUYERS)
    body = await _body(request)
    if "version" not in body:
        raise HTTPException(400, "Send the version of the requirement you are overriding.")
    try:
        record = ws.override(session, req_id, body["version"], user, role, body.get("route"), body.get("comment"),
                             body.get("supplier_id"), body.get("unit_price"), body.get("suggested_supplier_ids"))
    except ws.WorkspaceError as exc:
        _fail(session, exc)
    return {"record": record, "requirement": ws.requirement(session, req_id)}


@router.get("/api/suppliers")
def suppliers(request: Request, category: str | None = None, session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    return ws.suppliers_for(session, category)
