"""Tests for our JSON Logic evaluator (backend/engine/logic.py)."""
from decimal import Decimal

import pytest

from engine.logic import LogicError, evaluate

DATA = {
    "requirement": {"value_inr": 200000, "date": "2026-11-04", "is_new_item": False},
    "first_line": {"created_at": "2026-11-04 13:05", "need_by_date": "2026-11-24", "urgency": "Normal",
                   "estimated_unit_price": None},
    "lines": [{"urgency": "Normal", "quantity": 10}, {"urgency": "Emergency", "quantity": 5}],
    "item": None,  # as for a new item
    "plant": {"plant": "CHK1"},
    "contract": {"usable": False, "rate": None},
    "params": {"limits": {"spot_po": {"value": 200000, "operator": "<"},
                          "emergency_po": {"value": 500000, "operator": "<="}}},
}


@pytest.mark.parametrize("expr, expected", [
    (5, 5),                                                        # literals pass through
    ({"var": "requirement.value_inr"}, 200000),                    # dotted path
    ({"var": "lines.1.urgency"}, "Emergency"),                     # list index in a path
    ({"var": "nope.missing"}, None),                               # missing -> None
    ({"var": ["nope", 7]}, 7),                                     # missing -> default
    ({"==": [{"var": "plant.plant"}, "CHK1"]}, True),
    ({"===": [{"var": "plant.plant"}, "CHK1"]}, True),             # strict alias accepted
    ({"!=": [{"var": "plant.plant"}, "PUN1"]}, True),
    ({"<": [1, 2]}, True), ({"<=": [2, 2]}, True), ({">": [2, 2]}, False), ({">=": [2, 2]}, True),
    ({"<": ["2026-11-01", "2026-11-04"]}, True),                   # ISO dates compare as strings
    ({"!": {"var": "contract.usable"}}, True),                     # single argument without a list
    ({"!!": [{"var": "lines"}]}, True),
    ({"in": [{"var": "plant.plant"}, ["PUN1", "CHK1"]]}, True),
    ({"in": ["x", None]}, False),
    ({"+": [1, 2, 3]}, 6), ({"-": [10, 4]}, 6), ({"-": [3]}, -3), ({"*": [3, 4]}, 12), ({"/": [9, 2]}, 4.5),
    ({"min": [3, 1, 2]}, 1), ({"max": [3, 1, 2]}, 3),
    ({"and": [True, 1, "x"]}, "x"), ({"and": [True, 0, "x"]}, 0), ({"and": []}, True),
    ({"or": [0, "", "y"]}, "y"), ({"or": [0, False]}, False),
    ({"if": [False, "a", True, "b", "c"]}, "b"), ({"if": [False, "a", "c"]}, "c"), ({"if": [False, "a"]}, None),
])
def test_operators(expr, expected):
    assert evaluate(expr, DATA) == expected


def test_and_short_circuits():
    # The second argument would raise (mixed types), but "and" stops at the first false.
    assert evaluate({"and": [False, {"<": ["10", 5]}]}, DATA) is False


def test_arithmetic_is_exact_decimal():
    # In binary floats 100 * 1.15 is 114.99999999999999, which would make "115 > 15% above 100" true.
    assert evaluate({"*": [100, 1.15]}, DATA) == Decimal("115.00")
    assert evaluate({">": [115, {"*": [100, 1.15]}]}, DATA) is False
    assert evaluate({"*": [760, 166.41]}, DATA) == Decimal("126471.60")
    assert evaluate({"/": [1, 3]}, DATA) == Decimal(1) / Decimal(3)
    assert isinstance(evaluate({"var": "f"}, {"f": 0.1}), Decimal)  # a float fact is read as a decimal
    assert evaluate({"+": [{"var": "f"}, 0.2]}, {"f": 0.1}) == Decimal("0.3")


def test_division_by_zero_fails_loudly():
    with pytest.raises(LogicError):
        evaluate({"/": [1, 0]}, DATA)


def test_date_diff_days_uses_whole_calendar_days():
    expr = {"date_diff_days": [{"var": "first_line.need_by_date"}, {"var": "first_line.created_at"}]}
    assert evaluate(expr, DATA) == 20  # 2026-11-24 minus 2026-11-04 (the time of day is ignored)
    assert evaluate({"date_diff_days": ["2026-11-01", "2026-11-04"]}, DATA) == -3


def test_some_all_none_see_each_element_as_data():
    is_emergency = {"==": [{"var": "urgency"}, "Emergency"]}
    assert evaluate({"some": [{"var": "lines"}, is_emergency]}, DATA) is True
    assert evaluate({"all": [{"var": "lines"}, is_emergency]}, DATA) is False
    assert evaluate({"none": [{"var": "lines"}, is_emergency]}, DATA) is False
    assert evaluate({"all": [[], is_emergency]}, DATA) is False      # as in JSON Logic: all of nothing is false
    assert evaluate({"some": [{"var": "nope"}, is_emergency]}, DATA) is False


@pytest.mark.parametrize("value, limit, expected", [
    (199999, "limits.spot_po", True), (200000, "limits.spot_po", False),          # "below": strict
    (500000, "limits.emergency_po", True), (500001, "limits.emergency_po", False),  # "at or below"
])
def test_meets_limit_uses_the_operator_stored_with_the_limit(value, limit, expected):
    assert evaluate({"meets_limit": [value, limit]}, DATA) is expected


# --- A known field with no value: comparisons are False and the field is reported, never an exception.
@pytest.mark.parametrize("expr, reported", [
    ({">": [{"var": "first_line.estimated_unit_price"}, 100]}, ["first_line.estimated_unit_price"]),  # blank cell
    ({"<=": [100, {"var": "first_line.estimated_unit_price"}]}, ["first_line.estimated_unit_price"]),  # either side
    ({"==": [{"var": "item.category"}, "Lubricants"]}, ["item.category"]),        # a new item has no category
    ({"<": [{"var": "contract.rate"}, 5]}, ["contract.rate"]),
    ({"meets_limit": [{"var": "contract.rate"}, "limits.spot_po"]}, ["contract.rate"]),
    ({">": [{"-": [{"var": "contract.rate"}, 1]}, 0]}, ["contract.rate"]),        # arithmetic on missing -> None
    ({">": [{"date_diff_days": [{"var": "first_line.nope"}, "2026-11-01"]}, 3]}, ["first_line.nope"]),
    ({"some": [{"var": "lines"}, {"==": [{"var": "colour"}, "red"]}]}, ["lines[].colour"]),
])
def test_missing_value_makes_comparison_false_and_is_reported(expr, reported):
    missing = []
    assert evaluate(expr, DATA, missing) is False
    assert missing == reported


def test_missing_is_optional_and_defaults_are_not_reported():
    assert evaluate({"<": [{"var": "contract.rate"}, 5]}, DATA) is False  # no list passed: still no error
    missing = []
    assert evaluate({"<": [{"var": ["contract.rate", 0]}, 5]}, DATA, missing) is True
    assert missing == []


def test_negating_a_missing_comparison_gives_true():
    # Documented hazard (policy_schema.md section 7): "not (missing < 1)" is true. Only negate a
    # comparison on a field that cannot be missing at that point in the rule list.
    missing = []
    assert evaluate({"!": {"<": [{"var": "contract.rate"}, 1]}}, DATA, missing) is True
    assert missing == ["contract.rate"]


# --- Malformed expressions and mixed types still raise.
@pytest.mark.parametrize("expr", [
    {"<": ["10", 5]},                              # string vs number
    {"==": [1, 1], "!=": [1, 2]} ,                 # two operator keys
    {">": [True, 0]},                              # booleans are not numbers here
    {"<": [1]},                                    # wrong number of arguments
    {"frobnicate": [1]},                           # unknown operator
    {"meets_limit": [5, "limits.no_such_limit"]},  # unknown limit (the validator catches this earlier)
    {"date_diff_days": ["soon", "2026-11-01"]},    # not a date
    {"+": [1, "a"]},                               # bad arithmetic
])
def test_bad_expressions_raise(expr):
    with pytest.raises(LogicError):
        evaluate(expr, DATA)
