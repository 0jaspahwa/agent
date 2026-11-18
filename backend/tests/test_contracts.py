"""F1: applicable and usable contracts (policy 4), with a running ceiling."""
import copy
import dataclasses
from datetime import date
from decimal import Decimal

from engine.contracts import CeilingBook, applicable_contracts, choose_contract, money
from engine.inputs import Contract, ContractLine
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
PARAMS = MASTER.policies[0].document["parameters"]


def choose(item, on, qty, master=MASTER, params=PARAMS, book=None):
    book = book or CeilingBook(master.contracts)
    return choose_contract(item, on, Decimal(qty), master, params, book)


def ids(choice):
    return [o.contract.contract_id for o in choice.applicable]


def test_ex1_register_contract_with_room():
    c = choose("ITM-1002", date(2026, 11, 4), 15)
    assert (c.chosen.contract.contract_id, c.chosen.rate, c.chosen.value) == ("RC-2025-011", Decimal("9168.71"), Decimal("137530.65"))


def test_ex2_pdf_only_contract_applies_after_its_start():
    c = choose("ITM-1037", date(2026, 11, 18), 11)
    assert (c.chosen.contract.contract_id, c.chosen.consumed_before, c.chosen.value) == ("RC-2026-031", 0, Decimal("26829.11"))


def test_pr_26_00036_one_day_before_the_pdf_contract_starts_gets_none():
    assert ids(choose("ITM-1039", date(2026, 11, 14), 30)) == []
    assert ids(choose("ITM-1039", date(2026, 11, 15), 30)) == ["RC-2026-031"]  # start date is inclusive


def test_ex3_applicable_but_out_of_ceiling():
    c = choose("ITM-1022", date(2026, 11, 2), 380)
    assert ids(c) == ["RC-2026-002"] and c.chosen is None
    assert c.lowest.remaining_before == Decimal("38000.00") and c.lowest_rate == Decimal("579.62")


def test_ex4_cheapest_lacks_room_so_the_next_is_used():
    c = choose("ITM-1009", date(2026, 11, 2), 4610)
    assert ids(c) == ["RC-2026-015", "RC-2026-013"]  # 6.45 then 7.06
    assert [o.fits for o in c.applicable] == [False, True]
    assert (c.chosen.contract.contract_id, c.chosen.value) == ("RC-2026-013", Decimal("32546.60"))


def test_ex10_blocked_suppliers_contract_does_not_apply():
    assert ids(choose("ITM-1006", date(2026, 11, 2), 220)) == []  # RC-2026-005 belongs to Blocked S004


def test_expired_contract_does_not_apply_but_end_date_is_inclusive():
    assert ids(choose("ITM-1052", date(2026, 11, 2), 1)) == []  # RC-2025-020 ended 2026-09-30
    assert ids(choose("ITM-1016", date(2026, 11, 30), 1)) == ["RC-2025-014"]  # ends 11-30: still valid
    assert ids(choose("ITM-1016", date(2026, 12, 1), 1)) == []


def test_the_ceiling_is_shared_by_all_items_of_a_contract():
    book = CeilingBook(MASTER.contracts)
    first = choose("ITM-1009", date(2026, 11, 2), 4610, book=book).chosen  # RC-2026-013: 250000 consumed
    book.consume(first.contract.contract_id, first.value)
    left = Decimal("800000") - Decimal("250000") - first.value
    nut = choose("ITM-1010", date(2026, 11, 3), 1, book=book).chosen  # same contract, another item
    assert nut.consumed_before == Decimal("250000") + first.value and nut.remaining_before == left


def test_exactly_at_the_ceiling_fits_and_one_paisa_more_does_not():
    book = CeilingBook(MASTER.contracts)  # RC-2026-015: ITM-1014 at 20.64, so 3 units are 61.92
    book.consumed["RC-2026-015"] = Decimal("500000") - Decimal("61.92")  # exactly enough room ("<=")
    assert choose("ITM-1014", date(2026, 11, 2), 3, book=book).chosen.contract.contract_id == "RC-2026-015"
    book.consumed["RC-2026-015"] = Decimal("500000") - Decimal("61.91")  # one paisa short
    assert choose("ITM-1014", date(2026, 11, 2), 3, book=book).chosen is None


def test_same_rate_tie_goes_to_the_contract_ending_first_then_id():
    twin = lambda cid, end: Contract(cid, "S001", "Bhosari Steel Traders", date(2026, 1, 1), end, Decimal("1000000"),
                                     Decimal("0"), None, "manual", (ContractLine("ITM-1002", "MS sheet", "NOS", Decimal("9000")),))
    master = dataclasses.replace(MASTER, contracts=(*MASTER.contracts, twin("RC-X-2", date(2027, 6, 30)),
                                                    twin("RC-X-1", date(2027, 12, 31)), twin("RC-X-0", date(2027, 6, 30))))
    assert ids(choose("ITM-1002", date(2026, 11, 4), 15, master=master))[:3] == ["RC-X-0", "RC-X-2", "RC-X-1"]


def test_statuses_and_validity_are_policy_data():
    params = copy.deepcopy(PARAMS)
    params["suppliers"]["allowed_statuses"]["hold_applicable_contract"] = ["Active", "Blocked"]
    assert [c.contract_id for c, _ in applicable_contracts("ITM-1006", date(2026, 11, 2), MASTER, params)] == ["RC-2026-005"]
    params["contracts"]["validity"]["start_inclusive"] = False
    assert ids(choose("ITM-1039", date(2026, 11, 15), 1, params=params)) == []


def test_money_rounds_half_up_to_paise():
    assert (money(Decimal("0.005")), money(Decimal("0.015")), money(Decimal("2.675"))) == (
        Decimal("0.01"), Decimal("0.02"), Decimal("2.68"))
