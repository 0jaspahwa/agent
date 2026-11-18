"""H8: the amendment workflow over HTTP and on the operations pages, with a fake LLM only."""
import copy
import json
import re
from pathlib import Path

import pytest

from amendments.simple_pdf import text_pdf
from engine.policy import load_policy
from kitdata import DATA_DIR
from llm.client import LLMClient, Unavailable

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
BASE = load_policy("5.0")
PROCUREMENT = {"x-user": "Asha Rao", "x-role": "Procurement"}


def fake(*replies):
    queue, seen = list(replies), []

    def call(system, user, model):
        seen.append(user)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    client = LLMClient([("fake", "m1"), ("fake", "m2")], {"fake": call}, sleep=lambda s: None)
    client.seen = seen
    return client


def proposal(effective_from="2026-04-01", spot=150000):
    doc = copy.deepcopy(BASE)
    doc.update(version="5.1", supersedes="5.0", effective_from=effective_from, source_document="A-1",
               change_summary="Spot PO limit lowered")
    doc["parameters"]["limits"]["spot_po"]["value"] = spot
    return as_operations(doc, ["the approval matrix change"])


def as_operations(doc, not_expressed=(), notes=()):
    """An operations-mode reply (the default DRAFT_MODE) that turns the base policy into `doc`."""
    ops = [{"op": "set", "path": f"parameters.{k}", "value": v} for k, v in doc["parameters"].items()]
    ops += [{"op": "replace", "section": "rules", "id": r["id"], "item": r} for r in doc["rules"]]
    return json.dumps({"version": doc["version"], "effective_from": doc["effective_from"],
                       "change_summary": doc["change_summary"], "source_document": doc["source_document"],
                       "operations": ops, "not_expressed": list(not_expressed), "translation_notes": list(notes)})


def test_the_whole_flow_over_the_api(client):
    client.post("/api/process-batch", content=SAMPLE)
    client.app.state.llm_client = llm = fake(proposal())
    pdf = text_pdf(["Amendment A-1", "Spot PO limit lowered to below Rs 1,50,000 from 1 April 2026."])
    created = client.post("/api/policies/drafts", files={"file": ("A-1.pdf", pdf, "application/pdf")},
                          headers=PROCUREMENT)
    assert created.status_code == 202, created.text  # returns at once; the AI drafts in the background
    assert created.json()["drafting_status"] == "drafting"
    draft = client.get(created.json()["poll_url"]).json()
    assert draft["drafting_status"] == "ready" and draft["drafting_seconds"] is not None
    assert "Spot PO limit lowered" in llm.seen[0]  # the PDF's text reached the drafting prompt
    assert draft["status"] == "draft" and draft["errors"] == [] and draft["not_expressed"] == ["the approval matrix change"]
    assert draft["source_document_name"] == "A-1.pdf" and draft["drafted_by"] == "llm:fake:m1"
    preview = client.post(f"/api/policies/drafts/{draft['id']}/preview", headers=PROCUREMENT).json()
    assert preview["changed"] > 0
    assert client.post(f"/api/policies/drafts/{draft['id']}/approve", headers={"x-user": "Asha"}).status_code == 403
    approved = client.post(f"/api/policies/drafts/{draft['id']}/approve", headers=PROCUREMENT).json()
    assert approved["status"] == "approved" and approved["impact_summary"]["changed"] == preview["changed"]
    edit = client.put(f"/api/policies/drafts/{draft['id']}", content=json.dumps(BASE), headers=PROCUREMENT)
    assert edit.status_code == 409
    statuses = {p["version"]: p["status"] for p in client.get("/api/policies").json()}
    assert statuses == {"5.0": "approved", "5.1": "approved"}
    run2 = client.post("/api/process-batch?format=csv", content=SAMPLE).text
    run1 = client.post("/api/process-batch?format=csv&policy_version=5.0", content=SAMPLE).text
    assert run1 == GOLDEN and run2 != GOLDEN
    withdrawn = client.post(f"/api/policies/{draft['id']}/withdraw", json={"comment": "rehearsal"}, headers=PROCUREMENT)
    assert withdrawn.json()["status"] == "withdrawn"
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text == GOLDEN


def test_an_llm_outage_fails_the_draft_plainly_and_the_manual_path_works(client):
    client.app.state.llm_client = fake(Unavailable("quota"), Unavailable("quota"))
    down = client.post("/api/policies/drafts", json={"text": "Spot limit lowered from 1 Dec 2026."}, headers=PROCUREMENT)
    assert down.status_code == 202 and "from_current" in down.json()["manual_path"]
    failed = client.get(down.json()["poll_url"]).json()
    assert failed["drafting_status"] == "failed" and "unavailable right now" in failed["drafting_error"]
    assert client.post(f"/api/policies/drafts/{failed['id']}/approve", headers=PROCUREMENT).status_code == 409
    manual = client.post("/api/policies/drafts", json={"from_current": True}, headers={"x-user": "asha", "x-role": "Procurement"})
    assert manual.status_code == 201 and manual.json()["incomplete"] and manual.json()["drafted_by"] == "manual:asha"
    doc = manual.json()["document"]
    doc.update(effective_from="2026-12-01")
    doc["parameters"]["limits"]["spot_po"]["value"] = 150000
    edited = client.put(f"/api/policies/drafts/{manual.json()['id']}", content=json.dumps(doc), headers=PROCUREMENT).json()
    assert edited["errors"] == [] and any("1,50,000" in s for s in edited["diff"])


def test_an_unreadable_reply_fails_the_draft_plainly(client):
    client.app.state.llm_client = fake("this is not JSON")
    reply = client.post("/api/policies/drafts", json={"text": "anything"}, headers=PROCUREMENT)
    assert "not valid JSON" in client.get(reply.json()["poll_url"]).json()["drafting_error"]


def test_bad_requests_get_plain_messages(client):
    assert client.post("/api/policies/drafts", json={"text": "   "}, headers=PROCUREMENT).status_code == 400
    assert client.put("/api/policies/drafts/1", content="{not json", headers=PROCUREMENT).status_code == 400
    assert client.post("/api/policies/drafts", json={"text": "x"}).status_code == 403  # no role
    assert client.get("/api/policies/999").status_code == 404
    only = client.post("/api/policies/1/withdraw", json={"comment": "x"}, headers=PROCUREMENT)
    assert only.status_code == 409 and "only approved version" in only.json()["detail"]


# ---------------------------------------------------------------- the operations pages
def location_id(response):
    return int(re.search(r"/ops/amendments/(\d+)", response.headers["location"]).group(1))


def test_the_pages_take_a_draft_from_start_to_approval_without_javascript(client):
    client.post("/api/process-batch", content=SAMPLE)
    index = client.get("/ops/amendments")
    assert index.status_code == 200 and "<script" not in index.text and "5.0" in index.text
    made = client.post("/ops/amendments/new", data={"user": "asha", "role": "Procurement", "from_current": "true"}, follow_redirects=False)
    assert made.status_code == 303
    vid = location_id(made)
    page = client.get(f"/ops/amendments/{vid}").text
    assert "NOT SET" in page and "Must be fixed before approval" in page
    bad = client.post(f"/ops/amendments/{vid}/edit", data={"user": "asha", "role": "Procurement", "document": "{oops"})
    assert "could not be read" in bad.text and "{oops" in bad.text  # the typed text is kept
    doc = client.get(f"/api/policies/{vid}").json()["document"]
    doc.update(effective_from="2026-04-01")
    doc["parameters"]["limits"]["spot_po"]["value"] = 150000
    client.post(f"/ops/amendments/{vid}/edit", data={"user": "asha", "role": "Procurement", "document": json.dumps(doc)})
    page = client.get(f"/ops/amendments/{vid}?preview=1").text
    assert "1,50,000" in page and "lines change" in page and "Must be fixed" not in page
    refused = client.post(f"/ops/amendments/{vid}/approve", data={"user": "Ravi", "role": "Buyer"})
    assert "Only the Procurement role" in refused.text
    client.post(f"/ops/amendments/{vid}/approve", data={"user": "Asha", "role": "Procurement"})
    page = client.get(f"/ops/amendments/{vid}").text
    assert "Status <b>approved</b>" in page and "Approved by Asha" in page and "Withdraw" in page
    assert "only version 5.1" in client.get("/ops").text  # the named-version choice on the batch form


def test_the_page_offers_the_manual_path_when_the_ai_is_down(client):
    client.app.state.llm_client = fake(Unavailable("quota"), Unavailable("quota"))
    down = client.post("/ops/amendments/new", data={"user": "asha", "role": "Procurement", "text": "Spot limit lowered."})
    assert down.status_code == 200 and "Drafting failed" in down.text and "unavailable right now" in down.text
    assert "Start from the current version" in down.text and "Discard this failed draft" in down.text


def test_the_page_shows_drafting_progress_then_the_model_and_time(client):
    from services import amendments as svc
    client.app.state.llm_client = fake(proposal())
    with client.app.state.session_factory() as s:
        row_id = svc.start_draft(s, "asha", client.app.state.llm_client, "Spot limit lowered.").id
    waiting = client.get(f"/ops/amendments/{row_id}").text
    assert "http-equiv='refresh'" in waiting and "The AI is drafting" in waiting
    assert "AI drafting" in client.get("/ops/amendments").text
    svc.run_draft(client.app.state.session_factory, row_id, client.app.state.llm_client)
    ready = client.get(f"/ops/amendments/{row_id}").text
    assert "drafted by fake:m1 in" in ready and "http-equiv" not in ready
