"""Change operations (D33): the LLM proposes a short list of edits, and this pure function applies them, in
order, to the base policy. The result then goes through the same validator, diff and impact preview as any draft.

Paths use dots, and brackets for an entry of a list section by its id: "parameters.limits.spot_po.value",
"rules[5.5].then.suggest_count", "overrides[OV-1].set.value", "parameters.matching.noise_phrases".

Operations:
  {"op": "set", "path": P, "value": V}                    change an existing value
  {"op": "add_parameter", "path": P, "value": V}          a new parameter (its parent must exist)
  {"op": "add", "section": S, "item": {...}, "before"|"after": ID}   rules need a position
  {"op": "replace", "section": S, "id": ID, "item": {...}}
  {"op": "remove", "section": S, "id": ID}                 not for derived_facts (rules may use them)
  {"op": "list_add" | "list_remove", "path": P, "values": [...]}
Sections: rules, overrides, derived_facts, line_checks, line_flags.
"""
import copy
import re

SECTIONS = {"rules": "id", "overrides": "id", "derived_facts": "name", "line_checks": "id", "line_flags": "id"}
NAMES = {"rules": "rule", "overrides": "override", "derived_facts": "derived fact", "line_checks": "line check",
         "line_flags": "line flag"}
POSITIONED = {"rules"}  # rule order decides the outcome, so a new rule must say where it goes
NOT_REMOVABLE = {"derived_facts"}
OPS = {"set", "add_parameter", "add", "replace", "remove", "list_add", "list_remove"}
SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]+)\])?")


class OperationError(ValueError):
    pass


def parse_path(path):
    """'rules[5.5].then.suggest_count' -> [('rules', '5.5'), ('then', None), ('suggest_count', None)]."""
    if not isinstance(path, str) or not path:
        raise OperationError("the path is missing")
    out, i = [], 0
    while i < len(path):
        m = SEGMENT.match(path, i)
        if not m:
            raise OperationError(f"'{path}' is not a valid path")
        out.append((m.group(1), m.group(2)))
        i = m.end()
        if i < len(path):
            if path[i] != ".":
                raise OperationError(f"'{path}' is not a valid path")
            i += 1
            if i == len(path):
                raise OperationError(f"'{path}' is not a valid path")
    return out


def _entry(doc, section, ident):
    items = doc.get(section)
    if section not in SECTIONS or not isinstance(items, list):
        raise OperationError(f"there is no section '{section}'")
    for item in items:
        if isinstance(item, dict) and item.get(SECTIONS[section]) == ident:
            return item
    raise OperationError(f"there is no {NAMES[section]} '{ident}'")


def _resolve(doc, path, create=False):
    """(container, key) for the last segment of `path`. The container must exist; the key must exist unless create."""
    segments = parse_path(path)
    first, ident = segments[0]
    if first == "parameters" and ident is None:
        node, where = doc["parameters"], "parameters"
        rest = segments[1:]
    elif first in SECTIONS and ident is not None:
        node, where = _entry(doc, first, ident), f"{first}[{ident}]"
        rest = segments[1:]
    else:
        raise OperationError(f"'{path}' must start with 'parameters.' or a section entry such as 'rules[5.4].'")
    if not rest:
        raise OperationError(f"'{path}' names a whole entry; use 'replace' to change it")
    for name, sub in rest[:-1]:
        if sub is not None or not isinstance(node, dict) or name not in node:
            raise OperationError(f"'{path}' does not exist (no '{name}' in {where})")
        node, where = node[name], f"{where}.{name}"
    name, sub = rest[-1]
    if sub is not None or not isinstance(node, dict):
        raise OperationError(f"'{path}' does not exist")
    if name not in node and not create:
        raise OperationError(f"'{path}' does not exist (no '{name}' in {where})")
    if name in node and create:
        raise OperationError(f"'{path}' already exists; use 'set' to change it")
    return node, name


def _position(items, section, op):
    before, after = op.get("before"), op.get("after")
    if before is not None and after is not None:
        raise OperationError("give either 'before' or 'after', not both")
    anchor = before if before is not None else after
    if anchor is None:
        if section in POSITIONED:
            raise OperationError("a new rule needs 'before' or 'after' a named rule, because rule order decides outcomes")
        return len(items)
    key = SECTIONS[section]
    for i, item in enumerate(items):
        if item.get(key) == anchor:
            return i if before is not None else i + 1
    raise OperationError(f"there is no {NAMES[section]} '{anchor}' to place it {'before' if before is not None else 'after'}")


def _section(op):
    section = op.get("section")
    if section not in SECTIONS:
        raise OperationError(f"'section' must be one of {', '.join(SECTIONS)}")
    return section


def _item(op, section):
    item = op.get("item")
    if not isinstance(item, dict) or not item:
        raise OperationError(f"'item' must be the whole {NAMES[section]} as an object")
    return copy.deepcopy(item)


def _apply_one(doc, op):
    kind = op.get("op")
    if kind not in OPS:
        raise OperationError(f"unknown operation '{kind}' (allowed: {', '.join(sorted(OPS))})")
    if kind in ("set", "add_parameter"):
        if "value" not in op:
            raise OperationError("'value' is missing")
        if kind == "add_parameter" and not str(op.get("path", "")).startswith("parameters."):
            raise OperationError("'add_parameter' only adds under 'parameters.'")
        node, key = _resolve(doc, op.get("path"), create=kind == "add_parameter")
        node[key] = copy.deepcopy(op["value"])
    elif kind in ("list_add", "list_remove"):
        node, key = _resolve(doc, op.get("path"))
        values = op.get("values")
        if not isinstance(node[key], list):
            raise OperationError(f"'{op['path']}' is not a list")
        if not isinstance(values, list) or not values:
            raise OperationError("'values' must be a non-empty list")
        for v in values:
            if kind == "list_add":
                if v in node[key]:
                    raise OperationError(f"{v!r} is already in '{op['path']}'")
                node[key].append(copy.deepcopy(v))
            else:
                if v not in node[key]:
                    raise OperationError(f"{v!r} is not in '{op['path']}'")
                node[key].remove(v)
    else:
        section = _section(op)
        key = SECTIONS[section]
        items = doc.setdefault(section, [])
        if kind == "add":
            item = _item(op, section)
            ident = item.get(key)
            if not isinstance(ident, str) or not ident:
                raise OperationError(f"the new {NAMES[section]} needs a '{key}'")
            if any(i.get(key) == ident for i in items):
                raise OperationError(f"{NAMES[section]} '{ident}' already exists; use 'replace'")
            items.insert(_position(items, section, op), item)
        else:
            ident = op.get("id")
            current = _entry(doc, section, ident)
            if kind == "replace":
                item = _item(op, section)
                if item.setdefault(key, ident) != ident:
                    raise OperationError(f"'replace' cannot rename {NAMES[section]} '{ident}' to '{item[key]}'")
                items[items.index(current)] = item
            else:
                if section in NOT_REMOVABLE:
                    raise OperationError(f"a {NAMES[section]} cannot be removed (rules may use it); replace it instead")
                items.remove(current)


def describe(op):
    kind = op.get("op") if isinstance(op, dict) else None
    if kind in ("add", "replace", "remove"):
        target = op.get("id") or (op.get("item") or {}).get(SECTIONS.get(op.get("section"), "id"))
        return f"{kind} {NAMES.get(op.get('section'), op.get('section'))} {target}"
    if kind:
        return f"{kind} {op.get('path')}"
    return "not an operation"


def apply_operations(base, operations):
    """A new document: `operations` applied in order to a copy of `base`. Raises OperationError naming the
    first operation that cannot be applied, and why. `base` is never changed."""
    if not isinstance(operations, list):
        raise OperationError("'operations' must be a list")
    doc = copy.deepcopy(base)
    for n, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            raise OperationError(f"Operation {n} is not an object")
        try:
            _apply_one(doc, op)
        except OperationError as exc:
            raise OperationError(f"Operation {n} ({describe(op)}): {exc}") from None
    return doc
