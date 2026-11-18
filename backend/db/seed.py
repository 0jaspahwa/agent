"""Seed the database with policy v5.0 and, when the task kit is present, the kit's master data and contracts.

The kit is not in the repo (the task rules). It is read from DATA_DIR (default data/) when that folder holds it,
or uploaded through the app (POST /api/admin/load-kit, services/kit.py), which calls seed_kit() on a temporary
folder in the kit's layout. Both paths run the same code.

Safe to run any number of times: a row whose key already exists is left untouched (INSERT ... ON CONFLICT
DO NOTHING), so re-seeding never duplicates or overwrites. This file reads the CSVs itself, independently
of loaders/kit.py, so the B3 test that compares the kit loader with the database loader checks two paths.

    python -m db.seed          (from backend/, with DATABASE_URL set)
"""
import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.models import Contract, ContractLine, Item, Plant, PoHistory, PolicyVersion, Supplier
from db.session import init_db, make_engine
from engine.policy import POLICY_DIR
from kitdata import DATA_DIR, REGISTER_AS_OF, kit_present
from loaders.contract_pdf import pdf_only_contracts

POLICY_FILE = POLICY_DIR / "v5.0.json"
KIT_TABLES = (Item, Supplier, Plant, PoHistory, Contract, ContractLine)  # foreign-key order


class KitDataError(ValueError):
    """A kit file that cannot be read; the message names the file and says what is wrong."""


def _csv(data_dir, rel):
    with open(Path(data_dir) / rel, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _rows(data_dir, rel, convert):
    """convert() applied to every row of one kit file, with a plain error naming the file if it does not fit."""
    try:
        return [convert(r) for r in _csv(data_dir, rel)]
    except KeyError as exc:
        raise KitDataError(f"{rel}: the column {exc} is missing.") from exc
    except (ValueError, InvalidOperation, AttributeError, TypeError) as exc:
        raise KitDataError(f"{rel}: a value could not be read ({exc}).") from exc


def kit_rows(data_dir=DATA_DIR):
    """{model: [row dicts]} for every master-data table, straight from the kit files."""
    return {
        Item: _rows(data_dir, "master_data/item_master.csv", lambda r: dict(r, standard_price=Decimal(r["standard_price"]))),
        Supplier: _rows(data_dir, "master_data/supplier_master.csv", lambda r: dict(
            r, categories=r["categories"].split(";"), on_time_pct=Decimal(r["on_time_pct"]),
            quality_rating=Decimal(r["quality_rating"]))),
        Plant: _rows(data_dir, "master_data/plants.csv", lambda r: {"plant": r["plant"], "name": r["name"]}),
        PoHistory: _rows(data_dir, "master_data/po_history.csv", lambda r: dict(
            r, po_date=date.fromisoformat(r["po_date"]), quantity=Decimal(r["quantity"]),
            unit_price=Decimal(r["unit_price"]), delivered_on_time=r["delivered_on_time"] == "True")),
        Contract: _rows(data_dir, "contracts/contract_register.csv", lambda r: dict(
            r, start_date=date.fromisoformat(r["start_date"]), end_date=date.fromisoformat(r["end_date"]),
            value_cap=Decimal(r["value_cap"]), consumed_value=Decimal(r["consumed_value"]),
            consumed_as_of=REGISTER_AS_OF, source="register", source_file=None, added_by="seed")),
        ContractLine: _rows(data_dir, "contracts/contract_lines.csv", lambda r: dict(r, rate=Decimal(r["rate"]))),
    }


def _insert_new(conn, model, rows):
    insert = pg_insert if conn.dialect.name == "postgresql" else sqlite_insert
    if rows:
        conn.execute(insert(model).values(rows).on_conflict_do_nothing())


def _count(conn, model):
    return conn.execute(select(func.count()).select_from(model)).scalar_one()


def pdf_only_rows(register_ids, data_dir=DATA_DIR):
    """Contracts signed after the register update: read from their PDFs, nothing consumed (4.2, 4.4)."""
    headers, lines = [], []
    for c in pdf_only_contracts(Path(data_dir) / "contracts" / "pdf", register_ids):
        headers.append(dict(contract_id=c.contract_id, supplier_id=c.supplier_id, supplier_name=c.supplier_name,
                            start_date=c.start_date, end_date=c.end_date, value_cap=c.value_cap,
                            consumed_value=c.consumed_value, consumed_as_of=None, source="pdf",
                            source_file=f"data/contracts/pdf/{c.contract_id}.pdf", added_by="seed"))
        lines += [dict(contract_id=c.contract_id, item_code=l.item_code, description=l.description, uom=l.uom,
                       rate=l.rate) for l in c.lines]
    return headers, lines


def seed_kit(conn, data_dir):
    """Insert the kit in data_dir where missing, inside the caller's transaction.
    Returns {table: {"in_kit": rows in the files, "added": rows inserted now}}."""
    rows = kit_rows(data_dir)
    headers, lines = pdf_only_rows({r["contract_id"] for r in rows[Contract]}, data_dir)
    rows[Contract] += headers
    rows[ContractLine] += lines
    summary = {}
    for model in KIT_TABLES:
        before = _count(conn, model)
        _insert_new(conn, model, rows[model])
        summary[model.__tablename__] = {"in_kit": len(rows[model]), "added": _count(conn, model) - before}
    return summary


def seed_policy(conn):
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    _insert_new(conn, PolicyVersion, [{
        "policy_id": policy["policy_id"], "version": policy["version"],
        "effective_from": date.fromisoformat(policy["effective_from"]), "status": "approved",
        "document": policy, "source_document_name": policy["source_document"], "source_document_text": None,
        "change_summary": policy["change_summary"], "drafted_by": "seed", "impact_summary": None,
        "created_by": "seed", "approved_by": "seed", "approved_at": datetime.now(timezone.utc),
        "drafting_status": "ready"}])


def seed(engine, data_dir=None):
    """Create tables; insert policy v5.0, and the kit from data_dir (default DATA_DIR) if it is there
    (kit_present). Returns {table: row count}."""
    data_dir = Path(data_dir or DATA_DIR)
    init_db(engine)
    with engine.begin() as conn:
        if kit_present(data_dir):
            seed_kit(conn, data_dir)
        seed_policy(conn)
        return {m.__tablename__: _count(conn, m) for m in (*KIT_TABLES, PolicyVersion)}


if __name__ == "__main__":
    print(seed(make_engine()))
