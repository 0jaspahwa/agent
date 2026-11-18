"""S1: the stress batch (backend/tests/fixtures/stress_batch.csv) against expectations worked out by hand from the
policy and the data (stress_batch.expected.csv, with the reasoning per line; scripts/stress_facts.py). Each
listed field is compared; grouping and PO membership are compared as sets of lines, not by their ids."""
import csv
from pathlib import Path
from collections import defaultdict
from decimal import Decimal

import pytest

from engine.pipeline import decide
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

FIXTURES = Path(__file__).parent / "fixtures"
BATCH = FIXTURES / "stress_batch.csv"
EXPECTED = list(csv.DictReader(open(FIXTURES / "stress_batch.expected.csv", encoding="utf-8")))


def _rows():
    rows = [r.values for r in decide(kit.load_pr_batch(BATCH), kit.load_master()).rows]
    seen, out = defaultdict(int), {}
    for r in rows:
        ref = f"{r['pr_no']}/{r['pr_line']}"
        seen[ref] += 1
        out[ref if seen[ref] == 1 else f"{ref}#{seen[ref]}"] = r
    return out


ROWS = _rows()


def members(column, ref):
    value = ROWS[ref][column]
    return sorted(k for k, r in ROWS.items() if value and r[column] == value and k != ref)


def problems(e):
    got, out = ROWS.get(e["ref"]), []
    if got is None:
        return [f"no output row for {e['ref']}"]
    checks = [("item", "resolved_item_code"), ("route", "route"), ("supplier", "supplier_id"),
              ("suggestions", "suggested_supplier_ids")]
    for field, column in checks:
        if e[field] != got[column] and (e[field] or field in ("supplier", "suggestions")):
            out.append(f"{field}: expected {e[field]!r}, got {got[column]!r}")
    for field, column in (("unit_price", "unit_price"), ("value", "group_value_inr")):
        if (Decimal(e[field]) if e[field] else None) != (Decimal(got[column]) if got[column] else None):
            out.append(f"{field}: expected {e[field]!r}, got {got[column]!r}")
    if e["route"] != "NOT_PROCESSED":
        for field, column in (("grouped_with", "group_id"), ("same_po_as", "po_id")):
            want = sorted(x for x in e[field].split(";") if x)
            if members(column, e["ref"]) != want:
                out.append(f"{field}: expected {want}, got {members(column, e['ref'])}")
    for flag in filter(None, e["flags"].split(";")):
        if f"note {flag}:" not in got["reason"]:
            out.append(f"flag {flag} missing from the reason")
    return out


def test_every_line_has_an_expectation():
    assert sorted(ROWS) == sorted(e["ref"] for e in EXPECTED)


@pytest.mark.parametrize("e", EXPECTED, ids=[e["ref"] for e in EXPECTED])
def test_line_matches_the_worked_out_expectation(e):
    assert problems(e) == [], f"{e['case']}: {e['why']}"
