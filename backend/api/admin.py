"""POST /api/admin/load-kit (Procurement): load the task kit uploaded as the original zip, a zip without the
top folder, or the individual files (services/kit.py). Any multipart field name; or a zip as the raw body."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.deps import get_session, require_role
from services import kit

router = APIRouter()

MAX_REQUEST_BYTES = 60 * 1024 * 1024


async def uploaded_files(request: Request):
    """[(file name, bytes)] from a multipart upload (every file field) or a raw zip body."""
    if int(request.headers.get("content-length") or 0) > MAX_REQUEST_BYTES:
        raise HTTPException(413, f"The upload is larger than {MAX_REQUEST_BYTES // 2**20} MB; the kit zip is under 1 MB.")
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        files = [(value.filename or key, await value.read()) for key, value in form.multi_items() if hasattr(value, "read")]
    else:
        body = await request.body()
        files = [(request.headers.get("x-filename") or "kit.zip", body)] if body else []
    if not files:
        raise HTTPException(400, "The upload contained no file. Send the kit zip, or the kit's CSV and contract "
                                 "PDF files, as file fields.")
    return files


@router.post("/api/admin/load-kit")
async def load_kit(request: Request, session: Session = Depends(get_session)):
    user, role = require_role(request, "Procurement")
    files = await uploaded_files(request)
    try:
        return kit.load_kit(session, files, user, role)
    except kit.KitError as exc:
        raise HTTPException(400, str(exc)) from exc
