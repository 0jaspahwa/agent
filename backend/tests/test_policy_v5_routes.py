"""Proves the policy format can express v5.0: evaluating v5.0.json's rules in order on hand-built facts
gives the worked examples' routes. This is NOT the engine: here the facts (value, contract usable, bought
from an Active supplier) are typed in from Worked_Examples.pdf instead of being computed."""
import pytest

from engine.logic import evaluate
from engine.policy import decide, load_policy

POLICY = load_policy("5.0")


def first_matching_rule(policy, facts):
    rule, _data, _missing = decide(policy, facts, facts["_line_facts"])
    return rule


def facts(item, plant, urgencies, value, contract_usable, bought_from_active, new_item=False):
    lines = [{"plant": plant, "urgency": u, "quantity": 1} for u in urgencies]
    return {
        "requirement": {"value_inr": value, "is_new_item": new_item, "plant": plant},
        "first_line": lines[0],
        "lines": lines,
        "item": item,
        "plant": {"plant": plant},
        "contract": {"usable": contract_usable},
        "history": {"bought_from_active": bought_from_active},
        "_line_facts": {"line": lines[0], "item": item, "plant": {"plant": plant}},  # for overrides
    }


def item(code, description, category, item_type="Material"):
    return {"item_code": code, "description": description, "category": category, "item_type": item_type}


# (example, facts, expected rule id, route, suggestions) -- values and flags from Worked_Examples.pdf
WORKED = [
    ("Ex 1 contract PO",
     facts(item("ITM-1002", "MS sheet 3mm 1250x2500", "Steel & Metals"), "PUN1", ["Normal"], 137531,
           contract_usable=True, bought_from_active=True), "5.2", "CONTRACT_PO", 0),
    ("Ex 5 clubbed spot PO",
     facts(item("ITM-1038", "Hydraulic oil HLP 68", "Hydraulics & Pneumatics"), "CHK1",
           ["Normal", "Normal", "Normal"], 126472, contract_usable=False, bought_from_active=True),
     "5.4", "SPOT_PO", 0),
    ("Ex 8 emergency PO above the spot limit",
     facts(item("ITM-1026", "Gearbox oil seal 45x62x8", "Bearings & Transmission"), "PUN1", ["Emergency"],
           253184, contract_usable=False, bought_from_active=True), "5.3", "EMERGENCY_PO", 0),
    ("Ex 10 small but never bought (blocked supplier's contract unusable)",
     facts(item("ITM-1006", "Aluminium plate 6061 10mm", "Steel & Metals"), "PUN1", ["Normal"], 80300,
           contract_usable=False, bought_from_active=False), "5.5", "RFQ", 3),
    ("Ex 11 RFP",
     facts(item("ITM-1034", "Encoder for CNC spindle (Vertex)", "Electrical Spares"), "CHK1", ["Normal"],
           2070780, contract_usable=False, bought_from_active=True), "5.6", "RFP", 5),
    ("Ex 12 Capex before contracts and limits",
     facts(item("ITM-1071", "EOT crane 5 ton", "Capital Equipment", "Capex"), "PUN1", ["Normal"], 6036704,
           contract_usable=False, bought_from_active=True), "5.1", "CAPEX_SOURCING", 5),
]


@pytest.mark.parametrize("name, example_facts, rule_id, route, suggest", WORKED, ids=[w[0] for w in WORKED])
def test_worked_example_routes(name, example_facts, rule_id, route, suggest):
    rule = first_matching_rule(POLICY, example_facts)
    assert (rule["id"], rule["then"]["route"], rule["then"]["suggest_count"]) == (rule_id, route, suggest)


SEAL = item("ITM-1026", "Gearbox oil seal 45x62x8", "Bearings & Transmission")


# Synthetic cases on the limit boundaries (D10: emergency "<=", spot and RFQ "<").
@pytest.mark.parametrize("urgency, value, bought, route", [
    ("Emergency", 500000, True, "EMERGENCY_PO"),   # exactly 5 lakh is allowed
    ("Emergency", 500001, True, "RFQ"),            # just above: falls through 5.4 to 5.5
    ("Emergency", 150000, False, "RFQ"),           # emergency with no history fails 5.3 and 5.4
    ("Normal", 199999, True, "SPOT_PO"),
    ("Normal", 200000, True, "RFQ"),               # "below 2,00,000": exactly 2 lakh needs quotes
    ("Normal", 999999, True, "RFQ"),
    ("Normal", 1000000, True, "RFP"),              # "10,00,000 or more"
])
def test_limit_boundaries(urgency, value, bought, route):
    f = facts(SEAL, "PUN1", [urgency], value, contract_usable=False, bought_from_active=bought)
    assert first_matching_rule(POLICY, f)["then"]["route"] == route


def test_one_emergency_line_makes_the_requirement_an_emergency():
    f = facts(SEAL, "PUN1", ["Normal", "Emergency"], 300000, contract_usable=False, bought_from_active=True)
    assert first_matching_rule(POLICY, f)["id"] == "5.3"


def test_contract_beats_emergency_and_limits():
    f = facts(SEAL, "PUN1", ["Emergency"], 5000000, contract_usable=True, bought_from_active=True)
    assert first_matching_rule(POLICY, f)["then"]["route"] == "CONTRACT_PO"


def test_capex_is_checked_before_contracts():
    # Ex 12: "checked before contracts and value limits". A usable contract must not win over 5.1.
    crane = item("ITM-1071", "EOT crane 5 ton", "Capital Equipment", "Capex")
    f = facts(crane, "PUN1", ["Normal"], 6036704, contract_usable=True, bought_from_active=True)
    assert first_matching_rule(POLICY, f)["then"]["route"] == "CAPEX_SOURCING"


def test_new_item_goes_to_sourcing_without_suggestions():
    f = facts(None, "PUN1", ["Normal"], 141100, contract_usable=False, bought_from_active=False, new_item=True)
    rule = first_matching_rule(POLICY, f)
    assert (rule["then"]["route"], rule["then"]["suggest_count"]) == ("NEW_ITEM_SOURCING", 0)

# Line checks and flags are tested on real lines in test_validation.py.
