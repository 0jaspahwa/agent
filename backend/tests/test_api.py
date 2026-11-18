"""The API through FastAPI's test client, on a fresh database (SQLite, and Postgres when configured).

G4 coverage, here and in test_api_exports.py: every upload style; the sample batch through the API equals
the golden file (JSON decisions, ?format=csv, Accept: text/csv, and the stored run's export); a stored run's
export is byte-identical on a second download; the preferred export for 2026-11-01; the 400 for a missing
column; two runs of the same batch do not affect each other's contract ceilings."""
import csv
import io
from pathlib import Path

import pytest
from sqlalchemy import func, select

from db.models import AuditLog, Contract, Decision, PoLine, PurchaseOrder, Requirement, Run, SourcingRequest
from db.session import make_session_factory
from kitdata import DATA_DIR

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")


GOLDEN_ROWS = list(csv.DictReader(io.StringIO(GOLDEN)))


# ---------------------------------------------------------------- G1: every way of sending the file
@pytest.mark.parametrize("send", [
    lambda c: c.post("/api/process-batch", files={"file": ("sample.csv", SAMPLE, "text/csv")}),
    lambda c: c.post("/api/process-batch", files={"batch_upload": ("whatever.csv", SAMPLE.encode(), "application/octet-stream")}),
    lambda c: c.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv"}),
    lambda c: c.post("/api/process-batch", content=SAMPLE.encode(), headers={"content-type": "application/octet-stream"}),
    lambda c: c.post("/api/process-batch", content=SAMPLE),  # no content type at all
    lambda c: c.post("/api/process-batch", json={"csv": SAMPLE}),
    lambda c: c.post("/api/process-batch", data={"anything": SAMPLE}),  # CSV text in a plain form field
    lambda c: c.post("/api/process-batch", content=("﻿" + SAMPLE).encode(), headers={"content-type": "text/csv"}),
], ids=["multipart file", "multipart other name", "raw text/csv", "raw octet-stream", "raw no type", "json",
        "form field", "byte-order mark"])
def test_every_upload_style_gives_the_golden_decisions(client, send):
    r = send(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["lines"], body["requirements"], body["purchase_orders"]) == (186, 149, 82)
    assert body["summary_by_route"] == {"CAPEX_SOURCING": 10, "CONTRACT_PO": 33, "EMERGENCY_PO": 6,
                                        "NEW_ITEM_SOURCING": 2, "NOT_PROCESSED": 2, "RFP": 8, "RFQ": 53, "SPOT_PO": 72}
    assert body["decisions"] == GOLDEN_ROWS  # one object per PR line, the export's fields and values


@pytest.mark.parametrize("ask", [{"params": {"format": "csv"}}, {"headers": {"accept": "text/csv"}}])
def test_csv_can_be_asked_for_directly(client, ask):
    r = client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv", **ask.get("headers", {})},
                    params=ask.get("params"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text == GOLDEN and r.headers["x-run-id"]


@pytest.mark.parametrize("body, fragment", [
    ({"content": "pr_no,pr_line,plant\nPR-1,1,PUN1\n", "headers": {"content-type": "text/csv"}}, "created_at"),
    ({"content": "", "headers": {"content-type": "text/csv"}}, "no CSV"),
    ({"json": {"file": "x"}}, '"csv" field'),
    ({"content": "{not json", "headers": {"content-type": "application/json"}}, "JSON"),
    ({"files": {}, "data": {"note": "hello"}}, "no file"),
])
def test_bad_requests_get_a_400_with_a_plain_message(client, body, fragment):
    r = client.post("/api/process-batch", **body)
    assert r.status_code == 400 and fragment in r.json()["detail"], r.text


def test_missing_column_names_the_column(client):
    without = "\n".join(",".join(c for i, c in enumerate(line.split(",")) if i != 11) for line in SAMPLE.splitlines())
    r = client.post("/api/process-batch", content=without, headers={"content-type": "text/csv"})
    assert r.status_code == 400 and "need_by_date" in r.json()["detail"]


def test_a_run_is_stored_as_designed(client, db_engine):
    run_id = client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv", "x-user": "Asha"}).json()["run_id"]
    with make_session_factory(db_engine)() as s:
        run = s.get(Run, run_id)
        assert (run.status, run.kind, run.started_by, len(run.policy_version_ids)) == ("done", "batch", "Asha", 1)
        assert len(run.inputs["lines"]) == 186 and len(run.inputs["po_history"]) == 468
        assert run.inputs["contract_baseline"]["RC-2026-002"] == "1162000.00"
        counts = {m.__tablename__: s.scalar(select(func.count()).select_from(m).where(m.run_id == run_id))
                  for m in (Decision, Requirement, PurchaseOrder, SourcingRequest)}
        assert counts == {"decisions": 186, "requirements": 149, "purchase_orders": 82, "sourcing_requests": 55}
        po_requirements = s.scalar(select(func.count()).select_from(Requirement).where(
            Requirement.run_id == run_id, Requirement.decision == "PO"))
        assert po_requirements + counts["sourcing_requests"] == 149  # every requirement is one or the other
        assert s.scalar(select(func.count()).select_from(PoLine)) == po_requirements  # one PO line per requirement
        assert s.scalars(select(AuditLog.action)).all() == ["batch.process"]


def test_processing_the_same_file_again_gives_a_new_run_with_identical_decisions(client, db_engine):
    first = client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv"}).json()
    second = client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv"}).json()
    assert second["run_id"] != first["run_id"]
    assert second["decisions"] == first["decisions"]  # the second run did not see the first run's ceilings
    with make_session_factory(db_engine)() as s:
        assert s.get(Contract, "RC-2026-013").consumed_value == 250000  # runs never change the register
        a, b = (s.get(Run, x["run_id"]) for x in (first, second))
        assert a.inputs_sha256 == b.inputs_sha256 and a.export_sha256 == b.export_sha256
        assert a.inputs["contract_baseline"] == b.inputs["contract_baseline"]


def test_the_sample_batch_is_processed_well_within_a_request_timeout(client):
    r = client.post("/api/process-batch", content=SAMPLE, headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["processing_seconds"] < 10  # about 1.5 s on a laptop


# ---------------------------------------------------------------- H7: a named policy version
@pytest.mark.parametrize("send", [
    lambda c: c.post("/api/process-batch?policy_version=5.0&format=csv", content=SAMPLE),
    lambda c: c.post("/api/process-batch?format=csv", files={"file": ("s.csv", SAMPLE)}, data={"policy_version": "5.0"}),
    lambda c: c.post("/api/process-batch?format=csv", content=SAMPLE, headers={"x-policy-version": "5.0"}),
    lambda c: c.post("/api/process-batch?format=csv", json={"csv": SAMPLE, "policy_version": "5.0"}),
], ids=["query", "form field", "header", "json"])
def test_a_named_version_can_be_sent_every_way(client, send):
    response = send(client)
    assert response.status_code == 200, response.text
    assert response.headers["x-policy-mode"] == "named_version:5.0" and response.text == GOLDEN
    run = client.get(f"/api/runs/{response.headers['x-run-id']}").json()
    assert run["policy_mode"]["version"] == "5.0"


def test_an_unknown_version_is_a_plain_400(client):
    response = client.post("/api/process-batch?policy_version=7.3", content=SAMPLE)
    assert response.status_code == 400 and "no approved policy version '7.3'" in response.json()["detail"]
