"""G2: run listings, the stored run's export, the preferred-supplier export and the policy list."""
import csv
import hashlib
import io
from pathlib import Path

import pytest

from db.models import Run
from db.session import make_session_factory
from kitdata import DATA_DIR

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")


def process(client, **headers):
    return client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv", **headers}).json()


def test_a_stored_runs_export_is_regenerated_byte_for_byte(client, db_engine):
    run_id = process(client)["run_id"]
    first = client.get(f"/api/runs/{run_id}/export.csv")
    second = client.get(f"/api/runs/{run_id}/export.csv")
    assert first.status_code == 200 and first.headers["content-type"].startswith("text/csv")
    assert first.content == second.content == GOLDEN.encode()
    with make_session_factory(db_engine)() as s:
        assert hashlib.sha256(first.content).hexdigest() == s.get(Run, run_id).export_sha256


def test_runs_can_be_listed_and_read(client):
    a = process(client, **{"x-user": "Asha"})["run_id"]
    b = process(client)["run_id"]
    listed = client.get("/api/runs").json()
    assert [r["run_id"] for r in listed] == [b, a]  # newest first
    one = client.get(f"/api/runs/{a}").json()
    assert (one["status"], one["started_by"], one["lines"], one["filename"]) == ("done", "Asha", 186, "batch.csv")
    assert one["summary_by_route"]["SPOT_PO"] == 72 and len(one["policy_version_ids"]) == 1
    assert client.get("/api/runs/999").status_code == 404
    assert client.get("/api/runs/999/export.csv").status_code == 404


def test_two_runs_do_not_affect_each_others_contract_ceilings(client):
    a, b = process(client), process(client)
    assert client.get(f"/api/runs/{a['run_id']}/export.csv").text == client.get(f"/api/runs/{b['run_id']}/export.csv").text
    contract_rows = [d for d in b["decisions"] if d["route"] == "CONTRACT_PO"]
    assert len(contract_rows) == 33  # the same contract POs as the first run: no ceiling was carried over


def preferred(client, as_of):
    r = client.get("/api/preferred-suppliers/export.csv", params={"as_of": as_of})
    return r, list(csv.DictReader(io.StringIO(r.text))) if r.status_code == 200 else []


def test_preferred_export_as_of_2026_11_01_matches_the_printed_rankings(client):
    r, rows = preferred(client, "2026-11-01")
    assert r.status_code == 200 and r.text.splitlines()[0] == "item_code,rank,supplier_id,reference_price"
    by_item = {}
    for row in rows:
        by_item.setdefault(row["item_code"], []).append(row["supplier_id"])
        assert row["rank"] == str(len(by_item[row["item_code"]]))
    assert by_item["ITM-1048"] == ["S029", "S030"]          # S031 Inactive: excluded
    assert by_item["ITM-1036"] == ["S023", "S022", "S024"]
    assert by_item["ITM-1016"] == ["S009", "S010"]
    assert all(len(v) <= 3 for v in by_item.values())
    assert "ITM-1006" not in by_item  # never bought, its only contract is Blocked S004's: no preferred supplier
    assert all(row["reference_price"] for row in rows)


def test_preferred_export_uses_only_the_preferred_list_not_category_top_ups(client):
    _, rows = preferred(client, "2026-11-04")
    assert [r["supplier_id"] for r in rows if r["item_code"] == "ITM-1034"] == ["S020"]  # Ex 11 tops up to 4 for an RFP


@pytest.mark.parametrize("as_of, fragment", [("01/11/2026", "as_of must be a date"), ("2026-03-31", "No preferred list")])
def test_preferred_export_rejects_a_bad_or_too_early_date(client, as_of, fragment):
    r, _ = preferred(client, as_of)
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_policies_are_listed_with_status_and_effective_date(client):
    (v5,) = client.get("/api/policies").json()
    assert (v5["version"], v5["status"], v5["effective_from"], v5["approved_by"]) == ("5.0", "approved", "2026-04-01", "seed")


# ---------------------------------------------------------------- G3: the operations page
def test_operations_page_offers_upload_and_preferred_download(client):
    r = client.get("/ops")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'enctype="multipart/form-data"' in r.text and "/api/preferred-suppliers/export.csv" in r.text
    assert "<script" not in r.text  # plain HTML, nothing that can fail to load


def test_operations_page_upload_shows_counts_and_the_download_link(client):
    r = client.post("/ops", files={"file": ("sample.csv", SAMPLE, "text/csv")}, data={"user": "Ojas"})
    assert r.status_code == 200 and "186 lines" in r.text and "<td>SPOT_PO</td><td>72</td>" in r.text
    run_id = client.get("/api/runs").json()[0]["run_id"]
    assert f"/api/runs/{run_id}/export.csv" in r.text
    assert client.get(f"/api/runs/{run_id}").json()["started_by"] == "Ojas"
    assert f"/api/runs/{run_id}/export.csv" in client.get("/ops").text  # listed under recent runs


def test_operations_page_shows_a_plain_error(client):
    r = client.post("/ops", files={"file": ("bad.csv", "pr_no,plant\nPR-1,PUN1\n", "text/csv")})
    assert r.status_code == 400 and "missing required column" in r.text
    assert client.post("/ops", data={"user": "x"}).status_code == 400
