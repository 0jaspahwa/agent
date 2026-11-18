"""F2: valuation (policy 3.1) in price_sources order, exact to the paisa."""
import copy
import dataclasses
from decimal import Decimal

import pytest

from engine.clubbing import club
from engine.contracts import CeilingBook, choose_contract
from engine.valuation import value_requirement
from engine.validation import check_lines
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
PARAMS = MASTER.policies[0].document["parameters"]
REQS = club(check_lines(kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"), MASTER), MASTER)


def req(pr_no):
    return next(r for r in REQS if any(c.line.pr_no == pr_no for c in r.lines))


def value(pr_no, params=PARAMS, book=None):
    r = req(pr_no)
    choice = choose_contract(r.item_code, r.requirement_date, r.total_quantity, MASTER, params,
                             book or CeilingBook(MASTER.contracts)) if not r.is_new else None
    return value_requirement(r, choice, MASTER, params)


# (worked example, a line of the requirement, source, unit price, value to the paisa, printed value, reference)
WORKED = [
    ("Ex 1", "PR-26-00019", "contract_to_be_used", "9168.71", "137530.65", 137531, "RC-2025-011"),
    ("Ex 2", "PR-26-00045", "contract_to_be_used", "2439.01", "26829.11", 26829, "RC-2026-031"),
    ("Ex 3", "PR-26-00004", "lowest_applicable_contract_rate", "579.62", "220255.60", 220256, "RC-2026-002"),
    ("Ex 4", "PR-26-00034", "contract_to_be_used", "7.06", "32546.60", 32547, "RC-2026-013"),
    ("Ex 5", "PR-26-00146", "latest_po_in_window", "166.41", "126471.60", 126472, None),
    ("Ex 6", "PR-26-00106", "latest_po_in_window", "21.19", "156170.30", 156170, None),
    ("Ex 7", "PR-26-00088", "latest_po_in_window", "391.82", "97955.00", 97955, None),
    ("Ex 8", "PR-26-00059", "latest_po_in_window", "106.38", "253184.40", 253184, None),
    ("Ex 9", "PR-26-00089", "latest_po_in_window", "67312.43", "336562.15", 336562, None),
    ("Ex 10", "PR-26-00050", "standard_price", "365", "80300.00", 80300, None),
    ("Ex 11", "PR-26-00100", "latest_po_in_window", "41415.6", "2070780.00", 2070780, "7300220"),  # D1 tie
    ("Ex 12", "PR-26-00047", "latest_po_in_window", "1509176.02", "6036704.08", 6036704, None),
    ("Ex 13", "PR-26-00170", "requester_estimate", "141100.0", "141100.00", 141100, None),
    ("Ex 14", "PR-26-00031", "contract_to_be_used", "7.06", "23227.40", 23227, "RC-2026-013"),
]


@pytest.mark.parametrize("name, pr_no, source, price, exact, printed, ref", WORKED, ids=[w[0] for w in WORKED])
def test_worked_example_values(name, pr_no, source, price, exact, printed, ref):
    v = value(pr_no)
    assert (v.source, v.unit_price, v.value) == (source, Decimal(price), Decimal(exact))
    assert round(v.value) == printed  # as printed in Worked_Examples.pdf
    if ref:
        assert v.reference == ref


@pytest.mark.parametrize("pr_no, exact, price", [
    ("PR-26-00069", "565000.92", "1479.06"),   # argon, clubbed 382 CYL, latest PO from Blocked S011 (D2)
    ("PR-26-00058", "424920.00", "212.46"),    # cutting wheel CHK1, Blocked S011 PO
    ("PR-26-00122", "871086.00", "212.46"),    # cutting wheel PUN1
    ("PR-26-00083", "23319.00", "129.55"),     # goggles, Inactive S031 PO
    ("PR-26-00060", "106231.00", "129.55"),
])
def test_d2_values_count_blocked_and_inactive_suppliers_pos(pr_no, exact, price):
    v = value(pr_no)
    assert (v.source, v.unit_price, v.value) == ("latest_po_in_window", Decimal(price), Decimal(exact))


def test_d2_is_a_setting_excluding_non_active_suppliers_changes_the_argon_value():
    params = copy.deepcopy(PARAMS)
    params["valuation"]["include_non_active_suppliers"] = False
    assert value("PR-26-00069", params).value == Decimal("616597.66")  # 382 x 1614.13, the latest Active PO


def test_a_new_item_without_an_estimate_has_no_value():
    r = req("PR-26-00170")
    blank = dataclasses.replace(r.first, line=dataclasses.replace(r.first.line, estimated_unit_price=None))
    v = value_requirement(dataclasses.replace(r, lines=(blank,)), None, MASTER, PARAMS)
    assert (v.value, v.unit_price, v.source) == (None, None, "requester_estimate") and "D12" in v.note


def test_the_price_source_order_is_policy_data():
    params = copy.deepcopy(PARAMS)
    params["valuation"]["price_sources"] = ["standard_price"]
    assert value("PR-26-00019", params).value == Decimal("148500.00")  # 15 x 9900, not the contract rate
