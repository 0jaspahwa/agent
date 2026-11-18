"""F5: PO consolidation (policy 7) from the consolidation parameters."""
import json
from datetime import datetime, timedelta

import pytest

from engine.consolidation import Entry, consolidate
from engine.policy import POLICY_DIR

PARAMS = json.loads((POLICY_DIR / "v5.0.json").read_text(encoding="utf-8"))["parameters"]["consolidation"]
T0 = datetime(2026, 11, 10, 9, 0)


def entry(gid, at, supplier="S007", plant="PUN1", route="CONTRACT_PO", params=PARAMS):
    return Entry(gid, at, {"supplier_id": supplier, "plant": plant, "route": route, "decision": "PO"}, params)


def pos(*entries):
    return [(po.po_id, po.group_ids) for po in consolidate(entries)]


@pytest.mark.parametrize("gap, together", [
    (timedelta(hours=24), True),                   # exactly 24 h 00 m joins (D6)
    (timedelta(hours=24, minutes=1), False),       # 24 h 01 m does not
    (timedelta(hours=20, minutes=25), True),       # Ex 14's two hex bolt requirements
])
def test_the_24_hour_window(gap, together):
    result = pos(entry("R-1", T0), entry("R-2", T0 + gap))
    assert result == ([("PO-0001", ["R-1", "R-2"])] if together else [("PO-0001", ["R-1"]), ("PO-0002", ["R-2"])])


def test_the_window_is_measured_from_the_pos_first_requirement_not_the_previous_one():
    result = pos(entry("R-1", T0), entry("R-2", T0 + timedelta(hours=20)), entry("R-3", T0 + timedelta(hours=30)))
    assert result == [("PO-0001", ["R-1", "R-2"]), ("PO-0002", ["R-3"])]


@pytest.mark.parametrize("other", [
    entry("R-2", T0 + timedelta(hours=1), supplier="S006"),
    entry("R-2", T0 + timedelta(hours=1), plant="CHK1"),
    entry("R-2", T0 + timedelta(hours=1), route="SPOT_PO"),
])
def test_supplier_plant_and_route_must_all_match(other):
    assert len(pos(entry("R-1", T0), other)) == 2


def test_joins_the_earliest_open_po_and_numbers_follow_creation_time():
    a, b = entry("R-1", T0, supplier="S001"), entry("R-2", T0 + timedelta(hours=1), supplier="S007")
    c = entry("R-3", T0 + timedelta(hours=2), supplier="S001")
    assert pos(c, b, a) == [("PO-0001", ["R-1", "R-3"]), ("PO-0002", ["R-2"])]  # input order does not matter


def test_the_window_and_key_are_policy_data():
    wider = {**PARAMS, "window": {**PARAMS["window"], "length": 48}}
    assert len(pos(entry("R-1", T0, params=wider), entry("R-2", T0 + timedelta(hours=30), params=wider))) == 1
    by_supplier = {**PARAMS, "match_on": ["supplier_id"]}
    assert len(pos(entry("R-1", T0, params=by_supplier), entry("R-2", T0, plant="CHK1", params=by_supplier))) == 1
