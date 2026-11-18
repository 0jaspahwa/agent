"""B4: the deterministic contract PDF reader matches the register exactly, and refuses to guess."""
import csv
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from db.models import Contract as ContractRow
from db.models import ContractLine as ContractLineRow
from db.seed import seed
from db.session import make_session_factory
from engine.inputs import ContractLine
from kitdata import DATA_DIR
from loaders import kit
from loaders.contract_pdf import ContractPdfError, parse_contract_text, read_contract_pdf

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

PDF_DIR = DATA_DIR / "contracts" / "pdf"
REGISTER = {r["contract_id"]: r for r in csv.DictReader(open(DATA_DIR / "contracts/contract_register.csv", encoding="utf-8"))}
LINES = {}
for _r in csv.DictReader(open(DATA_DIR / "contracts/contract_lines.csv", encoding="utf-8")):
    LINES.setdefault(_r["contract_id"], []).append(_r)
SUPPLIERS = {r["supplier_id"]: r for r in csv.DictReader(open(DATA_DIR / "master_data/supplier_master.csv", encoding="utf-8"))}


def test_every_kit_pdf_is_either_in_the_register_or_one_of_the_two_pdf_only_contracts():
    assert sorted(p.stem for p in PDF_DIR.glob("*.pdf")) == sorted([*REGISTER, "RC-2026-031", "RC-2026-033"])


@pytest.mark.parametrize("contract_id", sorted(REGISTER))
def test_pdf_equals_the_register_exactly(contract_id):
    parsed = read_contract_pdf(PDF_DIR / f"{contract_id}.pdf")
    reg = REGISTER[contract_id]
    assert (parsed.contract_id, parsed.supplier_id, parsed.supplier_name, parsed.start_date, parsed.end_date,
            parsed.value_cap) == (reg["contract_id"], reg["supplier_id"], reg["supplier_name"],
                                  date.fromisoformat(reg["start_date"]), date.fromisoformat(reg["end_date"]),
                                  Decimal(reg["value_cap"]))
    expected = tuple(sorted((ContractLine(r["item_code"], r["description"], r["uom"], Decimal(r["rate"]))
                             for r in LINES[contract_id]), key=lambda l: l.item_code))
    assert parsed.lines == expected
    assert parsed.supplier_city == SUPPLIERS[parsed.supplier_id]["city"]  # cross-check with the supplier master


def test_pdf_only_contracts_load_with_source_pdf_and_nothing_consumed():
    contracts = {c.contract_id: c for c in kit.load_master().contracts}
    c031, c033 = contracts["RC-2026-031"], contracts["RC-2026-033"]
    assert (c031.source, c031.consumed_value, c031.consumed_as_of) == ("pdf", Decimal("0"), None)
    assert (c031.supplier_id, c031.start_date, c031.end_date, c031.value_cap) == (
        "S021", date(2026, 11, 15), date(2027, 11, 14), Decimal("2000000"))
    assert [(l.item_code, l.rate) for l in c031.lines] == [
        ("ITM-1036", Decimal("3537.76")), ("ITM-1037", Decimal("2439.01")), ("ITM-1039", Decimal("2746.87"))]
    assert (c033.source, c033.consumed_value, c033.supplier_id, c033.start_date) == (
        "pdf", Decimal("0"), "S035", date(2026, 11, 20))
    assert {c.source for c in contracts.values()} == {"register", "pdf"}
    assert sum(c.source == "pdf" for c in contracts.values()) == 2


def test_seed_stores_pdf_only_contracts_with_their_file(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        row = s.get(ContractRow, "RC-2026-033")
        assert (row.source, row.consumed_value, row.consumed_as_of, row.source_file) == (
            "pdf", Decimal("0"), None, "data/contracts/pdf/RC-2026-033.pdf")
        assert len(s.scalars(select(ContractLineRow).where(ContractLineRow.contract_id == "RC-2026-033")).all()) == 2


GOOD = (PDF_DIR / "RC-2026-031.pdf")


def _good_text():
    from pypdf import PdfReader
    return "\n".join(p.extract_text() for p in PdfReader(GOOD).pages)


@pytest.mark.parametrize("break_it, message", [
    (lambda t: t.replace("Contract No. RC-2026-031", "Contract RC-2026-031"), "contract number"),
    (lambda t: t.replace("(Supplier ID", "(Vendor ID"), "supplier"),
    (lambda t: t.replace("valid from", "valid since"), "validity period"),
    (lambda t: t.replace("shall not exceed INR", "is capped at"), "value ceiling"),
    (lambda t: t.replace("NOS 2,439.01", "NOS"), "could be read as"),            # a row lost its rate
    (lambda t: t.replace("3 ITM-1039", "4 ITM-1039"), "not numbered"),
    (lambda t: t.replace("ITM-1039", "ITM-1036"), "appears twice"),
    (lambda t: t.replace("Schedule A", "Annexure"), "Schedule A"),
    (lambda t: t.replace("to 2027-11-14", "to 2025-11-14"), "impossible values"),
])
def test_broken_contract_text_is_refused_with_a_clear_reason(break_it, message):
    assert parse_contract_text(_good_text()).contract_id == "RC-2026-031"  # the unbroken text parses
    with pytest.raises(ContractPdfError, match=message):
        parse_contract_text(break_it(_good_text()), source="RC-2026-031.pdf")


def test_a_file_that_is_not_a_pdf_is_refused(tmp_path):
    fake = tmp_path / "RC-2026-099.pdf"
    fake.write_bytes(b"this is not a pdf")
    with pytest.raises(ContractPdfError, match="not a readable PDF"):
        read_contract_pdf(fake)


def test_a_pdf_whose_number_differs_from_its_file_name_is_refused(tmp_path):
    renamed = tmp_path / "RC-2026-099.pdf"
    renamed.write_bytes(GOOD.read_bytes())
    with pytest.raises(ContractPdfError, match="says RC-2026-031"):
        read_contract_pdf(renamed)
