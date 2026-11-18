"""E3: club PR lines into requirements (policy 2.2, 2.3), driven by the policy's clubbing parameters.

Lines are taken in clubbing.order_by order. A line joins the earliest open requirement whose FIRST line
it matches on every clubbing.match_on field and sits within both windows of; otherwise it starts a new
requirement. Each requirement uses the policy version in force on its first line's creation date, with
that version's overrides evaluated on the first line, and every joining line is judged by those windows.
New items are never clubbed; NOT_PROCESSED lines are left out.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from engine.lines import canon_code, line_number_key, order_key
from engine.policy import resolve_parameters
from engine.validation import CheckedLine


@dataclass(frozen=True)
class Requirement:
    group_id: str  # R-0001 ... in order of the first line's creation time, then PR number, then line
    item_code: str | None  # None for a new item
    plant: str
    lines: tuple[CheckedLine, ...]  # lines[0] is the first line
    version: object  # PolicyVersion in force on the first line's creation date
    params: dict  # that version's parameters after overrides for the first line

    @property
    def first(self):
        return self.lines[0]

    @property
    def requirement_date(self):  # policy 2.3
        return self.first.line.created_at.date()

    @property
    def created_at(self):
        return self.first.line.created_at

    @property
    def total_quantity(self):
        return sum((c.line.quantity for c in self.lines), Decimal("0"))

    @property
    def is_emergency(self):  # policy 2.3: any line marked Emergency
        return any(c.urgency == "Emergency" for c in self.lines)

    @property
    def is_new(self):
        return self.item_code is None


def _field(checked, name, item):
    if name == "item_code":
        return checked.item_code
    if name == "plant":
        return checked.plant
    if name in ("category", "item_type"):
        return getattr(item, name, None) if item else None
    value = getattr(checked.line, name)
    return value.strip().casefold() if isinstance(value, str) else value


def _within(first, other, window, either_side=False):
    """Is `other` within the window of `first`? Calendar days compare dates; hours compare timestamps."""
    if window["unit"] == "hours":
        gap = other - first
        limit = timedelta(hours=window["length"])
    else:
        gap = (other.date() if hasattr(other, "date") else other) - (first.date() if hasattr(first, "date") else first)
        gap = gap.days
        limit = window["length"]
    if either_side:
        gap = abs(gap)
    elif gap < (timedelta(0) if window["unit"] == "hours" else 0):
        return False
    return gap <= limit if window["inclusive"] else gap < limit


def joins(requirement, checked, items):
    params = requirement.params["clubbing"]
    first = requirement.first
    item = items.get(checked.item_code)
    if any(_field(first, f, item) != _field(checked, f, item) for f in params["match_on"]):
        return False
    return (_within(first.line.created_at, checked.line.created_at, params["creation_window"])
            and _within(first.line.need_by_date, checked.line.need_by_date, params["need_by_window"],
                        either_side=params["need_by_window"].get("either_side", True)))


def _start(checked):
    facts = checked.facts or {}
    params = resolve_parameters(checked.version.document, {"line": facts.get("line"), "item": facts.get("item")})
    return [checked, params]


def club(checked_lines, master):
    """Requirements from the processed lines, with deterministic group ids."""
    processed = [c for c in checked_lines if c.processed]
    if not processed:
        return ()
    latest = max((c.version for c in processed), key=lambda v: v.effective_from)
    order_by = latest.document["parameters"]["clubbing"]["order_by"]
    open_reqs = []  # [first CheckedLine, params, [lines]] in creation order
    for checked in sorted(processed, key=lambda c: order_key(c.line, order_by)):
        home = None
        if not checked.is_new:
            for req in open_reqs:
                first, params, lines = req
                if not first.is_new and joins(Requirement("", first.item_code, first.plant, tuple(lines),
                                                          first.version, params), checked, master.items):
                    home = req
                    break
        if home:
            home[2].append(checked)
        else:
            first, params = _start(checked)
            open_reqs.append([first, params, [checked]])
    open_reqs.sort(key=lambda r: (r[0].line.created_at, canon_code(r[0].line.pr_no), line_number_key(r[0].line.pr_line)))
    return tuple(Requirement(f"R-{n:04d}", first.item_code, first.plant, tuple(lines), first.version, params)
                 for n, (first, params, lines) in enumerate(open_reqs, start=1))
