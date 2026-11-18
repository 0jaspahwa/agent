"""Canonical forms and ordering for PR lines.

Plant codes, item codes, units and urgency are compared case-insensitively (D17); the original text stays
on the PRLine for display. pr_line is kept as text, but ordered by its numeric value (2 before 10).
"""
import re
from datetime import datetime


def canon_code(value):
    """Plant or item code: trimmed, upper case. Blank -> None."""
    return (value or "").strip().upper() or None


def canon_uom(value):
    """Unit of measure: upper case, letters and digits only ("Nos." -> "NOS"). Blank -> None."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper()) or None


def canon_urgency(value, intake):
    """(urgency, recognised). Blank or unknown -> the policy's default urgency, recognised = False."""
    mapping = {k.lower(): v for k, v in intake["urgency_values"].items()}
    key = (value or "").strip().lower()
    return (mapping[key], True) if key in mapping else (intake["default_urgency"], False)


def line_number_key(pr_line):
    text = (pr_line or "").strip()
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def order_key(line, fields):
    """Sort key for a PR line from the policy's clubbing.order_by field list."""
    key = []
    for name in fields:
        value = getattr(line, name)
        if name == "pr_line":
            key.append(line_number_key(value))
        elif name == "created_at":
            key.append(value or datetime.max)
        else:
            key.append((value or "").strip().upper() if isinstance(value, str) or value is None else value)
    return tuple(key)
