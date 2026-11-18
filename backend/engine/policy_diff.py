"""Field-by-field difference between two policy documents.

Lists are keyed by identity, not position: rules and line checks by id, derived facts by name, overrides
by id. So inserting a rule shows as one added rule plus a changed rule order, not as every later rule
"changing". The plain-language rendering for the approval screen is built on top of this later.
"""
import json


SECTIONS = (("overrides", "id"), ("derived_facts", "name"), ("line_checks", "id"), ("line_flags", "id"), ("rules", "id"))


def _flatten(policy):
    flat = {}

    def params(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                params(v, f"{path}.{k}")
        else:
            flat[path] = node
    params(policy.get("parameters", {}), "parameters")

    for section, key in SECTIONS:
        for entry in policy.get(section) or []:
            for field, value in entry.items():
                if field != key:
                    flat[f"{section}[{entry.get(key)}].{field}"] = value
    flat["rule order"] = [r.get("id") for r in policy.get("rules") or []]
    # Every other top-level key (metadata, and anything unexpected) as a whole, so no change goes unseen.
    for key, value in policy.items():
        if key != "parameters" and key not in dict(SECTIONS):
            flat[key] = value
    return flat


def _show(value):
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


def diff(old, new):
    """[(kind, path, old_value, new_value)] with kind "+" added, "-" removed, "~" changed."""
    a, b = _flatten(old), _flatten(new)
    out = []
    for path in list(a) + [p for p in b if p not in a]:
        if path not in b:
            out.append(("-", path, a[path], None))
        elif path not in a:
            out.append(("+", path, None, b[path]))
        elif a[path] != b[path]:
            out.append(("~", path, a[path], b[path]))
    return out


def format_diff(changes):
    lines = []
    for kind, path, old, new in changes:
        if kind == "~":
            lines.append(f"~ {path}: {_show(old)}  ->  {_show(new)}")
        elif kind == "+":
            lines.append(f"+ {path}: {_show(new)}")
        else:
            lines.append(f"- {path}: {_show(old)}")
    return "\n".join(lines) if lines else "(no differences)"
