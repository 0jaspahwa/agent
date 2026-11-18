"""B6: contracts through the API: list, read a PDF, validate, save; a re-added PDF-only contract restores the
golden decisions."""
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from db.models import Contract, ContractLine
from kitdata import DATA_DIR
from llm.client import LLMClient

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

BUYER = {"x-user": "Ravi", "x-role": "Buyer"}
SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
PDF = DATA_DIR / "contracts" / "pdf" / "RC-2026-031.pdf"


def form(**changes):
    base = {"contract_id": "RC-2026-099", "supplier_id": "S001", "start_date": "2026-11-01", "end_date": "2027-03-31",
            "value_cap": "500000", "lines": [{"item_code": "ITM-1001", "rate": "6000"}]}
    return {**base, **changes}


def test_the_list_shows_every_contract_with_its_source_and_consumed_value(client):
    rows = client.get("/api/contracts", headers=BUYER).json()
    assert len(rows) == 12 and {r["source"] for r in rows} == {"register", "pdf"}
    pdf_only = {r["contract_id"]: r for r in rows if r["source"] == "pdf"}
    assert set(pdf_only) == {"RC-2026-031", "RC-2026-033"} and all(r["consumed_value"] == "0.00" for r in pdf_only.values())
    assert all(r["lines"] and r["supplier_status"] for r in rows)


def test_a_pdf_only_contract_removed_and_added_back_through_the_screen_restores_the_golden_decisions(client, db_engine):
    with db_engine.begin() as c:
        c.execute(delete(ContractLine).where(ContractLine.contract_id == "RC-2026-031"))
        c.execute(delete(Contract).where(Contract.contract_id == "RC-2026-031"))
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text != GOLDEN
    read = client.post("/api/contracts/read-pdf", files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
                       headers=BUYER).json()
    f = read["form"]
    assert f["contract_id"] == "RC-2026-031" and f["read_by"] == "pdf reader" and not f["needs_checking"]
    saved = client.post("/api/contracts", json={"form": f, "source": "pdf", "source_file": PDF.name}, headers=BUYER)
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert (body["source"], body["consumed_value"], body["added_by"], body["warnings"]) == ("pdf", "0.00", "Ravi", [])
    assert client.post("/api/process-batch?format=csv", content=SAMPLE).text == GOLDEN


@pytest.mark.parametrize("changes,problem", [
    ({"contract_id": "RC-2026-031"}, "Contract RC-2026-031 already exists."),
    ({"contract_id": "contract 9"}, "must look like RC-2026-031"),
    ({"supplier_id": "S999"}, "Choose a supplier from the supplier master."),
    ({"start_date": "2027-04-01"}, "The start date is after the end date."),
    ({"end_date": "soon"}, "The end date is missing or not a date."),
    ({"value_cap": "0"}, "The ceiling must be a positive amount."),
    ({"lines": []}, "Add at least one item with its rate."),
    ({"lines": [{"item_code": "ITM-9999", "rate": "5"}]}, "ITM-9999 is not in the item master."),
    ({"lines": [{"item_code": "ITM-1001", "rate": "-5"}]}, "the rate for ITM-1001 must be a positive amount"),
    ({"lines": [{"item_code": "ITM-1001", "rate": "5", "uom": "KG"}]}, "ITM-1001 is bought in NOS, not KG."),
    ({"lines": [{"item_code": "ITM-1001", "rate": "5"}, {"item_code": "ITM-1001", "rate": "6"}]}, "ITM-1001 appears twice."),
])
def test_every_check_gives_a_plain_reason(client, changes, problem):
    r = client.post("/api/contracts", json={"form": form(**changes), "source": "manual"}, headers=BUYER)
    assert r.status_code == 422 and any(problem in p for p in r.json()["problems"]), r.json()


def test_a_manual_contract_is_saved_with_nothing_consumed(client, db_engine):
    r = client.post("/api/contracts", json={"form": form(), "source": "manual"}, headers=BUYER)
    assert r.status_code == 201 and r.json()["source"] == "manual" and r.json()["consumed_value"] == "0.00"
    with db_engine.connect() as c:
        assert c.execute(select(Contract.consumed_as_of).where(Contract.contract_id == "RC-2026-099")).scalar() is None


def test_a_blocked_suppliers_contract_is_saved_with_a_warning(client, db_engine):
    r = client.post("/api/contracts", json={"form": form(supplier_id="S004"), "source": "manual"}, headers=BUYER)
    assert r.status_code == 201 and "will not be used for POs" in r.json()["warnings"][0]


def test_an_unreadable_file_says_why_and_the_ai_reading_is_marked_for_checking(client):
    junk = client.post("/api/contracts/read-pdf", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}, headers=BUYER)
    assert "not a readable PDF" in junk.json()["error"] and junk.json()["llm_available"] is False

    from amendments.simple_pdf import text_pdf
    odd = text_pdf(["Rate agreement RC-2026-077 with Bhosari Steel Traders (S001)", "valid 1 Dec 2026 to 31 Mar 2027",
                    "ceiling Rs 2,00,000; ITM-1001 MS sheet 2mm at Rs 6,100 per NOS"])
    reply = {"contract_id": "RC-2026-077", "supplier_id": "S001", "supplier_name": "Bhosari Steel Traders",
             "start_date": "2026-12-01", "end_date": "2027-03-31", "value_cap": 200000,
             "lines": [{"item_code": "ITM-1001", "description": "MS sheet 2mm", "uom": "NOS", "rate": 6100}]}
    client.app.state.contract_llm_client = LLMClient([("fake", "m")], {"fake": lambda s, u, m: json.dumps(reply)}, retries=0)
    first = client.post("/api/contracts/read-pdf", files={"file": ("odd.pdf", odd, "application/pdf")}, headers=BUYER).json()
    assert first["llm_available"] is True and "expected exactly one contract number" in first["error"]
    ai = client.post("/api/contracts/read-pdf?llm=1", files={"file": ("odd.pdf", odd, "application/pdf")}, headers=BUYER).json()
    assert ai["form"]["needs_checking"] and ai["form"]["read_by"] == "AI (fake:m)" and ai["form"]["value_cap"] == 200000


def test_only_buyers_and_procurement_manage_contracts(client):
    requester = {"x-user": "Meera", "x-role": "Requester"}
    assert client.get("/api/contracts", headers=requester).status_code == 403
    assert client.post("/api/contracts", json={"form": form(), "source": "manual"}, headers=requester).status_code == 403
