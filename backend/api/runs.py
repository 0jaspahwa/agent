"""Read stored runs and their exports (G2), and the policy versions."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session
from db.models import Run
from engine.export import preferred_csv
from loaders import database
from services import runs

router = APIRouter()


def _run(session, run_id):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, f"There is no run {run_id}.")
    return run


@router.get("/api/runs")
def list_runs(session: Session = Depends(get_session)):
    return [runs.describe(session, r) for r in session.scalars(select(Run).order_by(Run.id.desc()))]


@router.get("/api/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    return runs.describe(session, _run(session, run_id))


@router.get("/api/runs/{run_id}/export.csv")
def run_export(run_id: int, session: Session = Depends(get_session)):
    _run(session, run_id)
    return Response(runs.export_csv(session, run_id), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="run-{run_id}-decisions.csv"'})


@router.get("/api/preferred-suppliers/export.csv")
def preferred_export(as_of: str = Query(..., description="YYYY-MM-DD"), session: Session = Depends(get_session)):
    try:
        on = date.fromisoformat(as_of.strip())
    except ValueError as exc:
        raise HTTPException(400, f"as_of must be a date like 2026-11-01, not {as_of!r}.") from exc
    try:
        text = preferred_csv(database.load_master(session), on)
    except LookupError as exc:
        raise HTTPException(400, f"No preferred list for {on}: {exc}.") from exc
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="preferred-suppliers-{on}.csv"'})

