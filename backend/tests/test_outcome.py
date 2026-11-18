"""F4: requirement facts, the policy's ordered rules, and the outcome (supplier, price or suggestions)."""
import copy
import dataclasses

import pytest

from engine.clubbing import club
from engine.contracts import CeilingBook, choose_contract
from engine.facts import REQUIREMENT_SCOPE
from engine.outcome import apply_outcome
from engine.policy import decide as run_rules
from engine.preferred import preferred_list
from engine.requirement_facts import requirement_facts
from engine.validation import check_lines
from engine.valuation import value_requirement
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
LINES = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")


REQS = club(check_lines(LINES, MASTER), MASTER)


def decided(pr_no, master=MASTER):
    """Rules and outcome for the requirement holding pr_no (fresh ceiling book: no earlier consumption)."""
    reqs = REQS if master is MASTER else club(check_lines(LINES, master), master)
    req = next(r for r in reqs if any(c.line.pr_no == pr_no for c in r.lines))
    choice = None if req.is_new else choose_contract(req.item_code, req.requirement_date, req.total_quantity,
                                                     master, req.params, CeilingBook(master.contracts))
    valuation = value_requirement(req, choice, master, req.params)
    preferred = () if req.is_new else preferred_list(req.item_code, req.requirement_date, master, req.params)
    facts = requirement_facts(req, choice, valuation, preferred, master, req.params)
    line = {"line": req.first.facts["line"], "item": req.first.facts["item"]}
    skip = []
    while True:
        rule, _, _ = run_rules(req.version.document, facts, line, skip)
        outcome = apply_outcome(rule, req, choice, preferred, master, req.params)
        if outcome:
            return outcome, facts, skip
        skip.append(rule["id"])


@pytest.mark.parametrize("pr_no, route, supplier, price, suggestions", [
    ("PR-26-00019", "CONTRACT_PO", "S001", "9168.71", ()),                           # Ex 1
    ("PR-26-00146", "SPOT_PO", "S024", "166.41", ()),                                # Ex 5
    ("PR-26-00106", "SPOT_PO", "S027", "21.59", ()),                                 # Ex 6 PUN1 line
    ("PR-26-00088", "SPOT_PO", "S023", "391.82", ()),                                # Ex 7
    ("PR-26-00059", "EMERGENCY_PO", "S014", "106.38", ()),                           # Ex 8
    ("PR-26-00004", "RFQ", None, None, ("S014", "S013", "S016")),                    # Ex 3
    ("PR-26-00089", "RFQ", None, None, ("S043", "S044", "S042")),                    # Ex 9
    ("PR-26-00050", "RFQ", None, None, ("S003", "S002", "S005")),                    # Ex 10
    ("PR-26-00100", "RFP", None, None, ("S020", "S017", "S019", "S018")),            # Ex 11: 4 of 5 (D9)
    ("PR-26-00047", "CAPEX_SOURCING", None, None, ("S045", "S047", "S020", "S048", "S046")),  # Ex 12
    ("PR-26-00170", "NEW_ITEM_SOURCING", None, None, ()),                            # Ex 13
])
def test_outcomes_of_the_worked_examples(pr_no, route, supplier, price, suggestions):
    o, _, _ = decided(pr_no)
    assert (o.route, o.supplier_id, None if o.unit_price is None else str(o.unit_price), o.suggestions) == (
        route, supplier, price, suggestions)


def test_only_a_contract_po_draws_on_a_contract():
    assert decided("PR-26-00019")[0].uses_contract.contract.contract_id == "RC-2025-011"
    assert decided("PR-26-00004")[0].uses_contract is None  # RC-2026-002 applies but the RFQ does not use it
    assert decided("PR-26-00047")[0].uses_contract is None  # Capex decided by 5.1 before 5.2


def test_the_facts_are_exactly_the_fact_catalogue():
    _, facts, _ = decided("PR-26-00019")
    paths = set()

    def walk(value, prefix):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{prefix}{k}.")
        elif isinstance(value, list) and prefix == "lines.":
            for v in value:
                walk(v, "lines[].")
        else:
            paths.add(prefix[:-1])
    walk(facts, "")
    assert {p for p in paths if p not in REQUIREMENT_SCOPE} == set()  # nothing the catalogue does not list
    missing = {p for p in REQUIREMENT_SCOPE if p not in paths and p != "lines"}
    assert missing == set()


def test_a_po_rule_without_an_eligible_supplier_is_skipped_and_the_next_rule_decides():
    doc = copy.deepcopy(MASTER.policies[0].document)
    doc["parameters"]["suppliers"]["allowed_statuses"]["receive_po"] = []  # nobody may receive a PO
    master = dataclasses.replace(MASTER, policies=(dataclasses.replace(MASTER.policies[0], document=doc),))
    o, _, skip = decided("PR-26-00146", master)  # Ex 5 would be a spot PO
    assert (skip, o.route) == (["5.4"], "RFQ")


def test_suggestions_never_include_a_supplier_whose_status_is_not_allowed():
    for pr_no in ("PR-26-00050", "PR-26-00004", "PR-26-00089"):
        o, _, _ = decided(pr_no)
        assert all(MASTER.suppliers[s].status == "Active" for s in o.suggestions)
    assert "S004" not in decided("PR-26-00050")[0].suggestions  # Blocked, though it lists Steel & Metals
