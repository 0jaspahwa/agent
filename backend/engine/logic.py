"""A small JSON Logic evaluator of our own (standard library only).

An expression is a literal (number, string, bool, None, list) or a dict with exactly one key, the operator:
{"<=": [{"var": "requirement.value_inr"}, 500000]}. evaluate(expr, data) returns its value.

Three kinds of trouble, handled differently:
  * Unknown field name (not in the fact catalogue): caught by policy_check.validate before a policy is
    approved, so it never reaches a batch run.
  * Known field with no value here (a blank estimated_unit_price, a new item's category): a comparison on
    it is False, arithmetic on it is None, and its path is appended to the `missing` list the caller
    passes in, so the engine can say so in the reason text. No exception.
  * Mixed types (comparing a string with a number), unknown operators, malformed expressions: LogicError.
Numbers are exact decimals throughout (D11): any float that reaches the evaluator, whether a literal in the
policy or a fact, becomes Decimal(repr(x)), so 1.15 is exactly 1.15; division is decimal division.
Extra operators beyond jsonlogic.com: date_diff_days (whole days a - b) and meets_limit (compare a value
with a limit parameter that stores its own operator, so "<=" vs "<" lives with the limit, not the rule).
"""
from datetime import date, datetime
from decimal import Decimal, DecimalException


class LogicError(ValueError):
    """A policy expression that cannot be evaluated (unknown operator, mixed types, bad shape)."""


def get_path(data, path, default=None):
    """Read "a.b.0.c" from nested dicts/lists. "" returns data itself. Missing or null -> default."""
    if path in ("", None):
        return data
    for part in str(path).split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return default
    return default if data is None else data


def to_date(value):
    """Accept a date, a datetime, "YYYY-MM-DD" or "YYYY-MM-DD HH:MM[:SS]"; return the date part."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        return date.fromisoformat(value[:10])
    raise LogicError(f"not a date: {value!r}")


def exact(value):
    """A float becomes the Decimal of its written form; everything else is returned unchanged."""
    return Decimal(repr(value)) if isinstance(value, float) else value


def _compare(op, a, b):
    if isinstance(a, str) != isinstance(b, str) or isinstance(a, bool) or isinstance(b, bool):
        raise LogicError(f"'{op}' cannot compare {a!r} with {b!r}")
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


COMPARISONS = ("<", "<=", ">", ">=")
NULL_IS_FALSE = set(COMPARISONS) | {"meets_limit"}            # a missing operand makes these False
NULL_IS_NULL = {"+", "-", "*", "/", "min", "max", "date_diff_days"}  # a missing operand gives None
OPS = {  # operators whose arguments are evaluated first
    "==": lambda a, b: a == b, "===": lambda a, b: a == b,
    "!=": lambda a, b: a != b, "!==": lambda a, b: a != b,
    "!": lambda a: not a,
    "!!": lambda a: bool(a),
    "in": lambda a, b: b is not None and a is not None and a in b,
    "+": lambda *v: sum(v),
    "-": lambda *v: -v[0] if len(v) == 1 else v[0] - v[1],
    "*": lambda a, b: a * b,
    "/": lambda a, b: Decimal(a) / Decimal(b),
    "min": lambda *v: min(v),
    "max": lambda *v: max(v),
    "date_diff_days": lambda a, b: (to_date(a) - to_date(b)).days,
}
OPERATORS = set(OPS) | NULL_IS_FALSE | {"var", "and", "or", "if", "some", "all", "none"}


def evaluate(expr, data, missing=None):
    """Evaluate expr against data. If `missing` is a list, paths of fields that had no value are added."""
    if isinstance(expr, list):
        return [evaluate(e, data, missing) for e in expr]
    if not isinstance(expr, dict):
        return exact(expr)
    if len(expr) != 1:
        raise LogicError(f"an operation needs exactly one operator key, got {sorted(expr)}")
    op, args = next(iter(expr.items()))
    args = args if isinstance(args, list) else [args]

    if op in ("and", "or"):  # lazy; like JSON Logic, return the first deciding value, else the last one
        result = op == "and"
        for a in args:
            result = evaluate(a, data, missing)
            if bool(result) != (op == "and"):
                return result
        return result
    if op == "if":  # [cond1, then1, cond2, then2, ..., else]
        for i in range(0, len(args) - 1, 2):
            if evaluate(args[i], data, missing):
                return evaluate(args[i + 1], data, missing)
        return evaluate(args[-1], data, missing) if len(args) % 2 else None
    if op in ("some", "all", "none"):  # [array, predicate]; the predicate sees one element as its data
        inner = [] if missing is not None else None
        hits = [bool(evaluate(args[1], item, inner)) for item in evaluate(args[0], data, missing) or []]
        if inner:
            array = get_path(args[0], "var") if isinstance(args[0], dict) else "?"
            missing.extend(f"{array}[].{p}" for p in dict.fromkeys(inner))
        return {"some": any(hits), "all": bool(hits) and all(hits), "none": not any(hits)}[op]

    values = [evaluate(a, data, missing) for a in args]
    if op == "var":  # {"var": "path"} or {"var": ["path", default]}
        value = exact(get_path(data, values[0], values[1] if len(values) > 1 else None))
        if value is None and len(values) < 2 and missing is not None:
            missing.append(str(values[0]))
        return value
    if op in NULL_IS_FALSE and len(values) != 2:
        raise LogicError(f"'{op}' needs exactly two arguments, got {values!r}")
    if op in NULL_IS_FALSE and values[0] is None or op in COMPARISONS and values[1] is None:
        return False
    if op in NULL_IS_NULL and any(v is None for v in values):
        return None
    if op == "meets_limit":  # {"meets_limit": [value, "limits.spot_po"]} -> value <operator> limit.value
        limit = get_path(data, "params." + str(values[1]))
        if not isinstance(limit, dict) or limit.get("operator") not in COMPARISONS:
            raise LogicError(f"no limit parameter 'params.{values[1]}' with a valid operator")
        return _compare(limit["operator"], values[0], exact(limit["value"]))
    if op in COMPARISONS:
        return _compare(op, *values)
    if op not in OPS:
        raise LogicError(f"unknown operator {op!r}")
    try:
        return OPS[op](*values)
    except (TypeError, ZeroDivisionError, DecimalException) as exc:
        raise LogicError(f"bad arguments for {op!r}: {values!r}") from exc
