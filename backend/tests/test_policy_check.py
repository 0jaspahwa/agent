"""Tests for the policy validator (backend/engine/policy_check.py) and parameter overrides."""
import copy

import pytest

from engine.policy import load_policy, resolve_parameters
from engine.policy_check import collect, validate

V5 = load_policy("5.0")


def amended(change):
    policy = copy.deepcopy(V5)
    policy.update(version="5.1", supersedes="5.0", effective_from="2026-12-01")
    change(policy)
    return policy


def rule(policy, rule_id):
    return next(r for r in policy["rules"] if r["id"] == rule_id)


def test_v5_is_valid():
    assert validate(V5) == ([], [])


def test_unknown_field_is_caught_before_approval():
    def typo(p):
        rule(p, "5.3")["when"]["and"][0] = {"==": [{"var": "derived.is_emergancy"}, True]}
        rule(p, "5.4")["when"]["and"][1] = {"==": [{"var": "history.bought_from_actve"}, True]}
    errors, _ = validate(amended(typo), V5)
    assert any("derived.is_emergancy" in e for e in errors)
    assert any("unknown field 'history.bought_from_actve'" in e for e in errors)


def test_line_level_fields_are_not_readable_in_rules():
    def wrong_scope(p):
        rule(p, "5.5")["when"] = {"==": [{"var": "line.plant"}, "CHK1"]}  # rules see first_line.*, not line.*
    errors, _ = validate(amended(wrong_scope), V5)
    assert any("'line.plant' is not available at the requirement stage" in e for e in errors)


# --- Which facts exist at each stage (policy_schema.md section 8). The Gemini drafts used all three
# spellings of the plant; each is valid at its own stage.
def with_override(when):
    return lambda p: p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_po", "when": when,
                                            "set": {"value": 100000}})


def with_line_check(when):
    return lambda p: p["line_checks"].append({"id": "V9", "title": "t", "when": when, "reason": "r"})


def eq(path, value="CHK1"):
    return {"==": [{"var": path}, value]}


@pytest.mark.parametrize("change", [
    with_override(eq("line.plant")),                       # overrides: the line ...
    with_override(eq("item.category", "Lubricants")),      # ... and its matched item
    with_line_check(eq("line.plant")),                     # line checks: the line ...
    with_line_check({"!": {"var": "plant.plant"}}),        # ... and master data (plant, item)
    with_line_check(eq("item.item_type", "Capex")),
    lambda p: rule(p, "5.5").update(                       # rules see every spelling of the plant
        when={"and": [eq("requirement.plant"), eq("plant.plant"), eq("first_line.plant")]}),
])
def test_facts_available_at_their_stage_are_accepted(change):
    assert validate(amended(change), V5) == ([], [])


@pytest.mark.parametrize("change, path, stage", [
    (with_override(eq("plant.plant")), "plant.plant", "override"),                  # plant master: not yet
    (with_override(eq("requirement.plant")), "requirement.plant", "override"),      # no requirement yet
    (with_override({"<": [{"var": "requirement.value_inr"}, 5]}), "requirement.value_inr", "override"),
    (with_override({"<": [5, {"var": "params.limits.rfq.value"}]}), "params.limits.rfq.value", "override"),
    (with_override(eq("derived.is_emergency", True)), "derived.is_emergency", "override"),
    (with_line_check({"<": [{"var": "requirement.value_inr"}, 5]}), "requirement.value_inr", "line_check"),
    (with_line_check(eq("contract.usable", True)), "contract.usable", "line_check"),
    (with_line_check(eq("first_line.plant")), "first_line.plant", "line_check"),
])
def test_facts_not_available_at_a_stage_are_rejected(change, path, stage):
    errors, _ = validate(amended(change), V5)
    assert any(f"'{path}' is not available at the {stage} stage" in e for e in errors), errors


def test_invented_field_is_still_reported_as_unknown():
    errors, _ = validate(amended(with_override(eq("line.colour", "red"))), V5)
    assert any("unknown field 'line.colour'" in e for e in errors)


def test_override_evaluation_cannot_see_plant_master_or_params():
    # Even if a caller passes more, resolve_parameters only exposes line and item to an override.
    policy = amended(lambda p: p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_po",
                                                      "when": {"!": {"var": "plant.plant"}},
                                                      "set": {"value": 1}}))
    params = resolve_parameters(policy, {"line": {"plant": "CHK1"}, "plant": {"plant": "CHK1"}, "item": None})
    assert params["limits"]["spot_po"]["value"] == 1  # plant.plant was not visible, so "not plant" held


@pytest.mark.parametrize("change, fragment", [
    (lambda p: rule(p, "5.4")["when"].update({"and": [{"between": [1, 2, 3]}]}), "unknown operator 'between'"),
    (lambda p: rule(p, "5.5").update(when={"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfx"]}),
     "not a limit parameter"),
    (lambda p: rule(p, "5.6")["then"].update(route="RFI"), "then.route"),
    (lambda p: rule(p, "5.4")["then"].update(suggest_count=3), "suggest_count"),
    (lambda p: rule(p, "5.5")["then"].update(supplier="preferred_rank_1"), "then.supplier"),
    (lambda p: p["rules"].append(copy.deepcopy(rule(p, "5.6"))), "duplicate id '5.6'"),
    (lambda p: p["parameters"]["limits"]["spot_po"].update(operator="less than"), "limits.spot_po"),
    (lambda p: p["parameters"]["clubbing"]["need_by_window"].update(inclusive="yes"), "inclusive"),
    (lambda p: p["parameters"]["clubbing"].update(match_on=["item_code", "colour"]), "clubbing.match_on"),
    (lambda p: p["parameters"]["suppliers"]["allowed_statuses"].update(receive_po=["Active", "Gold"]),
     "allowed_statuses.receive_po"),
    (lambda p: p["parameters"]["valuation"].update(price_sources=["guess"]), "price_sources"),
    (lambda p: p["parameters"]["matching"].update(match_threshold=60), "match_threshold"),
    (lambda p: p["line_flags"][0].update(message="see {line.colour}"), "names '{line.colour}'"),
    (lambda p: p["parameters"]["ranking"]["preferred_score"]["weights"].pop("recency"), "preferred_score.weights"),
    (lambda p: p["parameters"]["ranking"]["preferred_score"]["weights"].update(recency=-1), "preferred_score.weights"),
    (lambda p: p["parameters"]["matching"].update(abbreviations=["brg"]), "abbreviations"),
    (lambda p: p["parameters"]["matching"].pop("min_word_coverage"), "matching.min_word_coverage"),
    (lambda p: p["parameters"]["intake"].update(default_urgency="Soon"), "default_urgency"),
    (lambda p: p.update(effective_from="1 Dec 2026"), "effective_from"),
    (lambda p: p.update(supersedes="4.0"), "supersedes"),
    (lambda p: p.update(notes="hello"), "unknown key 'notes'"),
    (lambda p: p["derived_facts"].insert(0, {"name": "x", "expr": {"var": "derived.is_emergency"}}),
     "not defined before it is used"),
    (lambda p: p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_limit",
                                      "when": True, "set": {"value": 1}}), "does not exist"),
    (lambda p: p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_po",
                                      "when": True, "set": {"value": "1 lakh"}}), "same type"),
    (lambda p: p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_po",
                                      "when": {"==": [{"var": "requirement.plant"}, "CHK1"]},
                                      "set": {"value": 1}}), "'requirement.plant' is not available at the override stage"),
])
def test_invalid_policies_are_rejected(change, fragment):
    errors, _ = validate(amended(change), V5)
    assert any(fragment in e for e in errors), errors


CHK1_SPOT = {"id": "OV-1", "parameter": "limits.spot_po",
             "when": {"==": [{"var": "line.plant"}, "CHK1"]}, "set": {"value": 100000}}


def test_plant_override_is_valid_and_applies_only_to_that_plant():
    policy = amended(lambda p: p["overrides"].append(copy.deepcopy(CHK1_SPOT)))
    assert validate(policy, V5) == ([], [])
    chk1 = resolve_parameters(policy, {"line": {"plant": "CHK1"}})
    pun1 = resolve_parameters(policy, {"line": {"plant": "PUN1"}})
    assert chk1["limits"]["spot_po"] == {**V5["parameters"]["limits"]["spot_po"], "value": 100000}
    assert pun1["limits"]["spot_po"] == V5["parameters"]["limits"]["spot_po"]
    assert policy["parameters"]["limits"]["spot_po"]["value"] == 200000  # the document itself is untouched


def test_first_matching_override_wins():
    second = {**CHK1_SPOT, "id": "OV-2", "set": {"value": 50000}}
    policy = amended(lambda p: p["overrides"].extend([copy.deepcopy(CHK1_SPOT), second]))
    assert resolve_parameters(policy, {"line": {"plant": "CHK1"}})["limits"]["spot_po"]["value"] == 100000


def test_rules_after_an_always_true_rule_are_flagged():
    _, warnings = validate(amended(lambda p: rule(p, "5.4").update(when=True)), V5)
    assert any("5.4" in w and "never apply" in w for w in warnings)


def test_collect_reports_operators_and_paths():
    expr = {"and": [{"some": [{"var": "lines"}, {"==": [{"var": "urgency"}, "Emergency"]}]},
                    {"meets_limit": [{"var": "requirement.value_inr"}, "limits.emergency_po"]}]}
    ops, paths = collect(expr)
    assert ops == {"and", "some", "var", "==", "meets_limit"}
    assert paths == {"lines", "lines[].urgency", "requirement.value_inr"}
