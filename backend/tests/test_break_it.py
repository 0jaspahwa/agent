"""S3: the break-it pass (docs/break_it.md). Each attack that got through is fixed and tested here; each that
was already refused is tested here too, so it stays refused."""
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kitdata import DATA_DIR
from services import amendments as svc
from services import chat as chat_service

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
HEADER = SAMPLE.splitlines()[0]
B = {"x-user": "Ravi", "x-role": "Buyer"}
B2 = {"x-user": "Kiran", "x-role": "Buyer"}
P = {"x-user": "Asha%20Rao", "x-role": "Procurement"}  # as the interface sends a name with a space
R = {"x-user": "Meera", "x-role": "Requester"}


@pytest.fixture
def ws(client):
    client.post("/api/process-batch", content=SAMPLE)
    return client.get("/api/workspace", headers=B).json()["requirements"]


def single_po(reqs, n=0):
    return [r for r in reqs if r["po"] and len(r["po"]["requirements"]) == 1][n]


# ---------------------------------------------------------------- workspace
def test_approve_then_override_and_override_then_approve_are_refused(client, ws):
    a, b = single_po(ws, 0), single_po(ws, 1)
    assert client.post(f"/api/requirements/{a['id']}/approve", json={"versions": {str(a["id"]): a["version"]}}, headers=B).status_code == 200
    for version in (a["version"], a["version"] + 1):
        r = client.post(f"/api/requirements/{a['id']}/override", json={"version": version, "route": "RFQ", "comment": "x"}, headers=B2)
        assert r.status_code == 409 and "already approved by Ravi" in r.json()["detail"]
    assert client.post(f"/api/requirements/{b['id']}/override", json={"version": b["version"], "route": "RFQ", "comment": "x"}, headers=B).status_code == 200
    r = client.post(f"/api/requirements/{b['id']}/approve", json={"versions": {str(b["id"]): b["version"] + 1}}, headers=B2)
    assert r.status_code == 409 and "already overridden by Ravi" in r.json()["detail"]


def test_the_same_consolidated_po_from_two_tabs_at_once_succeeds_once(client, ws):
    cons = next(r for r in ws if r["po"] and len(r["po"]["requirements"]) > 1)
    versions = {str(m["id"]): next(x["version"] for x in ws if x["id"] == m["id"]) for m in cons["po"]["requirements"]}
    codes = []
    tabs = [threading.Thread(target=lambda h=h: codes.append(
        client.post(f"/api/requirements/{cons['id']}/approve", json={"versions": versions}, headers=h).status_code)) for h in (B, B2)]
    [t.start() for t in tabs]
    [t.join() for t in tabs]
    assert sorted(codes) == [200, 409]


@pytest.mark.parametrize("body,status", [({"versions": "abc"}, 400), ({"versions": [1, 2]}, 400), ({"versions": {"x": 1}}, 400)])
def test_malformed_versions_are_a_plain_400_not_a_crash(client, ws, body, status):
    r = client.post(f"/api/requirements/{ws[0]['id']}/approve", json=body, headers=B)
    assert r.status_code == status and "Send versions as" in r.json()["detail"]


def test_a_malformed_override_version_is_a_plain_400(client, ws):
    r = client.post(f"/api/requirements/{ws[0]['id']}/override", json={"version": "abc", "route": "RFQ", "comment": "x"}, headers=B)
    assert r.status_code == 400 and "whole number" in r.json()["detail"]


# ---------------------------------------------------------------- policy versions
def approved_spot_change(client):
    d = client.post("/api/policies/drafts", json={"from_current": True}, headers=P).json()
    doc = d["document"]
    doc.update(effective_from="2026-11-01")
    doc["parameters"]["limits"]["spot_po"]["value"] = 150000
    client.put(f"/api/policies/drafts/{d['id']}", content=json.dumps(doc), headers=P)
    assert client.post(f"/api/policies/drafts/{d['id']}/approve", headers=P).status_code == 200
    return d["id"], doc


def test_an_approved_version_cannot_be_approved_again_edited_or_discarded(client):
    vid, doc = approved_spot_change(client)
    assert client.get(f"/api/policies/{vid}", headers=P).json()["approved_by"] == "Asha Rao"  # name decoded
    assert client.post(f"/api/policies/drafts/{vid}/approve", headers=P).status_code == 409
    assert client.put(f"/api/policies/drafts/{vid}", content=json.dumps(doc), headers=P).status_code == 409
    assert client.post(f"/api/policies/drafts/{vid}/discard", json={}, headers=P).status_code == 409


def test_old_exports_never_change_after_approving_or_withdrawing(client):
    run = client.post("/api/process-batch", content=SAMPLE).json()["run_id"]
    vid, _ = approved_spot_change(client)
    assert client.get(f"/api/runs/{run}/export.csv").text == GOLDEN
    assert client.post("/api/policies/1/withdraw", json={"comment": "test"}, headers=P).status_code == 200  # 5.0, used by the run
    assert client.get(f"/api/runs/{run}/export.csv").text == GOLDEN
    only = client.post(f"/api/policies/{vid}/withdraw", json={"comment": "test"}, headers=P)
    assert only.status_code == 409 and "only approved version" in only.json()["detail"]


def test_a_batch_processed_while_an_amendment_is_drafting_ignores_the_draft(client):
    with client.app.state.session_factory() as s:
        row = svc.start_draft(s, "Asha", object(), "Spot limit 1 rupee from 1 Nov 2026")
    assert client.get(f"/api/policies/{row.id}", headers=P).json()["drafting_status"] == "drafting"
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text == GOLDEN


@pytest.mark.parametrize("who", [R, B])
def test_only_procurement_can_draft_edit_preview_or_discard(client, who):
    d = client.post("/api/policies/drafts", json={"from_current": True}, headers=P).json()
    calls = [client.post("/api/policies/drafts", json={"from_current": True}, headers=who),
             client.put(f"/api/policies/drafts/{d['id']}", content=json.dumps(d["document"]), headers=who),
             client.post(f"/api/policies/drafts/{d['id']}/preview", headers=who),
             client.post(f"/api/policies/drafts/{d['id']}/discard", json={}, headers=who),
             client.post(f"/api/policies/drafts/{d['id']}/approve", headers=who),
             client.post("/api/policies/1/withdraw", json={"comment": "x"}, headers=who)]
    assert [c.status_code for c in calls] == [403] * 6


def test_the_ops_pages_also_need_procurement_for_policy_changes(client):
    r = client.post("/ops/amendments/new", data={"user": "Ravi", "role": "Buyer", "from_current": "true"})
    assert r.status_code == 403 and "Only the Procurement role" in r.text
    ok = client.post("/ops/amendments/new", data={"user": "Asha", "role": "Procurement", "from_current": "true"},
                     follow_redirects=False)
    assert ok.status_code == 303


# ---------------------------------------------------------------- every write endpoint as the wrong role
def test_a_requester_cannot_call_any_buyer_or_procurement_write(client, ws):
    rid = ws[0]["id"]
    for method, path, body in [("post", f"/api/requirements/{rid}/approve", {"versions": {}}),
                               ("post", f"/api/requirements/{rid}/override", {"version": 1, "route": "RFQ", "comment": "x"}),
                               ("post", "/api/contracts", {"form": {}, "source": "manual"}),
                               ("get", "/api/audit", None), ("get", "/api/workspace", None)]:
        r = getattr(client, method)(path, headers=R, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, path
    assert client.post("/api/contracts/read-pdf", files={"file": ("x.pdf", b"%PDF", "application/pdf")}, headers=R).status_code == 403


# ---------------------------------------------------------------- uploads
@pytest.mark.parametrize("send,message", [
    (lambda c: c.post("/api/process-batch", files={"file": ("e.csv", b"", "text/csv")}), "the file is empty"),
    (lambda c: c.post("/api/process-batch", content=HEADER + "\n"), "a header but no lines"),
    (lambda c: c.post("/api/process-batch", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nbinary", "image/png")}), "missing required column"),
    (lambda c: c.post("/api/process-batch", content=HEADER + '\nPR-X,1,2026-11-05 10:00,A,B,PUN1,ITM-1048,"Nitrile, unclosed,10,PAIR,,2026-11-20,Normal\n'),
     "line 2 is not valid CSV"),
])
def test_bad_files_are_refused_with_a_plain_reason(client, send, message):
    r = send(client)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_a_5000_line_batch_is_processed(client):
    lines = SAMPLE.splitlines()[1:]
    body = HEADER + "\n" + "\n".join(f"PR-B{n:05d},1,2026-11-{1 + n % 20:02d} {8 + n % 9:02d}:00,A,B,"
                                     f"{'PUN1' if n % 2 else 'CHK1'},{l.split(',')[6]},{l.split(',')[7]},{1 + n % 50},"
                                     f"{l.split(',')[9]},,2026-11-28,Normal" for n, l in enumerate((lines * 30)[:5000]))
    r = client.post("/api/process-batch", content=body)
    assert r.status_code == 200 and r.json()["lines"] == 5000


# ---------------------------------------------------------------- chat replies must be true
@pytest.mark.parametrize("message,expected", [
    ("need 100 kg aluminium plate 6061 10mm for Bhosari by 30 Nov", "goes to an RFQ with 3 suggested suppliers"),  # Blocked S004's contract item
    ("need 1 air compressor 30HP screw for Bhosari by 30 Nov", "is Capex, so it needs capex approval and goes to sourcing"),
])
def test_chat_replies_say_what_the_engine_decided(client, message, expected, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(chat_service, "now", lambda: datetime(2026, 11, 17, 10, 0, tzinfo=chat_service.IST))
    client.app.state.chat_llm_client = None
    conv = client.post("/api/chat/conversations", headers=R).json()["id"]
    client.post(f"/api/chat/conversations/{conv}/messages", json={"text": message}, headers=R)
    done = client.post(f"/api/chat/conversations/{conv}/messages", json={"event": {"type": "create"}}, headers=R).json()
    reply = done["messages"][-1]["text"]
    assert expected in reply and "S004" not in reply
    with client.app.state.session_factory() as s:
        run = s.execute(__import__("sqlalchemy").text("SELECT route, suggested_supplier_ids FROM decisions ORDER BY run_id DESC LIMIT 1")).one()
    assert run.route in ("RFQ", "CAPEX_SOURCING") and "S004" not in run.suggested_supplier_ids


def test_a_chat_new_item_reply_is_true(client, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(chat_service, "now", lambda: datetime(2026, 11, 17, 10, 0, tzinfo=chat_service.IST))
    client.app.state.chat_llm_client = None
    conv = client.post("/api/chat/conversations", headers=R).json()["id"]
    say = lambda body: client.post(f"/api/chat/conversations/{conv}/messages", json=body, headers=R).json()  # noqa: E731
    say({"text": "need 2 ultrasonic flaw detectors for Chakan by 30 Nov"})
    say({"text": "model UFD-9 portable"})
    say({"event": {"type": "new_item"}})
    say({"text": "Rs 250000"})
    say({"text": "nos"})
    reply = say({"event": {"type": "create"}})["messages"][-1]["text"]
    assert "is a new item, so it goes to sourcing" in reply


# ---------------------------------------------------------------- contracts
def test_bad_contracts_are_refused_and_the_golden_file_still_matches(client):
    form = {"supplier_id": "S001", "start_date": "2026-11-01", "end_date": "2027-03-31", "value_cap": "100000",
            "lines": [{"item_code": "ITM-1001", "rate": "6000"}]}
    dup = client.post("/api/contracts", json={"form": {**form, "contract_id": "RC-2025-011"}, "source": "manual"}, headers=B)
    backwards = client.post("/api/contracts", json={"form": {**form, "contract_id": "RC-2026-090", "end_date": "2026-10-01"},
                                                    "source": "manual"}, headers=B)
    blocked = client.post("/api/contracts", json={"form": {**form, "contract_id": "RC-2026-091", "supplier_id": "S004",
                                                           "lines": [{"item_code": "ITM-1006", "rate": "300"}]},
                                                  "source": "manual"}, headers=B)
    assert dup.status_code == 422 and "already exists" in dup.json()["detail"]
    assert backwards.status_code == 422 and "start date is after the end date" in backwards.json()["detail"]
    assert blocked.status_code == 201 and blocked.json()["warnings"]
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text == GOLDEN
