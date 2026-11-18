"""B8 preferred suppliers (JSON) and B9 audit log."""
import csv
import io

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

BUYER = {"x-user": "Ravi", "x-role": "Buyer"}


def test_the_preferred_list_matches_the_export_and_explains_each_score(client):
    r = client.get("/api/preferred-suppliers?item_code=ITM-1048&as_of=2026-11-01", headers=BUYER).json()
    assert r["item"]["item_code"] == "ITM-1048" and r["policy_version"] == "5.0"
    exported = [m for m in r["preferred"] if m["exported"]]
    rows = [x for x in csv.DictReader(io.StringIO(client.get("/api/preferred-suppliers/export.csv?as_of=2026-11-01").text))
            if x["item_code"] == "ITM-1048"]
    assert [(m["supplier_id"], str(m["rank"])) for m in exported] == [(x["supplier_id"], x["rank"]) for x in rows]
    for m in r["preferred"]:
        assert set(m["parts"]) == {"po_count", "recency", "contract_held", "on_time", "quality"}
        assert abs(sum(float(v) for v in m["parts"].values()) - float(m["score"])) < 0.01
    assert all(t["status"] == "Active" and t["supplier_id"] not in {m["supplier_id"] for m in r["preferred"]} for t in r["topups"])


def test_bad_items_and_dates_get_plain_messages(client):
    assert "not in the item master" in client.get("/api/preferred-suppliers?item_code=ITM-9&as_of=2026-11-01", headers=BUYER).json()["detail"]
    assert "a date like" in client.get("/api/preferred-suppliers?item_code=ITM-1048&as_of=soon", headers=BUYER).json()["detail"]
    assert "No approved policy version" in client.get("/api/preferred-suppliers?item_code=ITM-1048&as_of=2020-01-01", headers=BUYER).json()["detail"]


def test_the_audit_log_is_newest_first_and_filters_by_who_and_action(client):
    client.post("/api/process-batch", content="pr_no,pr_line,created_at,requester,department,plant,item_code,description,"
                "quantity,uom,estimated_unit_price,need_by_date,urgency\nPR-1,1,2026-11-02 10:00,a,b,PUN1,ITM-1048,x,5,PAIR,,2026-11-20,Normal\n",
                headers={"x-user": "Ravi"})
    client.post("/api/policies/drafts", json={"from_current": True}, headers={"x-user": "Asha", "x-role": "Procurement"})
    log = client.get("/api/audit", headers=BUYER).json()
    assert [e["action"] for e in log["entries"]][:2] == ["policy.draft", "batch.process"]
    assert {"Ravi", "Asha"} <= set(log["actors"])
    assert [e["actor"] for e in client.get("/api/audit?actor=Ravi", headers=BUYER).json()["entries"]] == ["Ravi"]
    assert [e["action"] for e in client.get("/api/audit?action=policy", headers=BUYER).json()["entries"]] == ["policy.draft"]
    assert client.get("/api/audit", headers={"x-user": "M", "x-role": "Requester"}).status_code == 403
