"""D3 and D8: the history windows' edges, on a real PO (ITM-1028's latest, 7300167 on 2026-10-14)."""
from datetime import date

import pytest

from engine.history import in_window, valuation_po
from engine.policy import load_policy
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
PARAMS = load_policy("5.0")["parameters"]
PO_DATE = date(2026, 10, 14)


@pytest.mark.parametrize("on,inside", [
    (date(2026, 10, 14), False),  # the requirement date itself: not "before" it (D3)
    (date(2026, 10, 15), True),   # the next day
    (date(2027, 10, 14), True),   # exactly 365 days later: the far end counts (D8)
    (date(2027, 10, 15), False),  # 366 days later
])
def test_the_365_day_window_edges(on, inside):
    assert in_window(PO_DATE, on, PARAMS["history"]["valuation_window"]) is inside
    po = valuation_po("ITM-1028", on, MASTER, PARAMS)
    assert (po is not None and po.po_number == "7300167") is inside


def test_the_548_day_window_has_the_same_shape():
    window = PARAMS["history"]["preferred_window"]
    assert in_window(PO_DATE, date(2028, 4, 14), window)  # 548 days
    assert not in_window(PO_DATE, date(2028, 4, 15), window)  # 549 days
    assert not in_window(PO_DATE, PO_DATE, window)
