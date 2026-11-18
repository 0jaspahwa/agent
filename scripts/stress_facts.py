"""Facts for working out the stress batch's expected outcomes by hand (S1), read straight from the kit's CSV files
with the policy's own definitions, independently of the engine (no engine module is imported).

For an item and a requirement date: standard price, contracts, the latest PO in the 365 days before (any
supplier; highest PO number on a tie, D1), whether it was bought from an Active supplier in that window, and
the preferred list (548 days, D24 score = POs + 5 x recency + 2 x contract held + on-time/100 + quality/5).

    python scripts/stress_facts.py ITM-1048 2026-11-16 [ITM-... date ...]
"""
import csv
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def rows(rel):
    with open(DATA / rel, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


ITEMS = {r["item_code"]: r for r in rows("master_data/item_master.csv")}
SUPPLIERS = {r["supplier_id"]: r for r in rows("master_data/supplier_master.csv")}
POS = rows("master_data/po_history.csv")
REGISTER = rows("contracts/contract_register.csv")
LINES = rows("contracts/contract_lines.csv")
PDF_ONLY = [  # read from data/contracts/pdf by hand (the register does not have them)
    {"contract_id": "RC-2026-031", "supplier_id": "S021", "start_date": "2026-11-15", "end_date": "2027-11-14",
     "items": {"ITM-1036": "3537.76", "ITM-1037": "2439.01", "ITM-1039": "2746.87"}},
    {"contract_id": "RC-2026-033", "supplier_id": "S035", "start_date": "2026-11-20", "end_date": "2027-11-19",
     "items": {"ITM-1056": "64654.36", "ITM-1057": "10689.51"}},
]


def contracts_for(item):
    out = []
    for c in REGISTER:
        for ln in LINES:
            if ln["contract_id"] == c["contract_id"] and ln["item_code"] == item:
                out.append((c["contract_id"], c["supplier_id"], c["start_date"], c["end_date"], ln["rate"],
                            Decimal(c["value_cap"]) - Decimal(c["consumed_value"])))
    for c in PDF_ONLY:
        if item in c["items"]:
            out.append((c["contract_id"], c["supplier_id"], c["start_date"], c["end_date"], c["items"][item], None))
    return out


def facts(item, on):
    it = ITEMS[item]
    d = date.fromisoformat(on)
    hist = [p for p in POS if p["item_code"] == item]
    win365 = [p for p in hist if d - timedelta(days=365) <= date.fromisoformat(p["po_date"]) < d]
    latest = max(win365, key=lambda p: (p["po_date"], p["po_number"])) if win365 else None
    active = [p for p in win365 if SUPPLIERS[p["supplier_id"]]["status"] == "Active"]
    print(f"{item} {it['description']} | {it['category']} | {it['item_type']} | std {it['standard_price']} {it['uom']} | as of {on}")
    for c in contracts_for(item):
        s = SUPPLIERS[c[1]]
        print(f"   contract {c[0]} {c[1]} ({s['status']}) {c[2]}..{c[3]} rate {c[4]} ceiling left {c[5]}")
    print(f"   latest PO in 365 days: {latest['po_number']} {latest['po_date']} {latest['supplier_id']} "
          f"({SUPPLIERS[latest['supplier_id']]['status']}) {latest['unit_price']}" if latest else "   no PO in 365 days")
    print(f"   bought from an Active supplier in 365 days: {bool(active)}")
    win548 = [p for p in hist if d - timedelta(days=548) <= date.fromisoformat(p["po_date"]) < d]
    members = {p["supplier_id"] for p in win548 if SUPPLIERS[p["supplier_id"]]["status"] == "Active"}
    members |= {c[1] for c in contracts_for(item) if c[2] <= on and SUPPLIERS[c[1]]["status"] == "Active"}
    ranked = []
    for sid in members:
        s = SUPPLIERS[sid]
        mine = [p for p in win548 if p["supplier_id"] == sid]
        age = (d - max(date.fromisoformat(p["po_date"]) for p in mine)).days if mine else None
        recency = Decimal(1) if age is not None and age <= 90 else Decimal("0.5") if age is not None and age <= 365 else Decimal(0)
        held = any(c[1] == sid and c[2] <= on for c in contracts_for(item))
        score = len(mine) + 5 * recency + (2 if held else 0) + Decimal(s["on_time_pct"]) / 100 + Decimal(s["quality_rating"]) / 5
        last = max(mine, key=lambda p: (p["po_date"], p["po_number"])) if mine else None
        ref = last["unit_price"] if last else next((c[4] for c in contracts_for(item) if c[1] == sid), None)
        ranked.append((-score, sid, score, len(mine), recency, held, ref))
    for i, (_, sid, score, n, rec, held, ref) in enumerate(sorted(ranked), start=1):
        print(f"   preferred #{i} {sid} score {score:.2f} (POs {n}, recency {rec}, contract {held}) ref price {ref}")
    actives = sorted(sid for sid, s in SUPPLIERS.items() if s["status"] == "Active" and it["category"] in s["categories"])
    print(f"   Active suppliers in the category: {actives}")


if __name__ == "__main__":
    args = sys.argv[1:]
    for i in range(0, len(args), 2):
        facts(args[i], args[i + 1])
