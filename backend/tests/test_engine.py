"""F6: the whole engine on the sample batch: worked examples on every printed field, the open cases from
docs/engine_test_list.md, and whole-batch invariants."""
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

import pytest

from engine.export import to_csv
from engine.pipeline import EXPORT_COLUMNS, decide
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
LINES = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
RESULT = decide(LINES, MASTER)
ROWS = {(r["pr_no"], r["pr_line"]): r for r in RESULT.rows}


def row(pr_no, line="1"):
    return ROWS[(pr_no, line)]


def members(pr_no):
    """The PR numbers of the requirement holding pr_no, first line first (clubbing order)."""
    gid = row(pr_no)["group_id"]
    req = next(d.requirement for d in RESULT.requirements if d.requirement.group_id == gid)
    return [c.line.pr_no for c in req.lines]


def printed(text):
    return int(Decimal(text).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# (example, line, route, supplier, unit price as printed, value as printed, suggestions, clubbed lines, item)
WORKED = [
    ("Ex 1", "PR-26-00019", "CONTRACT_PO", "S001", 9169, 137531, "", ["PR-26-00019"], "ITM-1002"),
    ("Ex 2", "PR-26-00045", "CONTRACT_PO", "S021", 2439, 26829, "", ["PR-26-00045"], "ITM-1037"),
    ("Ex 3", "PR-26-00004", "RFQ", "", None, 220256, "S014;S013;S016", ["PR-26-00004", "PR-26-00026"], "ITM-1022"),
    ("Ex 4", "PR-26-00034", "CONTRACT_PO", "S007", 7, 32547, "", ["PR-26-00034", "PR-26-00032"], "ITM-1009"),
    ("Ex 5", "PR-26-00146", "SPOT_PO", "S024", 166, 126472, "", ["PR-26-00146", "PR-26-00144", "PR-26-00145"], "ITM-1038"),
    ("Ex 6", "PR-26-00106", "SPOT_PO", "S027", 22, 156170, "", ["PR-26-00106"], "ITM-1044"),
    ("Ex 7", "PR-26-00088", "SPOT_PO", "S023", 392, 97955, "", ["PR-26-00088"], "ITM-1035"),
    ("Ex 8", "PR-26-00059", "EMERGENCY_PO", "S014", 106, 253184, "", ["PR-26-00059"], "ITM-1026"),
    ("Ex 9", "PR-26-00089", "RFQ", "", None, 336562, "S043;S044;S042", ["PR-26-00089"], "ITM-1066"),
    ("Ex 10", "PR-26-00050", "RFQ", "", None, 80300, "S003;S002;S005", ["PR-26-00050"], "ITM-1006"),
    ("Ex 11", "PR-26-00100", "RFP", "", None, 2070780, "S020;S017;S019;S018", ["PR-26-00100"], "ITM-1034"),
    ("Ex 12", "PR-26-00047", "CAPEX_SOURCING", "", None, 6036704, "S045;S047;S020;S048;S046", ["PR-26-00047"], "ITM-1071"),
    ("Ex 13", "PR-26-00170", "NEW_ITEM_SOURCING", "", None, 141100, "", ["PR-26-00170"], "NEW"),
    ("Ex 14", "PR-26-00031", "CONTRACT_PO", "S007", 7, 23227, "", ["PR-26-00031", "PR-26-00035"], "ITM-1009"),
]


@pytest.mark.parametrize("name, pr_no, route, supplier, price, value, suggested, lines, item", WORKED,
                         ids=[w[0] for w in WORKED])
def test_worked_example_on_every_printed_field(name, pr_no, route, supplier, price, value, suggested, lines, item):
    r = row(pr_no)
    assert (r["route"], r["supplier_id"], r["suggested_supplier_ids"], r["resolved_item_code"]) == (route, supplier, suggested, item)
    assert (printed(r["unit_price"]) if r["unit_price"] else None) == price
    assert printed(r["group_value_inr"]) == value
    assert members(pr_no) == lines
    assert r["decision"] == ("PO" if route.endswith("_PO") else "SOURCING_REQUEST")
    assert bool(r["po_id"]) == r["decision"].startswith("PO") and r["policy_version"] == "5.0"


def test_ex6_chk1_line_is_its_own_requirement():
    assert members("PR-26-00103") == ["PR-26-00103"] and row("PR-26-00103")["resolved_item_code"] == "ITM-1044"
    assert row("PR-26-00103")["group_id"] != row("PR-26-00106")["group_id"]


def test_ex4_and_ex14_requirements_share_one_po():
    assert row("PR-26-00034")["po_id"] == row("PR-26-00031")["po_id"] != ""
    assert row("PR-26-00034")["group_id"] != row("PR-26-00031")["group_id"]


PRINTED_POS = {"PR-26-00146": "PO-0001", "PR-26-00106": "PO-0002", "PR-26-00034": "PO-0003", "PR-26-00031": "PO-0003",
               "PR-26-00019": "PO-0011", "PR-26-00088": "PO-0023", "PR-26-00059": "PO-0024", "PR-26-00045": "PO-0072"}


def test_printed_po_numbers_are_ours_shifted_by_exactly_one():
    # Every printed PO number is ours minus one: one PO we create before 11-02 09:40 is not in the kit's
    # numbering (R-0001, PR-26-00174 + 00175). Nothing else diverges up to PO-0072. Open question for Ojas.
    shift = {int(row(p)["po_id"][3:]) - int(n[3:]) for p, n in PRINTED_POS.items()}
    assert shift == {1}
    assert row("PR-26-00174")["po_id"] == "PO-0001" and members("PR-26-00174") == ["PR-26-00174", "PR-26-00175"]


@pytest.mark.xfail(strict=True, reason="open question: the kit's PO numbering has no PO for PR-26-00174/00175")
def test_printed_po_numbers_exactly():
    assert {p: row(p)["po_id"] for p in PRINTED_POS} == PRINTED_POS


# ---------------------------------------------------------------- open cases from docs/engine_test_list.md
def test_pr_26_00036_gets_no_contract_a_day_before_rc_2026_031_starts():
    r = row("PR-26-00036")
    assert r["route"] != "CONTRACT_PO" and "RC-2026-031" not in r["reason"]


@pytest.mark.parametrize("a, b", [("PR-26-00055", "PR-26-00053"), ("PR-26-00099", "PR-26-00053"),
                                  ("PR-26-00011", ("PR-26-00166", "1")), ("PR-26-00011", ("PR-26-00166", "3"))])
def test_the_four_exact_24_hour_pairs_never_share_a_po(a, b):
    ra = row(a)
    rb = row(*b) if isinstance(b, tuple) else row(b)
    assert not (ra["po_id"] and ra["po_id"] == rb["po_id"])


def test_same_date_tie_uses_the_highest_po_number():
    assert row("PR-26-00100")["group_value_inr"] == "2070780.00" and "7300220" in row("PR-26-00100")["reason"]


@pytest.mark.parametrize("pr_no, value", [("PR-26-00069", "565000.92"), ("PR-26-00058", "424920.00"),
                                          ("PR-26-00122", "871086.00"), ("PR-26-00083", "23319.00"),
                                          ("PR-26-00060", "106231.00")])
def test_d2_values(pr_no, value):
    assert row(pr_no)["group_value_inr"] == value


def test_not_processed_and_new_items():
    assert (row("PR-26-00172")["route"], row("PR-26-00173")["route"]) == ("NOT_PROCESSED", "NOT_PROCESSED")
    assert "V1" in row("PR-26-00172")["reason"] and "V2" in row("PR-26-00173")["reason"]
    assert all(row(p)[c] == "" for p in ("PR-26-00172", "PR-26-00173") for c in ("group_id", "po_id", "decision"))
    assert (row("PR-26-00171")["route"], row("PR-26-00171")["group_value_inr"]) == ("NEW_ITEM_SOURCING", "105600.00")


# ---------------------------------------------------------------- whole-batch invariants
def test_one_row_per_pr_line_in_input_order():
    assert [(r["pr_no"], r["pr_line"]) for r in RESULT.rows] == [(l.pr_no, l.pr_line) for l in LINES]


def test_no_contract_ends_above_its_ceiling():
    caps = {c.contract_id: c.value_cap for c in MASTER.contracts}
    for cid, used in RESULT.ceiling_final.items():
        assert used <= caps[cid] or used == RESULT.ceiling_baseline[cid], cid


def test_po_rows_have_supplier_price_and_po_and_sourcing_rows_have_none():
    for r in RESULT.rows:
        if r["decision"] == "PO":
            assert r["supplier_id"] and r["unit_price"] and r["po_id"] and not r["suggested_supplier_ids"]
        elif r["decision"] == "SOURCING_REQUEST":
            assert not r["po_id"] and not r["supplier_id"] and not r["unit_price"]


def test_all_lines_of_a_requirement_share_one_decision():
    shared = ["group_id", "po_id", "decision", "route", "supplier_id", "unit_price", "group_value_inr",
              "suggested_supplier_ids", "policy_version", "resolved_item_code"]
    groups = defaultdict(set)
    for r in RESULT.rows:
        if r["group_id"]:
            groups[r["group_id"]].add(tuple(r[c] for c in shared))
    assert all(len(v) == 1 for v in groups.values())


def test_no_supplier_outside_the_allowed_statuses_appears_anywhere():
    statuses = MASTER.policies[0].document["parameters"]["suppliers"]["allowed_statuses"]
    for r in RESULT.rows:
        if r["supplier_id"]:
            assert MASTER.suppliers[r["supplier_id"]].status in statuses["receive_po"]
        for s in filter(None, r["suggested_supplier_ids"].split(";")):
            assert MASTER.suppliers[s].status in statuses["be_suggested"]
    used = {r["supplier_id"] for r in RESULT.rows} | {s for r in RESULT.rows for s in r["suggested_supplier_ids"].split(";")}
    assert not used & {"S004", "S008", "S011", "S031", "S034"}  # the Blocked and Inactive suppliers


def test_running_twice_gives_identical_bytes():
    assert to_csv(decide(LINES, MASTER)) == to_csv(RESULT)
    assert to_csv(RESULT).splitlines()[0] == ",".join(EXPORT_COLUMNS)


def test_shuffling_the_input_rows_gives_identical_decisions():
    shuffled = list(LINES)
    random.Random(7).shuffle(shuffled)
    again = {(r["pr_no"], r["pr_line"]): r.values for r in decide(shuffled, MASTER).rows}
    assert again == {k: r.values for k, r in ROWS.items()}
