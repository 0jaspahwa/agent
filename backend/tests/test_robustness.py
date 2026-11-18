"""S2: 200 generated batches (fixed seed), checked for invariants only. Each batch is written as CSV and read
by the real batch reader, so the reader is exercised too.

Generated: real items (and free-text descriptions with noise, typos and purpose clauses), both plants and now
and then an unknown one, November timestamps (some exactly 24 h apart), need-by dates, whole and decimal
quantities, urgency (Normal, Emergency, blank, odd words), blank optional cells, a wrong unit now and then,
shuffled row order. PR numbers are unique, so the order of the rows cannot matter (a duplicated PR line is
order-dependent by design: the first one is processed, V3).

Invariants: no crash; exactly one row per line; every PO row has a supplier whose status may receive a PO,
and a price; no sourcing row has a PO id; no contract ends above its ceiling; all lines of a requirement share
one decision and route; the same lines in another order give identical rows.
"""
import csv
import io
import random
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from engine.inputs import PRLine
from engine.pipeline import decide
from loaders import kit
from loaders.pr_csv import parse_pr_csv

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
ITEMS = sorted(MASTER.items)
SEED, BATCHES = 20261118, 200
COLUMNS = ["pr_no", "pr_line", "created_at", "requester", "department", "plant", "item_code", "description",
           "quantity", "uom", "estimated_unit_price", "need_by_date", "urgency"]
NOISE = ["as per sample", "for maintenance", "(repeat)", "urgent", "for paint shop", "pls"]
PO_ROUTES = {"CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO"}


def typo(word, rnd):
    if len(word) < 5 or rnd.random() < 0.7:
        return word
    i = rnd.randrange(1, len(word) - 1)
    return word[:i] + word[i + 1:]


def generate(rnd, n_batch):
    rows, base = [], datetime(2026, 11, 1, 8, 0)
    anchors = []
    for n in range(rnd.randint(20, 80)):
        code = rnd.choice(ITEMS)
        item = MASTER.items[code]
        if anchors and rnd.random() < 0.1:
            created = rnd.choice(anchors) + timedelta(hours=24)  # exactly 24 h after another line
        else:
            created = base + timedelta(days=rnd.randint(0, 19), hours=rnd.randint(0, 10), minutes=rnd.choice([0, 15, 30, 45]),
                                       seconds=rnd.choice([0, 0, 0, 1, 59]))
        anchors.append(created)
        free_text = rnd.random() < 0.3
        desc = item.description
        if free_text:
            desc = " ".join(typo(w, rnd) for w in desc.split())
            if rnd.random() < 0.5:
                desc = f"{desc} {rnd.choice(NOISE)}"
            desc = desc.lower() if rnd.random() < 0.5 else desc
        qty = (Decimal(rnd.randint(1, 4000)) / 4 if item.uom in ("KG", "MTR", "LTR") and rnd.random() < 0.5
               else Decimal(rnd.choice([1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 3000])))
        rows.append({
            "pr_no": f"G{n_batch:03d}-{n:03d}", "pr_line": "1",
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S" if created.second else "%Y-%m-%d %H:%M"),
            "requester": rnd.choice(["A. Rao", "B. Shah", "", "C. Iyer"]), "department": rnd.choice(["Stores", "", "IT"]),
            "plant": rnd.choices(["PUN1", "CHK1", "PUN2", ""], weights=[45, 45, 5, 5])[0],
            "item_code": "" if free_text else code, "description": desc, "quantity": str(qty),
            "uom": item.uom if rnd.random() > 0.05 else rnd.choice(["KG", "NOS", ""]),
            "estimated_unit_price": rnd.choice(["", "", "", str(rnd.randint(10, 90000))]),
            "need_by_date": (created + timedelta(days=rnd.randint(-2, 25))).date().isoformat() if rnd.random() > 0.03 else "",
            "urgency": rnd.choices(["Normal", "Emergency", "", "urgent", "NORMAL"], weights=[70, 15, 8, 4, 3])[0],
        })
    rnd.shuffle(rows)
    return rows


def as_csv(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def lines_of(rows):
    """Through the real batch reader, as loaders/kit.py does for a file."""
    return tuple(PRLine(**typed, source="batch") for _raw, typed in parse_pr_csv(as_csv(rows)))


def money(x):
    return Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)


def violations(rows, result):
    found = []
    refs = [f"{r['pr_no']}/{r['pr_line']}" for r in rows]
    out = {f"{r['pr_no']}/{r['pr_line']}": r.values for r in result.rows}
    if len(result.rows) != len(rows) or sorted(out) != sorted(refs):
        found.append(f"{len(result.rows)} rows for {len(rows)} lines")
    allowed = set(MASTER.policies[-1].document["parameters"]["suppliers"]["allowed_statuses"]["receive_po"])
    for ref, r in out.items():
        if r["route"] in PO_ROUTES:
            s = MASTER.suppliers.get(r["supplier_id"])
            if s is None or s.status not in allowed or not r["unit_price"] or not r["po_id"]:
                found.append(f"{ref}: PO row with supplier {r['supplier_id']!r} ({s.status if s else '?'}), "
                             f"price {r['unit_price']!r}, PO {r['po_id']!r}")
        elif r["po_id"]:
            found.append(f"{ref}: {r['route']} row has PO id {r['po_id']}")
    used = defaultdict(Decimal)
    for d in result.requirements:
        if d.outcome.route == "CONTRACT_PO":
            c = d.outcome.uses_contract.contract
            used[c.contract_id] += money(d.requirement.total_quantity * d.outcome.unit_price)
    for c in MASTER.contracts:
        start = result.ceiling_baseline.get(c.contract_id, c.consumed_value)
        if start + used[c.contract_id] > c.value_cap:
            found.append(f"{c.contract_id}: {start} + {used[c.contract_id]} > ceiling {c.value_cap}")
        if c.contract_id in result.ceiling_final and result.ceiling_final[c.contract_id] != start + used[c.contract_id]:
            found.append(f"{c.contract_id}: the engine's own total {result.ceiling_final[c.contract_id]} differs from "
                         f"{start + used[c.contract_id]}")
    groups = defaultdict(set)
    for r in out.values():
        if r["group_id"]:
            groups[r["group_id"]].add((r["decision"], r["route"]))
    found += [f"{g}: lines with different decisions {sorted(v)}" for g, v in groups.items() if len(v) > 1]
    return found, out


def test_the_checks_catch_a_broken_result():
    """The invariants would fail if the engine broke them (each tampering is caught)."""
    from dataclasses import replace
    rnd = random.Random(SEED)
    rows = generate(rnd, 0)
    result = decide(lines_of(rows), MASTER)
    po = next(r for r in result.rows if r["route"] == "SPOT_PO")
    sourcing = next(r for r in result.rows if r["route"] in ("RFQ", "RFP", "CAPEX_SOURCING"))
    tampered = [
        lambda r: r.values.update(supplier_id="S004") if r is po else None,  # a Blocked supplier
        lambda r: r.values.update(po_id="PO-9999") if r is sourcing else None,  # a sourcing row on a PO
        lambda r: r.values.update(route="RFQ", decision="SOURCING_REQUEST") if r is po else None,  # split group
    ]
    for change in tampered:
        broken = replace(result, rows=tuple(type(r)(r.index, dict(r.values)) for r in result.rows))
        po = next(r for r in broken.rows if r["route"] == "SPOT_PO")
        sourcing = next(r for r in broken.rows if r["route"] in ("RFQ", "RFP", "CAPEX_SOURCING"))
        for r in broken.rows:
            change(r)
        found, _ = violations(rows, broken)
        assert found, "a broken result passed the checks"
    assert violations(rows[:-1], result)[0]  # a missing row


@pytest.mark.parametrize("chunk", range(10))
def test_two_hundred_generated_batches_keep_every_invariant(chunk):
    rnd = random.Random(SEED + chunk)
    problems = []
    for n in range(chunk * BATCHES // 10, (chunk + 1) * BATCHES // 10):
        rows = generate(rnd, n)
        lines = lines_of(rows)
        try:
            result = decide(lines, MASTER)
        except Exception as exc:  # noqa: BLE001 - a crash is the first thing this test looks for
            problems.append(f"batch {n}: crashed: {type(exc).__name__}: {exc}")
            continue
        found, out = violations(rows, result)
        problems += [f"batch {n}: {p}" for p in found]
        shuffled = list(rows)
        random.Random(n).shuffle(shuffled)
        again = {f"{r['pr_no']}/{r['pr_line']}": r.values for r in decide(lines_of(shuffled), MASTER).rows}
        if again != out:
            diff = sorted(k for k in out if again.get(k) != out[k])
            problems.append(f"batch {n}: another row order changes {len(diff)} rows, e.g. {diff[:3]}")
    assert problems == [], "\n".join(problems[:30])
