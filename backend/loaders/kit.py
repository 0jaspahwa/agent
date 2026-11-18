"""Build the engine's inputs straight from the kit files in data/ (no database).

Used by tests and scripts, and as the reference the database loader must match exactly.
"""
import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from engine.inputs import Contract, ContractLine, HistoricalPO, Item, MasterData, Plant, PolicyVersion, PRLine, Supplier
from engine.policy import POLICY_DIR
from kitdata import DATA_DIR, REGISTER_AS_OF
from loaders.contract_pdf import pdf_only_contracts
from loaders.pr_csv import parse_pr_csv


def _csv(data_dir, rel):
    with open(Path(data_dir) / rel, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def register_contracts(data_dir=DATA_DIR):
    lines = {}
    for r in _csv(data_dir, "contracts/contract_lines.csv"):
        lines.setdefault(r["contract_id"], []).append(
            ContractLine(r["item_code"], r["description"], r["uom"], Decimal(r["rate"])))
    return [Contract(r["contract_id"], r["supplier_id"], r["supplier_name"], date.fromisoformat(r["start_date"]),
                     date.fromisoformat(r["end_date"]), Decimal(r["value_cap"]), Decimal(r["consumed_value"]),
                     REGISTER_AS_OF, "register",
                     tuple(sorted(lines.get(r["contract_id"], []), key=lambda l: l.item_code)))
            for r in _csv(data_dir, "contracts/contract_register.csv")]


def load_master(data_dir=DATA_DIR):
    """MasterData from the kit: register contracts plus the contracts that exist only as signed PDFs."""
    items = {r["item_code"]: Item(r["item_code"], r["description"], r["uom"], r["category"], r["item_type"],
                                  Decimal(r["standard_price"])) for r in _csv(data_dir, "master_data/item_master.csv")}
    suppliers = {r["supplier_id"]: Supplier(r["supplier_id"], r["name"], r["city"], tuple(r["categories"].split(";")),
                                            r["status"], Decimal(r["on_time_pct"]), Decimal(r["quality_rating"]))
                 for r in _csv(data_dir, "master_data/supplier_master.csv")}
    plants = {r["plant"]: Plant(r["plant"], r["name"]) for r in _csv(data_dir, "master_data/plants.csv")}
    history = tuple(sorted(
        (HistoricalPO(r["po_number"], date.fromisoformat(r["po_date"]), r["supplier_id"], r["item_code"],
                      Decimal(r["quantity"]), r["uom"], Decimal(r["unit_price"]), r["plant"],
                      r["delivered_on_time"] == "True") for r in _csv(data_dir, "master_data/po_history.csv")),
        key=lambda p: (p.po_date, p.po_number)))
    register = register_contracts(data_dir)
    pdf_only = pdf_only_contracts(Path(data_dir) / "contracts" / "pdf", {c.contract_id for c in register})
    contracts = tuple(sorted([*register, *pdf_only], key=lambda c: c.contract_id))
    document = json.loads((POLICY_DIR / "v5.0.json").read_text(encoding="utf-8"))
    policies = (PolicyVersion(document["version"], date.fromisoformat(document["effective_from"]), document),)
    return MasterData(items, suppliers, plants, history, contracts, policies)


def load_pr_batch(path):
    """The PR lines of a batch CSV, in file order."""
    text = Path(path).read_text(encoding="utf-8")
    return tuple(PRLine(**typed, source="batch") for _raw, typed in parse_pr_csv(text))
