"""Tests for the field-by-field policy diff (backend/engine/policy_diff.py)."""
import copy

from engine.policy import load_policy
from engine.policy_diff import diff

V5 = load_policy("5.0")


def test_identical_policies_have_no_differences():
    assert diff(V5, copy.deepcopy(V5)) == []


def test_limit_change_is_one_field():
    new = copy.deepcopy(V5)
    new["parameters"]["limits"]["spot_po"]["value"] = 150000
    assert diff(V5, new) == [("~", "parameters.limits.spot_po.value", 200000, 150000)]


def test_inserted_rule_is_an_addition_plus_new_order_not_a_change_to_later_rules():
    new = copy.deepcopy(V5)
    new_rule = {"id": "5.3A", "title": "t", "clause_text": "c", "when": True,
                "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest",
                         "price": "none", "suggest_count": 3}}
    new["rules"].insert(4, new_rule)
    changes = diff(V5, new)
    assert {c[1] for c in changes if c[0] == "+"} == {f"rules[5.3A].{f}" for f in ("title", "clause_text", "when", "then")}
    assert [c for c in changes if c[0] == "~"] == [
        ("~", "rule order", ["1.2", "5.1", "5.2", "5.3", "5.4", "5.5", "5.6"],
         ["1.2", "5.1", "5.2", "5.3", "5.3A", "5.4", "5.5", "5.6"])]
