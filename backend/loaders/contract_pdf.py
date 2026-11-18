"""Read a signed rate-contract PDF deterministically (no LLM): number, supplier, dates, ceiling, item lines.

pypdf keeps each Schedule A row on one text line ("1 ITM-1036 Pneumatic cylinder 50x100 NOS 3,537.76").
(The scrambled tables seen earlier came from pdftotext's layout mode, not from the PDFs.) Each row is
anchored on its item code and on the rate at the end of the line; the unit is the token before the rate
and the description is everything between. Every check below must pass, or ContractPdfError says what is
wrong and nothing is guessed: one contract number, one supplier, one validity period, one ceiling, rows
numbered 1..n, one parsed row for every item code in the schedule, unique codes, positive amounts.
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from engine.inputs import Contract, ContractLine

AMOUNT = r"\d[\d,]*(?:\.\d+)?"  # Indian (60,00,000) or Western (178,463.60) grouping
ROW = re.compile(rf"^(\d+)\s+(ITM-\d{{4}})\s+(.+?)\s+(\S+)\s+({AMOUNT})$")


class ContractPdfError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedContract:
    contract_id: str
    supplier_id: str
    supplier_name: str
    supplier_city: str
    start_date: date
    end_date: date
    value_cap: Decimal
    lines: tuple[ContractLine, ...]  # sorted by item_code, as in engine.inputs.Contract


def _amount(text):
    return Decimal(text.replace(",", ""))


def _one(pattern, flat, what, source):
    found = re.findall(pattern, flat)
    if len(found) != 1:
        raise ContractPdfError(f"{source}: expected exactly one {what}, found {len(found)}")
    return found[0]


def parse_contract_text(text, source="contract"):
    flat = " ".join(text.split())  # header sentences may wrap across lines
    contract_id = _one(r"Contract No\. (RC-\d{4}-\d{3})", flat, "contract number", source)
    name, city, supplier_id = _one(r"and (.+), ([A-Za-z .]+) \(Supplier ID (S\d{3})\)", flat, "supplier", source)
    start, end = _one(r"valid from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", flat, "validity period", source)
    cap = _one(rf"shall not exceed INR ({AMOUNT})", flat, "value ceiling", source)

    if "Schedule A" not in text:
        raise ContractPdfError(f"{source}: no Schedule A (items and rates)")
    schedule = text.split("Schedule A", 1)[1]
    codes_in_schedule = re.findall(r"ITM-\d{4}", schedule)
    rows = [m.groups() for line in schedule.splitlines() if (m := ROW.match(line.strip()))]
    if not rows:
        raise ContractPdfError(f"{source}: no item rows found in Schedule A")
    if [r[1] for r in rows] != codes_in_schedule:
        raise ContractPdfError(f"{source}: Schedule A names {len(codes_in_schedule)} item code(s) but only "
                               f"{len(rows)} row(s) could be read as '# code description unit rate'")
    if [int(r[0]) for r in rows] != list(range(1, len(rows) + 1)):
        raise ContractPdfError(f"{source}: Schedule A rows are not numbered 1..{len(rows)}")
    if len(set(codes_in_schedule)) != len(codes_in_schedule):
        raise ContractPdfError(f"{source}: an item code appears twice in Schedule A")

    lines = tuple(sorted((ContractLine(code, desc, uom, _amount(rate)) for _n, code, desc, uom, rate in rows),
                         key=lambda l: l.item_code))
    start_date, end_date, value_cap = date.fromisoformat(start), date.fromisoformat(end), _amount(cap)
    if end_date < start_date or value_cap <= 0 or any(l.rate <= 0 for l in lines):
        raise ContractPdfError(f"{source}: impossible values (dates out of order, or a non-positive amount)")
    return ParsedContract(contract_id, supplier_id, name, city, start_date, end_date, value_cap, lines)


def read_contract_bytes(data, name="upload.pdf"):
    """The same reader for an uploaded file (the contracts screen, B6)."""
    import io
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ContractPdfError(f"{name}: not a readable PDF ({exc})") from exc
    if not text.strip():
        raise ContractPdfError(f"{name}: the PDF has no text to read (a scan?)")
    return parse_contract_text(text, source=name), text


def read_contract_pdf(path):
    path = Path(path)
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ContractPdfError(f"{path.name}: not a readable PDF ({exc})") from exc
    parsed = parse_contract_text(text, source=path.name)
    if parsed.contract_id != path.stem:
        raise ContractPdfError(f"{path.name}: the document says {parsed.contract_id}, not {path.stem}")
    return parsed


def as_pdf_only_contract(parsed):
    """A contract known only from its signed PDF: binding from its start date, nothing consumed (4.2, 4.4)."""
    return Contract(parsed.contract_id, parsed.supplier_id, parsed.supplier_name, parsed.start_date,
                    parsed.end_date, parsed.value_cap, Decimal("0"), None, "pdf", parsed.lines)


def pdf_only_contracts(pdf_dir, register_ids):
    """Every PDF in pdf_dir whose contract is not in the register, as a PDF-only Contract. Any PDF that
    cannot be read raises ContractPdfError naming the file: a contract is never guessed or skipped."""
    found = []
    for path in sorted(Path(pdf_dir).glob("*.pdf")):
        if path.stem not in register_ids:
            found.append(as_pdf_only_contract(read_contract_pdf(path)))
    return found
