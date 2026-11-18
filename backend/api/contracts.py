"""B6: contracts over HTTP (Buyer or Procurement; thin handlers over services/contracts.py).

GET  /api/contracts               every contract: supplier, validity, ceiling, consumed (register) and source
POST /api/contracts/read-pdf      multipart file: the deterministic reader's form, or why it could not read it;
                                  ?llm=1 asks the AI instead (a draft marked as needing checking)
POST /api/contracts               {"form": {...}, "source": "pdf" | "manual", "source_file"?}: validate and save
GET  /api/items                   the item master, for forms and pickers
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.deps import get_session, require_role
from services import contracts

router = APIRouter()
BUYERS = ("Buyer", "Procurement")


@router.get("/api/contracts")
def listing(request: Request, session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    return contracts.listing(session)


@router.post("/api/contracts/read-pdf")
async def read_pdf(request: Request, llm: bool = False, session: Session = Depends(get_session)):
    require_role(request, *BUYERS)
    form = await request.form()
    upload = next((v for _, v in form.multi_items() if hasattr(v, "read")), None)
    if upload is None:
        raise HTTPException(400, "Choose the contract PDF first.")
    data = await upload.read()
    try:
        return contracts.read_pdf(data, upload.filename or "contract.pdf", request.app.state.contract_llm_client, llm)
    except contracts.ContractError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/api/contracts", status_code=201)
async def add(request: Request, session: Session = Depends(get_session)):
    user, role = require_role(request, *BUYERS)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("form"), dict):
        raise HTTPException(400, "Send {\"form\": {...}, \"source\": \"pdf\" or \"manual\"}.")
    try:
        return contracts.add(session, body["form"], user, role, body.get("source"), body.get("source_file"))
    except contracts.ContractError as exc:
        session.rollback()
        return JSONResponse({"detail": str(exc), "problems": exc.problems}, status_code=exc.status)


@router.get("/api/items")
def items(request: Request, session: Session = Depends(get_session)):
    require_role(request, "Requester", *BUYERS)
    return contracts.items(session)
