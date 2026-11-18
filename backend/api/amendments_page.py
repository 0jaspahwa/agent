"""H8: the amendments section of the operations page (plain HTML forms, no JavaScript).

/ops/amendments            versions and their status; start a draft from a file, from pasted text, or from the
                       current version with no AI at all
/ops/amendments/{id}       one version: what changes in plain words, validation, what the AI could not express,
                       the JSON to edit, the impact on a stored batch (?preview=<batch id>), approve or discard;
                       withdraw for an approved version
"""
import json
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session
from api.ops import page
from api.policies import body_fields, start_draft
from db.models import PrBatch
from services import amendments as svc

router = APIRouter()
NAV = "<p><a href='/ops/amendments'>All policy versions</a></p>"


def items(values, empty="none"):
    return "<ul>" + "".join(f"<li>{escape(str(v))}</li>" for v in values) + "</ul>" if values else f"<p class='muted'>{empty}</p>"


def status_words(v):
    if v["status"] == "draft" and v["drafting_status"] != "ready":
        return {"drafting": "draft (AI drafting...)", "failed": "draft (drafting failed)"}[v["drafting_status"]]
    return v["status"]


def who_fields():
    return ("<label>Your name <input name='user' required></label> "
            "<label>Role <select name='role'><option>Procurement</option><option>Buyer</option></select></label>")


@router.get("/ops/amendments", response_class=HTMLResponse)
def index(session: Session = Depends(get_session)):
    rows = "".join(
        f"<tr><td><a href='/ops/amendments/{v['id']}'>{escape(v['version'])}</a></td><td>{escape(status_words(v))}</td>"
        f"<td>{escape(v['effective_from'] or 'not set')}</td><td>{escape(v['change_summary'] or '')}</td>"
        f"<td>{escape(v['approved_by'] or v['drafted_by'] or '')}</td></tr>" for v in reversed(svc.listing(session)))
    body = f"""
<table><tr><th>Version</th><th>Status</th><th>Effective from</th><th>Change</th><th>By</th></tr>{rows}</table>
<form method="post" action="/ops/amendments/new" enctype="multipart/form-data">
  <h2>Draft a new version from an amendment</h2>
  <p>The AI only drafts. You review the plain-language changes and the impact, and approve.</p>
  <p>{who_fields()}</p>
  <p>Amendment document (PDF, DOCX, TXT or MD): <input type="file" name="file" accept=".pdf,.docx,.txt,.md"></p>
  <p>or paste its text:<br><textarea name="text" rows="6" cols="80"></textarea></p>
  <p><button type="submit">Draft with AI</button></p>
</form>
<form method="post" action="/ops/amendments/new">
  <h2>Or edit the current version by hand (no AI)</h2>
  <p>{who_fields()} <input type="hidden" name="from_current" value="true">
  <button type="submit">Start from the current version</button></p>
</form>"""
    return page("Policy versions and amendments", body)


def _procurement(fields):
    """The name and role typed in the form (the page has no login). Every change to the policy needs the
    Procurement role, as in the API; returns (name, a plain error or None)."""
    name = (fields.get("user") or "").strip()
    if not name:
        return name, "Enter your name."
    if (fields.get("role") or "").strip().lower() != "procurement":
        return name, "Only the Procurement role can change the policy."
    return name, None


@router.post("/ops/amendments/new", response_class=HTMLResponse)
async def new(request: Request, background: BackgroundTasks, session: Session = Depends(get_session)):
    fields, upload = await body_fields(request)
    user, refused = _procurement(fields)
    if refused:
        return page("No draft made", f"<p class='error'>{escape(refused)}</p>{NAV}", 403)
    try:
        row = start_draft(request, session, fields, upload, user, background)
    except HTTPException as exc:
        return page("The amendment could not be read", f"<p class='error'>{escape(str(exc.detail))}</p>{NAV}", exc.status_code)
    except svc.AmendmentError as exc:
        session.rollback()
        return page("No draft made", f"<p class='error'>{escape(str(exc))}</p>{manual_form()}{NAV}", exc.status)
    return RedirectResponse(f"/ops/amendments/{row.id}", status_code=303)


def manual_form():
    return f"""<form method="post" action="/ops/amendments/new"><input type="hidden" name="from_current" value="true">
<p>{who_fields()}
<button type="submit">Start from the current version and edit it by hand</button></p></form>"""


def made_by(v):
    """Which model produced the draft and how long it took."""
    if v["drafted_by"].startswith("llm:") and v["drafting_seconds"] is not None:
        return f"drafted by {v['drafted_by'][4:]} in {v['drafting_seconds']:.0f} s ({v['draft_mode'] or 'operations'})"
    return f"drafted by {v['drafted_by']}"


def impact_html(result):
    if result.get("batch_id") is None:
        return f"<p>{escape(result['explanation'])}</p>"
    rows = "".join(
        f"<tr><td>{escape(c['line'])}</td><td>{escape(c['rule_before'])} → {escape(c['rule_after'])}</td><td>"
        + "<br>".join(f"{escape(k)}: {escape(str(v['before']))} → {escape(str(v['after']))}" for k, v in c["changes"].items())
        + "</td></tr>" for c in result["changes"][:300])
    routes = sorted(set(result["routes_before"]) | set(result["routes_after"]))
    counts = "".join(f"<tr><td>{escape(r)}</td><td>{result['routes_before'].get(r, 0)}</td>"
                     f"<td>{result['routes_after'].get(r, 0)}</td></tr>" for r in routes)
    return (f"<p><b>{escape(result['explanation'])}</b> (batch {result['batch_id']}, requirements "
            f"{' to '.join(result['batch_dates'])}; {result['lines_under_draft']} lines fall under the draft).</p>"
            f"<table><tr><th>Route</th><th>Before</th><th>After</th></tr>{counts}</table>"
            + (f"<h3>Lines that change</h3><table><tr><th>Line</th><th>Rule</th><th>What changes</th></tr>{rows}</table>"
               if rows else ""))


@router.get("/ops/amendments/{version_id}", response_class=HTMLResponse)
def show(version_id: int, preview: int | None = None, error: str | None = None,
         session: Session = Depends(get_session), edited: str | None = None):
    try:
        v = svc.view(session, version_id)
    except svc.AmendmentError as exc:
        return page("Not found", f"<p class='error'>{escape(str(exc))}</p>{NAV}", exc.status)
    if v["status"] == "draft" and v["drafting_status"] == "drafting":
        return page(f"Drafting version {v['version']}", f"""<p><b>The AI is drafting this amendment.</b> This page
checks again every 5 seconds; it usually takes under a minute. If it takes more than 5 minutes it is marked failed.</p>
<p class='muted'>Started {escape(str(v['drafting_started_at'])[:19])} UTC from {escape(v['source_document_name'] or '')}.</p>
<p>You do not have to wait:</p>{manual_form()}{NAV}""", refresh=5)
    if v["status"] == "draft" and v["drafting_status"] == "failed":
        return page(f"Drafting failed for version {v['version']}", f"""<p class='error'>{escape(v['drafting_error'] or '')}</p>
{manual_form()}
<form method="post" action="/ops/amendments/{version_id}/discard"><p>{who_fields()}
<input type="hidden" name="comment" value="drafting failed"><button type="submit">Discard this failed draft</button></p></form>{NAV}""")
    draft = v["status"] == "draft"
    parts = [f"<p>Status <b>{escape(v['status'])}</b> · effective from <b>{escape(v['effective_from'] or 'NOT SET')}</b>"
             f" · based on {escape(v['base_version'] or '-')} · {escape(made_by(v))}</p>"]
    if error:
        parts.append(f"<p class='error'>{escape(error)}</p>")
    if v["approved_by"]:
        parts.append(f"<p>Approved by {escape(v['approved_by'])} at {escape(str(v['approved_at'])[:19])} UTC</p>")
    if v["closed_by"]:
        parts.append(f"<p>{escape(v['status'].capitalize())} by {escape(v['closed_by'])}: {escape(v['close_comment'] or '')}</p>")
    parts.append("<h2>What changes</h2>" + items(v["diff"], "Nothing differs from the base version yet."))
    if v["errors"]:
        parts.append("<h2 class='error'>Must be fixed before approval</h2>" + items(v["errors"]))
    if v["warnings"]:
        parts.append("<h2>Warnings</h2>" + items(v["warnings"]))
    parts.append("<h2>What the AI could not express</h2>" + items(v["not_expressed"], "nothing reported"))
    if v["translation_notes"]:
        parts.append("<h2>Translation notes</h2>" + items(v["translation_notes"]))
    if v["source_document_text"]:
        parts.append(f"<details><summary>Amendment text ({escape(v['source_document_name'] or '')})</summary>"
                     f"<pre style='white-space:pre-wrap'>{escape(v['source_document_text'])}</pre></details>")
    if draft:
        batches = session.scalars(select(PrBatch).order_by(PrBatch.id.desc()).limit(20)).all()
        options = "".join(f"<option value='{b.id}' {'selected' if b.id == preview else ''}>batch {b.id}: "
                          f"{escape(b.filename)} ({b.line_count} lines)</option>" for b in batches)
        parts.append(f"""<form method="get" action="/ops/amendments/{version_id}"><h2>Impact preview</h2>
<p><select name="preview">{options or "<option value=''>no batch processed yet</option>"}</select>
<button type="submit">Preview the impact</button></p></form>""")
        if preview:
            try:
                parts.append(impact_html(svc.preview(session, version_id, preview)))
            except svc.AmendmentError as exc:
                parts.append(f"<p class='error'>{escape(str(exc))}</p>")
        text = edited if edited is not None else json.dumps(v["document"], indent=2, ensure_ascii=False)
        parts.append(f"""<form method="post" action="/ops/amendments/{version_id}/edit"><h2>Edit the draft (JSON)</h2>
<p>{who_fields()}</p>
<textarea name="document" rows="24" cols="100" style="font-family:monospace">{escape(text)}</textarea>
<p><button type="submit">Save and re-check</button></p></form>
<form method="post" action="/ops/amendments/{version_id}/approve"><h2>Approve</h2>
<p>Activates version {escape(v['version'])} from {escape(v['effective_from'] or '(set an effective date first)')}.
The impact on the latest batch is stored with the approval.</p><p>{who_fields()} <button type="submit">Approve</button></p></form>
<form method="post" action="/ops/amendments/{version_id}/discard"><h2>Discard</h2>
<p>{who_fields()} <label>Why <input name="comment"></label>
<button type="submit">Discard this draft</button></p></form>""")
    elif v["status"] == "approved":
        parts.append(f"""<form method="post" action="/ops/amendments/{version_id}/withdraw"><h2>Withdraw</h2>
<p>Later runs stop using this version; past runs keep their record.</p>
<p>{who_fields()} <label>Why <input name="comment" required></label> <button type="submit">Withdraw</button></p></form>""")
        if v["impact_summary"]:
            parts.append("<h2>Impact recorded at approval</h2>" + impact_html(v["impact_summary"]))
    parts.append(f"<details><summary>Policy document (JSON)</summary><pre>{escape(json.dumps(v['document'], indent=2, ensure_ascii=False))}</pre></details>")
    return page(f"Policy version {v['version']}", "".join(parts) + NAV)


def back(version_id, error=None):
    return RedirectResponse(f"/ops/amendments/{version_id}" + (f"?error={quote(error)}" if error else ""), status_code=303)


@router.post("/ops/amendments/{version_id}/edit", response_class=HTMLResponse)
async def edit(version_id: int, request: Request, session: Session = Depends(get_session)):
    fields, _ = await body_fields(request)
    raw = fields.get("document") or ""
    try:
        document = json.loads(raw)
    except ValueError as exc:
        return show(version_id, error=f"The JSON could not be read: {exc}. Nothing was saved.", session=session, edited=raw)
    user, refused = _procurement(fields)
    if refused:
        return show(version_id, error=refused + " Nothing was saved.", session=session, edited=raw)
    try:
        svc.update_draft(session, version_id, document, user)
    except svc.AmendmentError as exc:
        session.rollback()
        return show(version_id, error=str(exc), session=session, edited=raw)
    return back(version_id)


@router.post("/ops/amendments/{version_id}/{action}", response_class=HTMLResponse)
async def act(version_id: int, action: str, request: Request,
              session: Session = Depends(get_session)):
    fields, _ = await body_fields(request)
    user, role, comment = (fields.get("user") or "").strip(), fields.get("role") or "", fields.get("comment")
    try:
        if action == "approve":
            svc.approve(session, version_id, user, role)
        elif action == "discard":
            name, refused = _procurement(fields)
            if refused:
                return back(version_id, refused)
            svc.discard(session, version_id, name, comment)
        elif action == "withdraw":
            svc.withdraw(session, version_id, user, role, comment)
        else:
            return page("Not found", f"<p class='error'>Unknown action.</p>{NAV}", 404)
    except svc.AmendmentError as exc:
        session.rollback()
        return back(version_id, str(exc))
    return back(version_id)
