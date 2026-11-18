"""G3: a minimal operations page at /ops (plain HTML forms, no JavaScript, no build step).

Load the task kit (Procurement; the kit is not in the repo); upload a batch -> summary counts and a link to the
decisions CSV; download the preferred-supplier CSV for a date; recent runs. Every page says when no kit is loaded. The Thursday fallback if the full interface is not ready; the React app replaces it.
"""
from html import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import current_user, get_session
from api.upload import decode
from db.models import Item, PolicyVersion, Run
from kitdata import NO_KIT_NOTICE
from loaders.pr_csv import BatchFormatError
from services import kit, runs

router = APIRouter()

STYLE = """body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;line-height:1.5}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .6rem;text-align:left}
form{margin:1rem 0;padding:1rem;border:1px solid #ccc}.error{color:#a00}.muted{color:#666}
.banner{background:#fff4d6;border:1px solid #e0b84c;padding:.6rem 1rem}"""

STATE = {"engine": None}  # set by main at startup, so every page can say when no kit is loaded


def kit_banner():
    engine = STATE["engine"]
    if engine is None:
        return ""
    with engine.connect() as conn:
        loaded = conn.execute(select(func.count()).select_from(Item)).scalar_one() > 0
    return "" if loaded else f"<p class='banner' role='status'><b>{escape(NO_KIT_NOTICE)}</b> <a href='/ops#kit'>Load kit data</a></p>"


def page(title, body, status=200, refresh=None):
    meta = f"<meta http-equiv='refresh' content='{int(refresh)}'>" if refresh else ""
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'>{meta}<title>{escape(title)}</title>"
                        f"<style>{STYLE}</style></head><body>{kit_banner()}<h1>{escape(title)}</h1>{body}"
                        f"<p class='muted'><a href='/ops'>Operations</a> · <a href='/ops/amendments'>Policy amendments</a> · <a href='/'>Main interface</a> · <a href='/docs'>API docs</a> · "
                        f"<a href='/api/health'>health</a></p></body></html>", status_code=status)


def table(counts):
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in counts.items())
    return f"<table><tr><th>Route</th><th>Lines</th></tr>{rows}</table>"


@router.get("/ops", response_class=HTMLResponse)
def home(session: Session = Depends(get_session)):
    recent = session.scalars(select(Run).order_by(Run.id.desc()).limit(10)).all()
    runs_html = "".join(
        f"<tr><td>{r.id}</td><td>{escape(str(r.started_at)[:19])}</td><td>{escape(r.started_by)}</td>"
        f"<td><a href='/api/runs/{r.id}/export.csv'>decisions CSV</a> · <a href='/api/runs/{r.id}'>details</a></td></tr>"
        for r in recent) or "<tr><td colspan='4'>No runs yet.</td></tr>"
    approved = session.scalars(select(PolicyVersion).where(PolicyVersion.status == "approved")
                               .order_by(PolicyVersion.effective_from, PolicyVersion.id)).all()
    options = "".join(f"<option value='{escape(v.version)}'>only version {escape(v.version)} "
                      f"(effective {v.effective_from})</option>" for v in approved)
    body = f"""
<form method="post" action="/ops/load-kit" enctype="multipart/form-data" id="kit">
  <h2>Load kit data</h2>
  <p>The task kit is not in the repo. Upload the kit zip as distributed (or a zip without its top folder, or the
  six CSV files and the contract PDFs). Loading the same kit again changes nothing. Procurement only.</p>
  <p><label>Your name <input name="user" required></label>
  <label>Role <select name="role"><option>Procurement</option><option>Buyer</option></select></label></p>
  <p><input type="file" name="files" accept=".zip,.csv,.pdf" multiple required> <button type="submit">Load kit data</button></p>
</form>
<form method="post" action="/ops" enctype="multipart/form-data">
  <h2>1. Process a PR batch</h2>
  <p>CSV in the sample batch format. <label>Your name <input name="user" placeholder="optional"></label></p>
  <p><label>Policy <select name="policy_version"><option value="">version in force on each requirement date</option>
  {options}</select></label></p>
  <p><input type="file" name="file" accept=".csv,text/csv" required> <button type="submit">Process</button></p>
</form>
<form method="get" action="/api/preferred-suppliers/export.csv">
  <h2>2. Preferred supplier lists</h2>
  <p>Top 3 per item as of <input type="date" name="as_of" value="2026-11-01" required>
  <button type="submit">Download CSV</button></p>
</form>
<h2>Recent runs</h2>
<table><tr><th>Run</th><th>Started (UTC)</th><th>By</th><th>Downloads</th></tr>{runs_html}</table>"""
    return page("Corvo procurement: operations", body)


@router.post("/ops", response_class=HTMLResponse)
async def upload(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    upload_file = form.get("file")
    if not hasattr(upload_file, "read"):
        return page("Nothing to process", "<p class='error'>Choose a CSV file first.</p>", 400)
    text = decode(await upload_file.read())
    user = (form.get("user") or "").strip() or current_user(request, default="operations page")
    version = (form.get("policy_version") or "").strip() or None
    try:
        run, result, _export, seconds = runs.process_batch(session, upload_file.filename or "batch.csv", text, user,
                                                           version)
    except BatchFormatError as exc:
        session.rollback()
        return page("The batch could not be read", f"<p class='error'>{escape(str(exc))}</p>", 400)
    except runs.UnknownVersion as exc:
        session.rollback()
        return page("Unknown policy version", f"<p class='error'>{escape(str(exc))}</p>", 400)
    except runs.NoKitData as exc:
        session.rollback()
        return page("No kit data loaded", f"<p class='error'>{escape(str(exc))}</p>", 409)
    body = f"""
<p>Run <b>{run.id}</b>: {escape(upload_file.filename or 'batch.csv')}, {len(result.rows)} lines,
{len(result.requirements)} requirements, {len(result.purchase_orders)} purchase orders, processed in {seconds:.1f} s.
Policy: {escape(run.inputs["policy_mode"]["note"])}.</p>
<p><a href="/api/runs/{run.id}/export.csv"><b>Download the decisions CSV</b></a> · <a href="/api/runs/{run.id}">run details (JSON)</a></p>
{table(runs.route_counts(result))}"""
    return page("Batch processed", body)


@router.post("/ops/load-kit", response_class=HTMLResponse)
async def load_kit(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    user = (form.get("user") or "").strip()
    if not user:
        return page("Kit not loaded", "<p class='error'>Type your name first.</p>", 400)
    if (form.get("role") or "").strip().lower() != "procurement":
        return page("Kit not loaded", "<p class='error'>Only the Procurement role can load the kit.</p>", 403)
    files = [(f.filename or "upload", await f.read()) for _k, f in form.multi_items() if hasattr(f, "read") and f.filename]
    if not files:
        return page("Kit not loaded", "<p class='error'>Choose the kit zip, or the kit's files, first.</p>", 400)
    try:
        summary = kit.load_kit(session, files, user, "Procurement")
    except kit.KitError as exc:
        return page("Kit not loaded", f"<p class='error'>{escape(str(exc))}</p>", 400)
    rows = "".join(f"<tr><td>{escape(name)}</td><td>{t['in_kit']}</td><td>{t['added']}</td></tr>"
                   for name, t in summary["tables"].items())
    ignored = "".join(f"<li>{escape(i)}</li>" for i in summary["ignored"])
    body = (f"<p><b>{escape(summary['message'])}</b></p><table><tr><th>Table</th><th>Rows in the kit</th>"
            f"<th>Added now</th></tr>{rows}</table><p>Contract PDFs read: {escape(', '.join(summary['contract_pdfs']))}</p>"
            + (f"<p>Not loaded:</p><ul>{ignored}</ul>" if ignored else ""))
    return page("Kit data", body)
