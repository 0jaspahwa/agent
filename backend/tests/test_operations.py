"""D33: change operations applied to the base policy (pure)."""
import copy

import pytest

from amendments.operations import OperationError, apply_operations, parse_path
from engine.policy import load_policy
from engine.policy_check import validate

BASE = load_policy("5.0")
NEW_RULE = {"id": "5.3C", "title": "Office and IT", "when": {"==": [{"var": "item.category"}, "Office & IT"]},
            "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none",
                     "suggest_count": 3}}


def ids(doc, section="rules", key="id"):
    return [x[key] for x in doc[section]]


def test_the_base_is_never_changed():
    before = copy.deepcopy(BASE)
    apply_operations(BASE, [{"op": "set", "path": "parameters.limits.spot_po.value", "value": 1}])
    assert BASE == before


def test_set_changes_a_parameter_and_a_rule_field():
    doc = apply_operations(BASE, [{"op": "set", "path": "parameters.limits.spot_po.value", "value": 150000},
                                  {"op": "set", "path": "rules[5.5].then.suggest_count", "value": 4}])
    assert doc["parameters"]["limits"]["spot_po"]["value"] == 150000
    assert next(r for r in doc["rules"] if r["id"] == "5.5")["then"]["suggest_count"] == 4


def test_a_rule_is_added_before_or_after_a_named_rule():
    after = apply_operations(BASE, [{"op": "add", "section": "rules", "item": NEW_RULE, "after": "5.3"}])
    assert ids(after) == ["1.2", "5.1", "5.2", "5.3", "5.3C", "5.4", "5.5", "5.6"]
    before = apply_operations(BASE, [{"op": "add", "section": "rules", "item": NEW_RULE, "before": "5.4"}])
    assert ids(before) == ids(after)
    assert validate(after, None)[0] == []


def test_operations_are_applied_in_order():
    ops = [{"op": "add", "section": "rules", "item": NEW_RULE, "after": "5.3"},
           {"op": "set", "path": "rules[5.3C].then.suggest_count", "value": 5}]
    doc = apply_operations(BASE, ops)
    assert next(r for r in doc["rules"] if r["id"] == "5.3C")["then"]["suggest_count"] == 5
    with pytest.raises(OperationError, match="Operation 1 .*no rule '5.3C'"):
        apply_operations(BASE, list(reversed(ops)))


def test_replace_and_remove():
    replaced = dict(NEW_RULE, id="5.4", title="Spot PO (amended)")
    doc = apply_operations(BASE, [{"op": "replace", "section": "rules", "id": "5.4", "item": replaced}])
    assert next(r for r in doc["rules"] if r["id"] == "5.4")["title"] == "Spot PO (amended)"
    assert ids(doc) == ids(BASE)  # same position
    doc = apply_operations(BASE, [{"op": "remove", "section": "line_flags", "id": "F7"}])
    assert "F7" not in ids(doc, "line_flags")


def test_overrides_derived_facts_checks_and_lists():
    ops = [{"op": "add", "section": "overrides", "item": {"id": "OV-1", "parameter": "limits.emergency_po",
                                                          "when": {"==": [{"var": "line.plant"}, "CHK1"]},
                                                          "set": {"value": 200000}}},
           {"op": "add", "section": "derived_facts", "item": {"name": "has_tool_room_line", "expr": {
               "some": [{"var": "lines"}, {"==": [{"var": "department"}, "Tool Room"]}]}}},
           {"op": "replace", "section": "derived_facts", "id": "has_tool_room_line", "item": {"expr": {
               "some": [{"var": "lines"}, {"==": [{"var": "department"}, "Tool Room"]}]}, "description": "x"}},
           {"op": "list_add", "path": "parameters.matching.noise_phrases", "values": ["as discussed"]},
           {"op": "list_remove", "path": "parameters.matching.noise_phrases", "values": ["as discussed"]},
           {"op": "add_parameter", "path": "parameters.limits.price_variance", "value": {"value": 15, "operator": ">"}}]
    doc = apply_operations(BASE, ops)
    assert ids(doc, "overrides") == ["OV-1"] and "has_tool_room_line" in ids(doc, "derived_facts", "name")
    assert doc["parameters"]["matching"]["noise_phrases"] == BASE["parameters"]["matching"]["noise_phrases"]
    assert doc["parameters"]["limits"]["price_variance"]["value"] == 15
    assert validate(doc, None)[0] == []


@pytest.mark.parametrize("op,message", [
    ({"op": "set", "path": "parameters.limits.spot.value", "value": 1}, "no 'spot' in parameters.limits"),
    ({"op": "set", "path": "parameters.limits.spot_po.amount", "value": 1}, "no 'amount'"),
    ({"op": "set", "path": "rules[9.9].then.route", "value": "RFQ"}, "there is no rule '9.9'"),
    ({"op": "set", "path": "version", "value": "6.0"}, "must start with 'parameters.'"),
    ({"op": "set", "path": "rules[5.4]", "value": {}}, "use 'replace'"),
    ({"op": "add", "section": "rules", "item": NEW_RULE}, "needs 'before' or 'after'"),
    ({"op": "add", "section": "rules", "item": NEW_RULE, "after": "5.9"}, "no rule '5.9' to place it after"),
    ({"op": "add", "section": "rules", "item": dict(NEW_RULE, id="5.4"), "after": "5.3"}, "already exists"),
    ({"op": "replace", "section": "rules", "id": "5.9", "item": NEW_RULE}, "there is no rule '5.9'"),
    ({"op": "replace", "section": "rules", "id": "5.4", "item": NEW_RULE}, "cannot rename"),
    ({"op": "remove", "section": "overrides", "id": "OV-9"}, "there is no override 'OV-9'"),
    ({"op": "remove", "section": "derived_facts", "id": "is_emergency"}, "cannot be removed"),
    ({"op": "list_remove", "path": "parameters.matching.noise_phrases", "values": ["nope"]}, "is not in"),
    ({"op": "list_add", "path": "parameters.limits.spot_po.value", "values": [1]}, "is not a list"),
    ({"op": "add_parameter", "path": "parameters.limits.spot_po", "value": {}}, "already exists"),
    ({"op": "add", "section": "rulez", "item": NEW_RULE}, "'section' must be one of"),
    ({"op": "rename"}, "unknown operation 'rename'"),
])
def test_a_bad_operation_is_rejected_with_a_plain_message(op, message):
    with pytest.raises(OperationError, match=message) as exc:
        apply_operations(BASE, [{"op": "set", "path": "parameters.limits.rfq.value", "value": 900000}, op])
    assert str(exc.value).startswith("Operation 2 (")


def test_paths_with_dotted_ids():
    assert parse_path("rules[5.3A].then.route") == [("rules", "5.3A"), ("then", None), ("route", None)]
    for bad in ("", "rules[5.3", "a..b", "a.", ".a"):
        with pytest.raises(OperationError):
            parse_path(bad)
