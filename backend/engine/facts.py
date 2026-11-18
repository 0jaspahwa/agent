"""The fact catalogue: every field a policy expression may read, with its type.

The engine promises to supply these fields; policy_check.validate rejects a policy that reads anything
else (a typo or an invented field), so unknown names are caught before approval, never in a batch run.
A type ending in "?" may be missing (None) on a given line or requirement; comparisons on it are then
False and the evaluator reports the path (see logic.py). docs/policy_schema.md section 8 mirrors this.
"""

# Raw columns, exactly as in the kit files.
PR_LINE = {
    "pr_no": "string", "pr_line": "integer", "created_at": "datetime", "requester": "string?",
    "department": "string?", "plant": "string", "item_code": "string?", "description": "string",
    "quantity": "number", "uom": "string?", "estimated_unit_price": "number?", "need_by_date": "date?",
    "urgency": "string?",
    "source": "string",  # batch | chat (where the line came from; not a CSV column)
}
ITEM = {"item_code": "string", "description": "string", "uom": "string", "category": "string",
        "item_type": "string", "standard_price": "number"}
SUPPLIER = {"supplier_id": "string", "name": "string", "city": "string", "categories": "string",
            "status": "string", "on_time_pct": "number", "quality_rating": "number"}
PLANT = {"plant": "string", "name": "string"}
CONTRACT = {"contract_id": "string", "supplier_id": "string", "supplier_name": "string",
            "start_date": "date", "end_date": "date", "value_cap": "number", "consumed_value": "number",
            "rate": "number"}  # register columns plus the contract line's rate for this item

# Facts the engine computes for a requirement (after clubbing, contract selection and valuation).
REQUIREMENT = {
    "requirement.id": "string", "requirement.date": "date", "requirement.created_at": "datetime",
    "requirement.plant": "string", "requirement.item_code": "string", "requirement.is_new_item": "boolean",
    "requirement.total_quantity": "number", "requirement.line_count": "integer",
    "requirement.distinct_requesters": "integer", "requirement.distinct_departments": "integer",
    "requirement.lead_time_days": "integer?",  # first line's need-by date minus requirement date
    "requirement.value_inr": "number?",  # missing only for a new item with no estimated price
    "requirement.valuation_price": "number?", "requirement.valuation_source": "string?",
    "contract.usable": "boolean", "contract.any_applicable": "boolean",
    "contract.remaining_ceiling": "number?",  # ceiling left on the contract that would be used, before it
    "contract.lowest_applicable_rate": "number?",
    "history.bought_from_active": "boolean",  # purchase window, allowed statuses only (5.3, 5.4)
    "history.po_count": "integer",  # POs for the item in the purchase window, any supplier
    "history.active_po_count": "integer",
    "history.distinct_active_suppliers": "integer",
    "history.days_since_last_po": "integer?",  # requirement date minus latest PO date, any supplier
    "history.latest_po_price": "number?", "history.latest_po_number": "string?",
    "history.latest_po_date": "date?", "history.latest_po_supplier_id": "string?",  # valuation window
    "preferred.list_size": "integer", "preferred.rank1.reference_price": "number?",
    "lines": "list",
}


def _prefixed(prefix, columns, nullable=False):
    return {prefix + name: (kind if kind.endswith("?") or not nullable else kind + "?")
            for name, kind in columns.items()}


# Which facts exist depends on the stage of the pipeline (docs/policy_schema.md section 8):
#   line_check   - one PR line after item matching: the line, its matched item, its plant, match details
#   override     - while clubbing, before any requirement exists: the (first) line and its matched item
#   requirement  - rules and derived facts, after clubbing, contracts and valuation: everything
# Line facts carry canonical values: plant and item_code upper case, uom upper case without punctuation,
# urgency mapped through intake.urgency_values (blank or unknown -> intake.default_urgency).
LINE_COMPUTED = {
    "is_duplicate": "boolean",              # an earlier line in the batch has the same pr_no and pr_line
    "uom_mismatch": "boolean",              # both units present and different after canonicalising
    "urgency_recognised": "boolean",        # the urgency cell was one of intake.urgency_values
    "description_says_urgent": "boolean",   # the description contains one of intake.urgency_words
    "possible_duplicate": "boolean",        # same requester, item, plant, quantity, need-by within the window
    "possible_duplicate_of": "string?",     # the other line(s), e.g. "PR-26-00175/1"
}
MATCH = {  # how the line's item was resolved (engine/matching.py)
    "status": "string",                     # code | description | new | ambiguous
    "score": "number?",                     # description match score, 0..1
    "item_code_unknown": "boolean",         # a code was given but is not in the item master
    "description_disagrees": "boolean",     # a valid code was given but the description clearly names another item
}
_LINE = _prefixed("line.", {**PR_LINE, "quantity": "number?", "plant": "string?", "created_at": "datetime?",
                            **LINE_COMPUTED})
LINE_CHECK_SCOPE = {
    **_LINE,
    **_prefixed("item.", ITEM, nullable=True),    # the matched item; missing for a new item
    **_prefixed("plant.", PLANT, nullable=True),  # missing when the plant is not in the plant master
    **_prefixed("match.", MATCH),
}
OVERRIDE_SCOPE = {
    **_LINE,
    **_prefixed("item.", ITEM, nullable=True),    # the matched item; missing for a new item
}
REQUIREMENT_SCOPE = {
    **REQUIREMENT,
    **_prefixed("first_line.", {**PR_LINE, **LINE_COMPUTED}), **_prefixed("lines[].", {**PR_LINE, **LINE_COMPUTED}),
    **_prefixed("item.", ITEM, nullable=True),  # no item for a new item
    **_prefixed("plant.", PLANT),
    **_prefixed("contract.", CONTRACT, nullable=True), **_prefixed("contract.supplier.", SUPPLIER, nullable=True),
    **_prefixed("preferred.rank1.", SUPPLIER, nullable=True),
}
SCOPES = {"line_check": LINE_CHECK_SCOPE, "override": OVERRIDE_SCOPE, "requirement": REQUIREMENT_SCOPE}
# Fields computed from the policy itself: derived facts (rules only) and parameters (not in overrides,
# because overrides are what produce the parameter values).
DYNAMIC_PREFIXES = {"line_check": ("params.",), "override": (), "requirement": ("derived.", "params.")}
