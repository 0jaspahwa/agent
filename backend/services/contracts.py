"""B6: contracts. List the register and every contract added later; add one from its PDF or by hand.

Reading a PDF: the deterministic reader (loaders/contract_pdf.py) first. If it cannot read the file, it says why,
and the buyer can ask the AI to read the text instead (a draft clearly marked as needing checking) or fill the
form by hand. Either way the buyer confirms the form, and code validates it before saving: supplier and items
exist, dates in order, positive ceiling and rates, units match the item master, no duplicate contract number or
item. A saved contract has source pdf or manual and nothing consumed, and applies to every run made after it.
"""
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from db.models import AuditLog, Contract, ContractLine, Item, Supplier
from engine.lines import canon_uom
from llm.client import LLMError
from loaders.contract_pdf import ContractPdfError, read_contract_bytes
from services.snapshot import plain

PROMPT = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "contract_read.md"
CONTRACT_ID = re.compile(r"^RC-\d{4}-\d{3}$")


class ContractError(ValueError):
    def __init__(self, message, status=400, problems=None):
        super().__init__(message)
        self.status, self.problems = status, problems or []


def listing(session):
    suppliers = {s.supplier_id: s for s in session.scalars(select(Supplier))}
    lines = {}
    for ln in session.scalars(select(ContractLine).order_by(ContractLine.item_code)):
        lines.setdefault(ln.contract_id, []).append({"item_code": ln.item_code, "description": ln.description,
                                                     "uom": ln.uom, "rate": plain(ln.rate)})
    out = []
    for c in session.scalars(select(Contract).order_by(Contract.start_date, Contract.contract_id)):
        s = suppliers.get(c.supplier_id)
        out.append({"contract_id": c.contract_id, "supplier_id": c.supplier_id, "supplier_name": c.supplier_name,
                    "supplier_status": s.status if s else "unknown", "start_date": plain(c.start_date),
                    "end_date": plain(c.end_date), "value_cap": plain(c.value_cap),
                    "consumed_value": plain(c.consumed_value), "consumed_as_of": plain(c.consumed_as_of),
                    "source": c.source, "source_file": c.source_file, "added_by": c.added_by,
                    "lines": lines.get(c.contract_id, [])})
    return out


def _form(parsed, read_by):
    return {"contract_id": parsed.contract_id, "supplier_id": parsed.supplier_id, "supplier_name": parsed.supplier_name,
            "start_date": plain(parsed.start_date), "end_date": plain(parsed.end_date), "value_cap": plain(parsed.value_cap),
            "lines": [{"item_code": ln.item_code, "description": ln.description, "uom": ln.uom, "rate": plain(ln.rate)}
                      for ln in parsed.lines], "read_by": read_by, "needs_checking": read_by != "pdf reader"}


def read_pdf(data, name, client=None, use_llm=False):
    """{"form": ...} from the deterministic reader, or {"error": why, "llm_available": bool}; with use_llm, the
    AI's reading of the text (marked as needing checking)."""
    try:
        parsed, text = read_contract_bytes(data, name)
        return {"form": _form(parsed, "pdf reader")}
    except ContractPdfError as exc:
        error = str(exc)
    text = _text(data)
    if not use_llm:
        return {"error": error, "llm_available": client is not None and bool(text.strip())}
    if client is None or not text.strip():
        raise ContractError("The AI cannot read this file. Fill in the form by hand.", 503)
    try:
        system, user = PROMPT.read_text(encoding="utf-8").split("---USER---", 1)
        result = client.complete(system.strip(), user.strip().replace("{text}", text[:20000]))
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.text.strip())
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except LLMError as exc:
        raise ContractError(f"{exc} Fill in the form by hand instead.", 503) from exc
    except ValueError as exc:
        raise ContractError("The AI's reading could not be used. Fill in the form by hand.", 502) from exc
    form = {k: data.get(k) for k in ("contract_id", "supplier_id", "supplier_name", "start_date", "end_date", "value_cap")}
    form["lines"] = [{k: ln.get(k) for k in ("item_code", "description", "uom", "rate")}
                     for ln in (data.get("lines") or []) if isinstance(ln, dict)]
    form.update(read_by=f"AI ({result.provider}:{result.model})", needs_checking=True)
    return {"form": form, "reader_error": error}


def _text(data):
    import io
    from pypdf import PdfReader
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001 - an unreadable file simply has no text
        return ""


def _decimal(value):
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def validate(session, form):
    """(clean values, problems, warnings): each a plain sentence. Problems stop the save; warnings do not."""
    problems, warnings = [], []
    cid = str(form.get("contract_id") or "").strip().upper()
    if not CONTRACT_ID.match(cid):
        problems.append("The contract number must look like RC-2026-031.")
    elif session.get(Contract, cid):
        problems.append(f"Contract {cid} already exists.")
    supplier = session.get(Supplier, str(form.get("supplier_id") or "").strip().upper())
    if supplier is None:
        problems.append("Choose a supplier from the supplier master.")
    elif supplier.status != "Active":
        warnings.append(f"{supplier.supplier_id} {supplier.name} is {supplier.status}, so this contract will "
                        f"not be used for POs or valuation (4.1) until the supplier is Active again.")
    dates = {}
    for key, words in (("start_date", "start date"), ("end_date", "end date")):
        try:
            dates[key] = date.fromisoformat(str(form.get(key)))
        except ValueError:
            problems.append(f"The {words} is missing or not a date.")
    if len(dates) == 2 and dates["start_date"] > dates["end_date"]:
        problems.append("The start date is after the end date.")
    cap = _decimal(form.get("value_cap"))
    if cap is None or cap <= 0:
        problems.append("The ceiling must be a positive amount.")
    lines, seen = [], set()
    rows = form.get("lines") or []
    if not rows:
        problems.append("Add at least one item with its rate.")
    for n, row in enumerate(rows, start=1):
        code = str(row.get("item_code") or "").strip().upper()
        item = session.get(Item, code)
        rate = _decimal(row.get("rate"))
        if item is None:
            problems.append(f"Line {n}: {code or 'no item'} is not in the item master.")
            continue
        if code in seen:
            problems.append(f"Line {n}: {code} appears twice.")
        seen.add(code)
        if rate is None or rate <= 0:
            problems.append(f"Line {n}: the rate for {code} must be a positive amount.")
        uom = str(row.get("uom") or item.uom)
        if canon_uom(uom) != canon_uom(item.uom):
            problems.append(f"Line {n}: {code} is bought in {item.uom}, not {uom}.")
        lines.append({"item_code": code, "description": str(row.get("description") or item.description),
                      "uom": item.uom, "rate": rate})
    clean = {"contract_id": cid, "supplier": supplier, "cap": cap, "lines": lines, **dates}
    return clean, problems, warnings


def add(session, form, user, role, source, source_file=None):
    if source not in ("pdf", "manual"):
        raise ContractError("source must be pdf or manual.")
    clean, problems, warnings = validate(session, form)
    if problems:
        raise ContractError("The contract cannot be saved: " + " ".join(problems), 422, problems)
    s = clean["supplier"]
    session.add(Contract(contract_id=clean["contract_id"], supplier_id=s.supplier_id, supplier_name=s.name,
                         start_date=clean["start_date"], end_date=clean["end_date"], value_cap=clean["cap"],
                         consumed_value=Decimal("0"), consumed_as_of=None, source=source, source_file=source_file,
                         added_by=user))
    session.flush()
    for ln in clean["lines"]:
        session.add(ContractLine(contract_id=clean["contract_id"], **ln))
    session.add(AuditLog(actor=user, actor_role=role, action="contract.add", entity_type="contract",
                         entity_id=clean["contract_id"], details=plain({"source": source, "file": source_file,
                                                                        "read_by": form.get("read_by"),
                                                                        "lines": len(clean["lines"])})))
    session.commit()
    saved = next(c for c in listing(session) if c["contract_id"] == clean["contract_id"])
    return {**saved, "warnings": warnings}


def items(session):
    return [{"item_code": i.item_code, "description": i.description, "uom": i.uom, "category": i.category,
             "item_type": i.item_type, "standard_price": plain(i.standard_price)}
            for i in session.scalars(select(Item).order_by(Item.item_code))]
