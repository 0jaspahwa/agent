"""F3: preferred supplier lists (policy 6), the fitted score (D24), reference prices and category top-ups."""
import copy
from datetime import date
from decimal import Decimal

import pytest

from engine.preferred import preferred_list, topup_suppliers
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
PARAMS = MASTER.policies[0].document["parameters"]
ACTIVE = PARAMS["suppliers"]["allowed_statuses"]["be_suggested"]


def ranked(item, on, params=PARAMS):
    return [r.supplier_id for r in preferred_list(item, on, MASTER, params)]


@pytest.mark.parametrize("item, order", [
    ("ITM-1048", ["S029", "S030"]),           # S031 (Inactive) excluded
    ("ITM-1036", ["S023", "S022", "S024"]),
    ("ITM-1016", ["S009", "S010"]),           # the contract breaks the tie
])
def test_the_three_printed_rankings_exactly(item, order):
    assert ranked(item, date(2026, 11, 1)) == order


def test_inactive_supplier_with_pos_is_excluded():
    assert any(p.supplier_id == "S031" and p.item_code == "ITM-1048" for p in MASTER.po_history)
    assert "S031" not in ranked("ITM-1048", date(2026, 11, 1))


@pytest.mark.parametrize("item, on, first, reference_price", [
    ("ITM-1038", date(2026, 11, 2), "S024", Decimal("166.41")),   # Ex 5: printed "S024 at 166"
    ("ITM-1044", date(2026, 11, 2), "S027", Decimal("21.59")),    # Ex 6: S027 at its own 21.59, not the 21.19 valuation
    ("ITM-1035", date(2026, 11, 6), "S023", Decimal("391.82")),   # Ex 7: printed 392
    ("ITM-1026", date(2026, 11, 6), "S014", Decimal("106.38")),   # Ex 8: printed 106
])
def test_first_preferred_supplier_and_reference_price_in_ex_5_to_8(item, on, first, reference_price):
    top = preferred_list(item, on, MASTER, PARAMS)[0]
    assert (top.supplier_id, top.rank, top.reference_price) == (first, 1, reference_price)
    assert top.reference.startswith("PO ")


def test_ex5_recent_supplier_with_fewer_pos_beats_older_one_with_more():
    s024, s023 = [r for r in preferred_list("ITM-1038", date(2026, 11, 2), MASTER, PARAMS) if r.supplier_id in ("S024", "S023")]
    assert (s024.inputs["po_count"], s024.inputs["recency"], s023.inputs["po_count"], s023.inputs["recency"]) == (4, 1, 6, Decimal("0.5"))
    assert s024.rank < s023.rank


@pytest.mark.parametrize("item, on, order", [
    ("ITM-1022", date(2026, 11, 2), ["S014", "S013", "S016"]),   # Ex 3
    ("ITM-1066", date(2026, 11, 5), ["S043", "S044"]),           # Ex 9 (S042 comes from the category)
    ("ITM-1006", date(2026, 11, 2), []),                         # Ex 10: never bought; S004 is Blocked
    ("ITM-1034", date(2026, 11, 4), ["S020"]),                   # Ex 11
    ("ITM-1071", date(2026, 11, 3), ["S045"]),                   # Ex 12
])
def test_preferred_part_of_the_suggestion_lists(item, on, order):
    assert ranked(item, on) == order


def test_score_parts_add_up_and_show_why():
    s029 = preferred_list("ITM-1048", date(2026, 11, 1), MASTER, PARAMS)[0]
    parts = dict(s029.parts)
    assert parts == {"po_count": 7, "recency": 5, "contract_held": 2, "on_time": Decimal("0.81"), "quality": Decimal("0.62")}
    assert sum(parts.values()) == s029.score == Decimal("15.43")


def test_expired_contract_still_puts_its_supplier_on_the_list_with_the_contract_rate():
    # RC-2025-020 (S033) ended 2026-09-30 but started before the date (6.1b); S033 has no POs for ITM-1053,
    # so it is on the list only through the expired contract, and its reference price is that rate (6.3).
    s033 = next(r for r in preferred_list("ITM-1053", date(2026, 11, 2), MASTER, PARAMS) if r.supplier_id == "S033")
    assert (s033.inputs["po_count"], s033.inputs["contract_held"]) == (0, True)
    assert (s033.reference, s033.reference_price) == ("contract RC-2025-020", Decimal("3928.84"))


def test_pdf_only_contract_counts_from_its_start_date():
    held = lambda on: next(r for r in preferred_list("ITM-1037", on, MASTER, PARAMS) if r.supplier_id == "S021").inputs["contract_held"]
    assert (held(date(2026, 11, 14)), held(date(2026, 11, 15))) == (False, True)  # RC-2026-031 starts 11-15


@pytest.mark.parametrize("item, exclude, expected", [
    ("ITM-1066", {"S043", "S044"}, ["S042"]),                     # Ex 9: one top-up needed
    ("ITM-1006", set(), ["S003", "S002", "S005"]),                # Ex 10: all three from Steel & Metals
    ("ITM-1034", {"S020"}, ["S017", "S019", "S018"]),             # Ex 11: only three more exist (D9)
    ("ITM-1071", {"S045"}, ["S047", "S020", "S048", "S046"]),     # Ex 12: S020 = S048 on score, id decides (D13)
])
def test_category_top_ups_best_delivery_and_quality_first(item, exclude, expected):
    got = [sid for sid, _, _ in topup_suppliers(item, MASTER, PARAMS, ACTIVE, exclude)]
    assert got[:len(expected)] == expected
    if item in ("ITM-1034", "ITM-1071"):
        assert got == expected  # nobody else lists the category: never padded


def test_blocked_supplier_is_never_a_top_up():
    assert "S004" not in [sid for sid, _, _ in topup_suppliers("ITM-1006", MASTER, PARAMS, ACTIVE)]


def test_weights_are_policy_data():
    params = copy.deepcopy(PARAMS)
    params["ranking"]["preferred_score"]["weights"]["recency"] = 0  # count alone: S023 (6 POs) would win Ex 5
    assert ranked("ITM-1038", date(2026, 11, 2), params)[0] == "S023"
