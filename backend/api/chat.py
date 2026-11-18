"""B2: chat intake over HTTP (thin handlers; the conversation is chat/conversation.py, stored by services/chat.py).

POST /api/chat/conversations                  start one (Requester or Procurement)
GET  /api/chat/conversations/{id}             its messages, the draft PR so far, what is missing, the choices
POST /api/chat/conversations/{id}/messages    {"text": "..."} or {"event": {"type": "choose", "item_code": ...}}
GET  /api/chat/requests                       the caller's PRs made in chat, with their status
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.deps import get_session, require_role
from services import amendments, chat

router = APIRouter()
CHAT_ROLES = ("Requester", "Procurement")
EVENTS = {"choose", "new_item", "describe_again", "urgency", "create", "cancel"}


def _fail(session, exc):
    session.rollback()
    raise HTTPException(exc.status, str(exc)) from exc


@router.post("/api/chat/conversations", status_code=201)
def start(request: Request, session: Session = Depends(get_session)):
    user, role = require_role(request, *CHAT_ROLES)
    conv = chat.start(session, user, role)
    return chat.view(session, conv.id, user)


@router.get("/api/chat/conversations/{conv_id}")
def get(conv_id: int, request: Request, session: Session = Depends(get_session)):
    user, _ = require_role(request, *CHAT_ROLES)
    try:
        return chat.view(session, conv_id, user)
    except chat.ChatError as exc:
        _fail(session, exc)


@router.post("/api/chat/conversations/{conv_id}/messages")
async def message(conv_id: int, request: Request, background: BackgroundTasks, session: Session = Depends(get_session)):
    user, role = require_role(request, *CHAT_ROLES)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "Send {\"text\": \"...\"} or {\"event\": {...}}.")
    if isinstance(body.get("event"), dict):
        event = body["event"]
        if event.get("type") not in EVENTS:
            raise HTTPException(400, f"Unknown chat action. Use one of: {', '.join(sorted(EVENTS))}.")
    else:
        event = {"type": "message", "text": body.get("text")}
    try:
        result, drafts = chat.post(session, conv_id, user, role, event, request.app.state.chat_llm_client,
                                   request.app.state.llm_client)
    except chat.ChatError as exc:
        _fail(session, exc)
    for draft_id in drafts:
        background.add_task(amendments.run_draft, request.app.state.session_factory, draft_id, request.app.state.llm_client)
    return result


@router.get("/api/chat/requests")
def my_requests(request: Request, session: Session = Depends(get_session)):
    user, _ = require_role(request, *CHAT_ROLES)
    return chat.my_requests(session, user)
