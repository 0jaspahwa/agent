"""B4: the buyer workspace through the API, on the sample batch."""
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from db.models import BuyerAction, Contract, PoHistory, PoLine, PurchaseOrder, Requirement, SourcingRequest, Supplier
from kitdata import DATA_DIR
from services import workspace as ws

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
BUYER = {"x-user": "Ravi", "x-role": "Buyer"}
OTHER = {"x-user": "Kiran", "x-role": "Procurement"}


@pytest.fixture
def run(client):
    client.post("/api/process-batch", content=SAMPLE)
    return client.get("/api/workspace", headers=BUYER).json()


def pick(view, test):
    return next(r for r in view["requirements"] if test(r))


def versions(*reqs):
    return {str(r["id"]): r["version"] for r in reqs}


def test_an_empty_database_shows_no_run(client):
    assert client.get("/api/workspace", headers=BUYER).json()["requirements"] == []
    assert client.get("/api/workspace/runs", headers=BUYER).json() == []


def test_every_requirement_carries_what_a_buyer_needs(run):
    reqs = run["requirements"]
    assert run["run"]["kind"] == "batch" and run["run"]["open"] == len(reqs) and run["run"]["label"].startswith("Batch run")
    assert Counter(r["route"] for r in reqs)["CONTRACT_PO"] > 0 and all(r["status"] == "open" for r in reqs)
    contract = pick(run, lambda r: r["route"] == "CONTRACT_PO")
    assert contract["contract_id"] and contract["supplier"]["name"] and contract["unit_price"]
    assert contract["po"]["po_number"].startswith("PO-") and contract["why"]["clause"] == "5.2"
    assert contract["why"]["price_source_words"] and contract["policy_version"] == "5.0"
    rfq = pick(run, lambda r: r["route"] == "RFQ")
    assert rfq["suggestions"] and all(s["status"] == "Active" for s in rfq["suggestions"])
    assert {s["source"] for s in rfq["suggestions"]} <= {"preferred list", "category top-up (6.4)"}
    ranked = pick(run, lambda r: len(r["preferred"]) >= 2)
    assert set(ranked["preferred"][0]["parts"]) == {"po_count", "recency", "contract_held", "on_time", "quality"}
    assert len(run["not_processed"]) == 2 and all(n["reason"] for n in run["not_processed"])
    flagged = [r for r in run["requirements"] if r["flags"]]
    assert flagged and all(f["code"].startswith("F") for r in flagged for f in r["flags"])


def test_approving_a_sourcing_requirement_issues_it_and_cannot_be_repeated(client, run):
    rfq = pick(run, lambda r: r["route"] == "RFQ" and not r["po"])
    r = client.post(f"/api/requirements/{rfq['id']}/approve", json={"versions": versions(rfq)}, headers=BUYER)
    assert r.status_code == 200, r.text
    assert r.json()["record"] == {"kind": "sourcing", "route": "RFQ", "group_id": rfq["group_id"], "status": "issued",
                                  "suggested_supplier_ids": [s["supplier_id"] for s in rfq["suggestions"]]}
    after = r.json()["requirement"]
    assert after["status"] == "approved" and after["version"] == rfq["version"] + 1
    assert after["history"][0]["action"] == "approve" and after["history"][0]["by"] == "Ravi"
    again = client.post(f"/api/requirements/{rfq['id']}/approve", json={"versions": versions(rfq)}, headers=OTHER)
    assert again.status_code == 409 and "already approved by Ravi" in again.json()["detail"]


def test_a_consolidated_po_is_approved_with_all_its_requirements(client, run, db_engine):
    consolidated = pick(run, lambda r: r["po"] and len(r["po"]["requirements"]) > 1)
    members = [pick(run, lambda r, m=m: r["id"] == m["id"]) for m in consolidated["po"]["requirements"]]
    partial = client.post(f"/api/requirements/{consolidated['id']}/approve", json={"versions": versions(consolidated)},
                          headers=BUYER)
    assert partial.status_code == 409 and "approves all its requirements together" in partial.json()["detail"]
    ok = client.post(f"/api/requirements/{consolidated['id']}/approve", json={"versions": versions(*members)}, headers=BUYER)
    record = ok.json()["record"]
    assert record["kind"] == "po" and record["po_number"] == consolidated["po"]["po_number"] and record["status"] == "approved"
    assert len(record["lines"]) == len(members) and all(x["approved"] for x in record["lines"])
    view = client.get("/api/workspace", headers=BUYER).json()
    assert all(pick(view, lambda r, m=m: r["id"] == m["id"])["status"] == "approved" for m in members)


def test_two_buyers_acting_at_once_exactly_one_succeeds(client, run, db_engine):
    from db.session import make_session_factory
    spot = pick(run, lambda r: r["route"] == "SPOT_PO" and len(r["po"]["requirements"]) == 1)
    factory = make_session_factory(db_engine)
    with factory() as a, factory() as b:
        a.get(Requirement, spot["id"]), b.get(Requirement, spot["id"])  # both read version 1
        ws.approve(a, spot["id"], versions(spot), "Ravi", "Buyer")
        with pytest.raises(ws.WorkspaceError) as exc:
            ws.override(b, spot["id"], spot["version"], "Kiran", "Procurement", "RFQ", "cheaper elsewhere")
    assert exc.value.status == 409
    with factory() as s:
        assert [a.action for a in s.scalars(select(BuyerAction).where(BuyerAction.requirement_id == spot["id"]))] == ["approve"]


def test_an_override_needs_a_comment_and_an_allowed_supplier(client, run, db_engine):
    spot = pick(run, lambda r: r["route"] == "SPOT_PO" and len(r["po"]["requirements"]) == 1)
    url, base = f"/api/requirements/{spot['id']}/override", {"version": spot["version"], "route": "SPOT_PO", "unit_price": 10}
    assert client.post(url, json={**base, "supplier_id": "S001", "comment": " "}, headers=BUYER).status_code == 422
    with db_engine.connect() as c:
        blocked = c.execute(select(Supplier.supplier_id).where(Supplier.status == "Blocked")).scalars().first()
    refused = client.post(url, json={**base, "supplier_id": blocked, "comment": "they are cheaper"}, headers=BUYER)
    assert refused.status_code == 422 and "is Blocked and cannot receive a PO" in refused.json()["detail"]
    done = client.post(url, json={**base, "supplier_id": "S001", "comment": "S001 has stock today"}, headers=BUYER).json()
    req = done["requirement"]
    assert req["status"] == "overridden" and req["route"] == "SPOT_PO" and req["supplier"]["supplier_id"] == spot["supplier"]["supplier_id"]
    assert req["history"][0] | {"at": None} == {"action": "override", "by": "Ravi", "role": "Buyer", "at": None,
                                                "comment": "S001 has stock today", "new_route": "SPOT_PO",
                                                "new_supplier_id": "S001", "new_unit_price": "10.00",
                                                "new_suggested_supplier_ids": None}
    assert client.post(f"/api/requirements/{spot['id']}/approve", json={"versions": {str(spot["id"]): req["version"]}},
                       headers=BUYER).status_code == 409


def test_a_requester_cannot_use_the_workspace(client, run):
    assert client.get("/api/workspace", headers={"x-user": "Meera", "x-role": "Requester"}).status_code == 403
    rid = run["requirements"][0]["id"]
    r = client.post(f"/api/requirements/{rid}/approve", json={"versions": {}}, headers={"x-user": "Meera", "x-role": "Requester"})
    assert r.status_code == 403 and "Buyer or Procurement" in r.json()["detail"]


def test_actions_change_neither_ceilings_nor_po_history_and_reprocessing_is_unchanged(client, run, db_engine):
    with db_engine.connect() as c:
        before = (c.execute(select(func.sum(Contract.consumed_value))).scalar(), c.execute(select(func.count()).select_from(PoHistory)).scalar())
    for r in run["requirements"][:20]:
        if not r["po"] or len(r["po"]["requirements"]) == 1:
            client.post(f"/api/requirements/{r['id']}/approve", json={"versions": versions(r)}, headers=BUYER)
    with db_engine.connect() as c:
        after = (c.execute(select(func.sum(Contract.consumed_value))).scalar(), c.execute(select(func.count()).select_from(PoHistory)).scalar())
        assert c.execute(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "approved")).scalar() > 0
    assert before == after  # D14
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text == GOLDEN


def test_open_chat_requirements_view(client):
    view = client.get("/api/workspace?kind=chat", headers=BUYER).json()
    assert view["run"] is None and view["requirements"] == []
