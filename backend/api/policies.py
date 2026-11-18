"""H8: policy versions and the amendment workflow over HTTP (thin handlers; the work is in services/amendments.py).

Who is asking comes from the X-User and X-Role headers (no login in this app; docs/data_model.md). Approving
and withdrawing need both, with the role Procurement.

GET  /api/policies                          every version with its status
GET  /api/policies/{id}                     one version: document, validation, plain diff, reviewer lists
POST /api/policies/drafts                   a draft: amendment file (multipart) or text (the AI drafts it in the
                                            background: 202, poll GET /api/policies/{id}), or from_current (no AI: 201)
PUT  /api/policies/drafts/{id}              replace the draft's document (the reviewer's edit)
POST /api/policies/drafts/{id}/preview      impact on a stored batch (?batch_id=, default the latest)
POST /api/policies/drafts/{id}/approve      X-User and X-Role: Procurement
POST /api/policies/drafts/{id}/discard
POST /api/policies/{id}/withdraw            X-User, X-Role: Procurement, {"comment": "..."}
"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from amendments.extract import ExtractError, extract_text, typed_text
from api.deps import current_user, get_session, require_role
from services import amendments as svc

router = APIRouter()
POLICY_ROLE = ("Procurement",)  # every change to the policy, drafts included (break-it pass, docs/break_it.md)
MANUAL = "POST /api/policies/drafts with {\"from_current\": true}, then PUT the edited document"


def role(request: Request):
    return (request.headers.get("x-role") or "").strip()


def fail(session, exc):
    session.rollback()
    raise HTTPException(exc.status, str(exc)) from exc


async def body_fields(request: Request):
    """Form or JSON fields as a dict, plus (filename, bytes) of an uploaded file if there is one."""
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        upload = None
        for key, value in form.multi_items():
            if hasattr(value, "read"):
                data = await value.read()
                if data:  # an empty file input (nothing chosen) is no upload
                    upload = (value.filename or key, data)
                    break
        return {k: v for k, v in form.multi_items() if isinstance(v, str)}, upload
    raw = await request.body()
    if not raw.strip():
        return {}, None
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, f"The JSON body could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Send a JSON object.")
    return payload, None


def truthy(value):
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


def start_draft(request, session, fields, upload, user, background):
    """Shared by the API and the operations page. Returns the new row: ready for a manual draft, or 'drafting'
    with run_draft queued on `background` (FastAPI BackgroundTasks) for an AI draft. Raises HTTPException or
    AmendmentError."""
    if truthy(fields.get("from_current")):
        return svc.create_manual_draft(session, user)
    try:
        if upload and upload[1]:
            name, text = upload[0], extract_text(*upload)
        else:
            name, text = fields.get("filename") or "typed text", typed_text(fields.get("text") or "")
    except ExtractError as exc:
        raise HTTPException(400, str(exc)) from exc
    client = request.app.state.llm_client
    row = svc.start_draft(session, user, client, text, name)
    background.add_task(svc.run_draft, request.app.state.session_factory, row.id, client)
    return row


@router.get("/api/policies")
def list_policies(session: Session = Depends(get_session)):
    return svc.listing(session)


@router.get("/api/policies/{version_id}")
def get_policy(version_id: int, session: Session = Depends(get_session)):
    try:
        return svc.view(session, version_id)
    except svc.AmendmentError as exc:
        fail(session, exc)


@router.post("/api/policies/drafts")
async def create_draft(request: Request, background: BackgroundTasks, session: Session = Depends(get_session)):
    """201 with a ready draft (from_current), or 202 with a draft the AI is making: poll GET /api/policies/{id}
    until drafting_status is 'ready' or 'failed' (failed carries a plain reason and the manual path)."""
    user, _ = require_role(request, *POLICY_ROLE)
    fields, upload = await body_fields(request)
    try:
        row = start_draft(request, session, fields, upload, user, background)
    except svc.AmendmentError as exc:
        fail(session, exc)
    body = {**svc.view(session, row.id), "poll_url": f"/api/policies/{row.id}", "manual_path": MANUAL}
    return JSONResponse(body, status_code=202 if row.drafting_status == "drafting" else 201)


@router.put("/api/policies/drafts/{version_id}")
async def edit_draft(version_id: int, request: Request, session: Session = Depends(get_session)):
    user, _ = require_role(request, *POLICY_ROLE)
    try:
        document = json.loads(await request.body())
    except ValueError as exc:
        raise HTTPException(400, f"The edited document is not valid JSON: {exc}") from exc
    try:
        svc.update_draft(session, version_id, document, user)
        return svc.view(session, version_id)
    except svc.AmendmentError as exc:
        fail(session, exc)


@router.post("/api/policies/drafts/{version_id}/preview")
def preview(version_id: int, request: Request, batch_id: int | None = None, session: Session = Depends(get_session)):
    require_role(request, *POLICY_ROLE)
    try:
        return svc.preview(session, version_id, batch_id)
    except svc.AmendmentError as exc:
        fail(session, exc)


@router.post("/api/policies/drafts/{version_id}/approve")
def approve(version_id: int, request: Request, batch_id: int | None = None, session: Session = Depends(get_session)):
    try:
        svc.approve(session, version_id, current_user(request, default=""), role(request), batch_id)
        return svc.view(session, version_id)
    except svc.AmendmentError as exc:
        fail(session, exc)


@router.post("/api/policies/drafts/{version_id}/discard")
async def discard(version_id: int, request: Request, session: Session = Depends(get_session)):
    user, _ = require_role(request, *POLICY_ROLE)
    fields, _ = await body_fields(request)
    try:
        svc.discard(session, version_id, user, fields.get("comment"))
        return svc.view(session, version_id)
    except svc.AmendmentError as exc:
        fail(session, exc)


@router.post("/api/policies/{version_id}/withdraw")
async def withdraw(version_id: int, request: Request, session: Session = Depends(get_session)):
    fields, _ = await body_fields(request)
    try:
        svc.withdraw(session, version_id, current_user(request, default=""), role(request), fields.get("comment"))
        return svc.view(session, version_id)
    except svc.AmendmentError as exc:
        fail(session, exc)
