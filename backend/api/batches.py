"""POST /api/process-batch: a PR batch CSV in, the decisions out (JSON, or the export CSV).

Optional policy_version (query parameter, form field, X-Policy-Version header or JSON field): decide every
requirement under that one approved version (H7). Without it, each requirement uses the version in force on
its requirement date."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from api.deps import current_user, get_session, wants_csv
from api.upload import read_batch
from loaders.pr_csv import BatchFormatError
from services import runs

router = APIRouter()


async def requested_version(request: Request):
    value = request.query_params.get("policy_version") or request.headers.get("x-policy-version")
    ctype = request.headers.get("content-type", "").lower()
    if not value and ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        field = (await request.form()).get("policy_version")
        value = field if isinstance(field, str) else None
    elif not value and ctype.startswith("application/json"):
        try:
            payload = json.loads((await request.body()) or b"{}")
        except ValueError:
            payload = {}
        value = payload.get("policy_version") if isinstance(payload, dict) else None
    return (value or "").strip() or None


@router.post("/api/process-batch")
async def process_batch(request: Request, session: Session = Depends(get_session)):
    filename, text = await read_batch(request)
    version = await requested_version(request)
    try:
        run, result, export, seconds = runs.process_batch(session, filename, text, current_user(request), version)
    except BatchFormatError as exc:
        session.rollback()
        raise HTTPException(400, f"The batch could not be read: {exc}") from exc
    except runs.UnknownVersion as exc:
        session.rollback()
        raise HTTPException(400, str(exc)) from exc
    except runs.NoKitData as exc:
        session.rollback()
        raise HTTPException(409, str(exc)) from exc
    headers = {"X-Run-Id": str(run.id), "X-Processing-Seconds": f"{seconds:.3f}",
               "X-Policy-Mode": run.inputs["policy_mode"]["mode"] + (f":{version}" if version else "")}
    if wants_csv(request):
        return Response(export, media_type="text/csv; charset=utf-8", headers=headers)
    body = {"run_id": run.id, "batch_id": run.batch_id, "filename": filename, "lines": len(result.rows),
            "requirements": len(result.requirements), "purchase_orders": len(result.purchase_orders),
            "summary_by_route": runs.route_counts(result), "policy_version_ids": run.policy_version_ids,
            "policy_mode": run.inputs["policy_mode"], "export_url": f"/api/runs/{run.id}/export.csv",
            "processing_seconds": round(seconds, 3),
            "decisions": [row.values for row in result.rows]}
    return JSONResponse(body, headers=headers)
