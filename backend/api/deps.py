"""Shared request helpers: a database session per request, and who is asking (X-User and X-Role headers;
docs/data_model.md, DECISIONS.md D35: no login, so this records intent, it is not security)."""
from urllib.parse import unquote

from fastapi import HTTPException, Request

ROLES = {"requester": "Requester", "buyer": "Buyer", "procurement": "Procurement"}


def get_session(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def current_user(request: Request, default="api"):
    """The X-User header (the interface percent-encodes it, so any name fits in a header), or a default for
    clients that do not send one (D29)."""
    return unquote(request.headers.get("x-user") or "").strip() or default


def current_role(request: Request):
    """'Requester', 'Buyer' or 'Procurement', or None."""
    return ROLES.get((request.headers.get("x-role") or "").strip().lower())


def require_role(request: Request, *allowed):
    """(name, role) of the caller, or a 403 with a plain sentence if the role may not do this."""
    name, role = current_user(request, default=""), current_role(request)
    if not name:
        raise HTTPException(403, "Say who you are first: this action needs your name.")
    if role not in allowed:
        raise HTTPException(403, f"This needs the {' or '.join(allowed)} role"
                                 + (f"; you are signed in as {role}." if role else "."))
    return name, role


def wants_csv(request: Request):
    return request.query_params.get("format", "").lower() == "csv" or \
        "text/csv" in request.headers.get("accept", "").lower()
