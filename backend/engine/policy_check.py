"""Validate a policy document before it can be approved (hand-written or drafted by the LLM).

validate(policy, previous=None) -> (errors, warnings). Any error blocks approval. The most important
check: every field an expression reads must be in the fact catalogue (engine/facts.py) or be a defined
derived fact or an existing parameter, so a typo or an invented field can never reach a batch run.
"""
import re
from datetime import date
from decimal import Decimal

from engine.facts import DYNAMIC_PREFIXES, ITEM, PR_LINE, SCOPES
from engine.logic import COMPARISONS, OPERATORS, get_path

TOP_KEYS = {"schema_version", "policy_id", "version", "effective_from", "supersedes", "source_document",
            "change_summary", "parameters", "overrides", "derived_facts", "line_checks", "rules"}
OPTIONAL_TOP_KEYS = {"translation_notes", "line_flags"}
ROUTES = {"CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO", "RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING"}
SUPPLIER_BY_DECISION = {"PO": {"contract_supplier", "preferred_rank_1"}, "SOURCING_REQUEST": {"suggest", "none"}}
PRICE_BY_DECISION = {"PO": {"contract_rate", "reference_price"}, "SOURCING_REQUEST": {"none"}}
PRICE_SOURCES = {"contract_to_be_used", "lowest_applicable_contract_rate", "latest_po_in_window", "standard_price"}
STATUSES = {"Active", "Blocked", "Inactive"}
WINDOW_UNITS = {"calendar_days", "hours", "minutes"}
REQUIRED_PARAMS = [
    "limits", "clubbing.creation_window", "clubbing.need_by_window", "clubbing.match_on", "clubbing.order_by",
    "consolidation.window", "consolidation.match_on", "contracts.validity", "contracts.ceiling",
    "contracts.selection", "history.valuation_window", "history.purchase_window", "history.preferred_window",
    "valuation.price_sources", "valuation.include_non_active_suppliers", "valuation.tie_break",
    "valuation.new_item_price", "suppliers.allowed_statuses", "ranking.recency_buckets",
    "ranking.category_topup", "ranking.reference_price", "ranking.tie_break", "intake.urgency_values",
    "intake.default_urgency", "intake.urgency_words", "intake.possible_duplicate_window", "matching.noise_phrases", "matching.abbreviations",
    "matching.symbols", "matching.number_weight", "matching.min_word_coverage", "matching.match_threshold",
    "matching.ambiguity_margin", "matching.ambiguity_floor", "matching.word_similarity",
    "matching.fuzzy_min_word_length", "ranking.preferred_score.weights",
]
SCORE_WEIGHTS = {"po_count", "recency", "contract_held", "on_time", "quality"}
FRACTIONS = ("min_word_coverage", "match_threshold", "ambiguity_margin", "ambiguity_floor", "word_similarity")
STAGE_NOTE = {
    "line_check": "line checks and flags see one matched line: line.*, item.*, plant.*, match.*, params.*",
    "override": "overrides run while clubbing, before any requirement exists: line.* and item.* only",
    "requirement": "rules and derived facts see every requirement-level fact",
}
STATUS_USES = {"receive_po", "be_suggested", "count_for_purchase_history", "hold_applicable_contract",
               "join_preferred_list"}


def collect(expr):
    """Return (operators, variable paths) used by an expression.
    Inside some/all/none the predicate's paths are reported as "<array path>[].<path>"."""
    ops, paths = set(), set()

    def walk(e, prefix):
        if isinstance(e, list):
            for x in e:
                walk(x, prefix)
        elif isinstance(e, dict):
            for op, args in e.items():
                ops.add(op)
                args = args if isinstance(args, list) else [args]
                if op == "var" and args and isinstance(args[0], str):
                    paths.add(prefix + args[0])
                elif op in ("some", "all", "none") and len(args) == 2:
                    walk(args[0], prefix)
                    array = args[0].get("var") if isinstance(args[0], dict) else None
                    walk(args[1], f"{prefix}{array}[]." if isinstance(array, str) else prefix)
                else:
                    walk(args, prefix)

    walk(expr, "")
    return ops, paths


def _limit_names(expr):
    """Second argument of every meets_limit in expr."""
    if isinstance(expr, list):
        return [n for e in expr for n in _limit_names(e)]
    if not isinstance(expr, dict):
        return []
    names = []
    for op, args in expr.items():
        if op == "meets_limit" and isinstance(args, list) and len(args) == 2:
            names.append(args[1])
        names += _limit_names(args)
    return names


def validate(policy, previous=None):
    errors, warnings = [], []
    err = lambda where, msg: errors.append(f"{where}: {msg}")  # noqa: E731
    if not isinstance(policy, dict):
        return ["document: not a JSON object"], []
    for key in sorted(TOP_KEYS - set(policy)):
        err("document", f"missing key '{key}'")
    for key in sorted(set(policy) - TOP_KEYS - OPTIONAL_TOP_KEYS):
        err("document", f"unknown key '{key}'")
    if policy.get("schema_version") != "1":
        err("schema_version", "must be \"1\"")
    if not isinstance(policy.get("version"), str) or not policy.get("version"):
        err("version", "must be a non-empty string")
    try:
        date.fromisoformat(str(policy.get("effective_from")))
    except ValueError:
        err("effective_from", f"not a YYYY-MM-DD date: {policy.get('effective_from')!r}")
    if previous:
        if policy.get("version") == previous["version"]:
            err("version", f"must differ from the current version {previous['version']}")
        if policy.get("supersedes") != previous["version"]:
            err("supersedes", f"must be {previous['version']!r}")
    params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}

    # Parameters: required paths, limit and window shapes, plain lists and settings.
    for path in REQUIRED_PARAMS:
        if get_path(params, path) is None:
            err("parameters", f"missing '{path}'")
    for name, limit in (params.get("limits") or {}).items():
        if not isinstance(limit, dict) or not isinstance(limit.get("value"), (int, float, Decimal)) \
                or isinstance(limit.get("value"), bool) or limit.get("operator") not in COMPARISONS:
            err(f"parameters.limits.{name}", "needs a numeric 'value' and an 'operator' in < <= > >=")

    def check_windows(node, where):
        if isinstance(node, dict):
            if "length" in node:
                if not isinstance(node["length"], (int, float, Decimal)) or node["length"] <= 0:
                    err(where, "window 'length' must be a positive number")
                if node.get("unit") not in WINDOW_UNITS:
                    err(where, f"window 'unit' must be one of {sorted(WINDOW_UNITS)}")
                if not isinstance(node.get("inclusive"), bool):
                    err(where, "window needs 'inclusive': true or false")
            for key, child in node.items():
                check_windows(child, f"{where}.{key}")
    check_windows(params, "parameters")

    def check_list(path, allowed):
        value = get_path(params, path)
        if value is not None and (not isinstance(value, list) or not value or set(value) - allowed):
            err(f"parameters.{path}", f"must be a non-empty list drawn from {sorted(allowed)}")
    check_list("clubbing.match_on", set(PR_LINE) | {"category", "item_type"})
    check_list("consolidation.match_on", {"supplier_id", "plant", "route", "decision"} | set(PR_LINE))
    check_list("valuation.price_sources", PRICE_SOURCES)
    statuses = get_path(params, "suppliers.allowed_statuses") or {}
    for use in sorted(STATUS_USES - set(statuses)):
        err("parameters.suppliers.allowed_statuses", f"missing '{use}'")
    for use in statuses:
        check_list(f"suppliers.allowed_statuses.{use}", STATUSES)
    tie = get_path(params, "ranking.tie_break") or {}
    if tie and (tie.get("order_by") != "supplier_id" or tie.get("direction") not in ("ascending", "descending")):
        err("parameters.ranking.tie_break", "order_by must be supplier_id and direction ascending or descending")
    if not isinstance(get_path(params, "valuation.include_non_active_suppliers"), bool):
        err("parameters.valuation.include_non_active_suppliers", "must be true or false")

    # Expressions: known operators, known fields, existing limits.
    def check_expr(where, expr, scope, derived):
        ops, paths = collect(expr)
        for op in sorted(ops - OPERATORS):
            err(where, f"unknown operator '{op}'")
        for path in sorted(paths):
            if path in SCOPES[scope]:
                continue
            if path.startswith("params.") and "params." in DYNAMIC_PREFIXES[scope]:
                if get_path(params, path[len("params."):]) is None:
                    err(where, f"unknown parameter '{path}'")
            elif path.startswith("derived.") and "derived." in DYNAMIC_PREFIXES[scope]:
                if path[len("derived."):] not in derived:
                    err(where, f"derived fact '{path}' is not defined before it is used")
            elif any(path in s for s in SCOPES.values()) or path.startswith(("derived.", "params.")):
                err(where, f"'{path}' is not available at the {scope} stage ({STAGE_NOTE[scope]})")
            else:
                err(where, f"unknown field '{path}' (not in the fact catalogue)")
        for name in _limit_names(expr):
            if not isinstance(name, str) or not isinstance(get_path(params, name), dict) \
                    or "operator" not in get_path(params, name):
                err(where, f"meets_limit refers to '{name}', which is not a limit parameter")

    def unique_ids(items, key, where):
        seen = set()
        for item in items:
            ident = item.get(key) if isinstance(item, dict) else None
            if not isinstance(ident, str) or not ident:
                err(where, f"every entry needs a string '{key}'")
            elif ident in seen:
                err(where, f"duplicate {key} '{ident}'")
            seen.add(ident)

    overrides = policy.get("overrides") or []
    unique_ids(overrides, "id", "overrides")
    for o in overrides:
        where = f"overrides[{o.get('id')}]"
        target = get_path(params, str(o.get("parameter")))
        if not isinstance(target, dict):
            err(where, f"parameter '{o.get('parameter')}' does not exist")
        elif not isinstance(o.get("set"), dict) or not o["set"]:
            err(where, "'set' must be a non-empty object")
        else:
            for key, value in o["set"].items():
                if key not in target:
                    err(where, f"'{key}' is not a field of parameter '{o['parameter']}'")
                elif type(value) is not type(target[key]) and not (
                        isinstance(value, (int, float, Decimal)) and isinstance(target[key], (int, float, Decimal))):
                    err(where, f"'{key}' must have the same type as in the parameter")
                elif key == "operator" and value not in COMPARISONS:
                    err(where, "'operator' must be one of < <= > >=")
        check_expr(where, o.get("when"), "override", set())

    derived = set()
    facts = policy.get("derived_facts") or []
    unique_ids(facts, "name", "derived_facts")
    for fact in facts:
        name = str(fact.get("name"))
        if not name.isidentifier():
            err(f"derived_facts[{name}]", "name must be a simple identifier like lead_time_days")
        check_expr(f"derived_facts[{name}]", fact.get("expr"), "requirement", derived)
        derived.add(name)

    checks = policy.get("line_checks") or []
    unique_ids(checks, "id", "line_checks")
    for check in checks:
        check_expr(f"line_checks[{check.get('id')}]", check.get("when"), "line_check", set())
        if not isinstance(check.get("reason"), str) or not check.get("reason"):
            err(f"line_checks[{check.get('id')}]", "needs a 'reason'")

    flags = policy.get("line_flags") or []
    unique_ids(flags, "id", "line_flags")
    for flag in flags:
        check_expr(f"line_flags[{flag.get('id')}]", flag.get("when"), "line_check", set())
        if not isinstance(flag.get("message"), str) or not flag.get("message"):
            err(f"line_flags[{flag.get('id')}]", "needs a 'message'")
        for name in re.findall(r"\{([^{}]+)\}", flag.get("message") or ""):
            if name not in SCOPES["line_check"]:
                err(f"line_flags[{flag.get('id')}]", f"message names '{{{name}}}', which is not a line-check fact")
    weights = get_path(params, "ranking.preferred_score.weights")
    if weights is not None and (not isinstance(weights, dict) or set(weights) != SCORE_WEIGHTS or not all(
            isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) and v >= 0 for v in weights.values())):
        err("parameters.ranking.preferred_score.weights", f"must give a number >= 0 for each of {sorted(SCORE_WEIGHTS)}")
    matching = get_path(params, "matching") or {}
    for key in FRACTIONS:
        value = matching.get(key)
        if value is not None and (not isinstance(value, (int, float, Decimal)) or isinstance(value, bool)
                                  or not 0 <= value <= 1):
            err(f"parameters.matching.{key}", "must be a number from 0 to 1")
    for key in ("number_weight", "fuzzy_min_word_length"):
        value = matching.get(key)
        if value is not None and (not isinstance(value, (int, float, Decimal)) or isinstance(value, bool) or value < 1):
            err(f"parameters.matching.{key}", "must be a number of at least 1")
    if not all(isinstance(x, str) and x.strip() for x in matching.get("noise_phrases", [])):
        err("parameters.matching.noise_phrases", "must be a list of non-empty phrases")
    for key in ("abbreviations", "symbols"):
        table = matching.get(key, {})
        if not isinstance(table, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in table.items()):
            err(f"parameters.matching.{key}", "must map text to text")
    urgency = get_path(params, "intake.urgency_values")
    if urgency is not None and (not isinstance(urgency, dict) or
                                get_path(params, "intake.default_urgency") not in urgency.values()):
        err("parameters.intake", "urgency_values must map words to urgencies, and default_urgency must be one of them")

    rules = policy.get("rules") or []
    if not rules:
        err("rules", "the rule list is empty")
    unique_ids(rules, "id", "rules")
    for i, rule in enumerate(rules):
        where = f"rules[{rule.get('id')}]"
        check_expr(where, rule.get("when"), "requirement", derived)
        then = rule.get("then") or {}
        decision = then.get("decision")
        if decision not in SUPPLIER_BY_DECISION:
            err(where, "then.decision must be PO or SOURCING_REQUEST")
            continue
        if then.get("route") not in ROUTES:
            err(where, f"then.route must be one of {sorted(ROUTES)}")
        if then.get("supplier") not in SUPPLIER_BY_DECISION[decision]:
            err(where, f"then.supplier for {decision} must be one of {sorted(SUPPLIER_BY_DECISION[decision])}")
        if then.get("price") not in PRICE_BY_DECISION[decision]:
            err(where, f"then.price for {decision} must be one of {sorted(PRICE_BY_DECISION[decision])}")
        count = then.get("suggest_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0 or (decision == "PO" and count):
            err(where, "then.suggest_count must be a whole number >= 0, and 0 for a PO")
        if rule.get("when") is True and i < len(rules) - 1:
            warnings.append(f"{where}: always true, so the rules after it can never apply")
    return errors, warnings
