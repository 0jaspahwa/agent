"""F5: combine requirements that end in a PO into purchase orders (policy 7), from consolidation.*.

Requirements are taken in order of creation (their first line's created_at, then group id). Each joins the
earliest open PO whose first requirement has the same consolidation.match_on values and was created within
consolidation.window of it (measured from that PO's first requirement); otherwise it starts a new PO. POs
are numbered PO-0001... in that order. Sourcing requests never reach this function (7.2).
"""
from dataclasses import dataclass, field
from datetime import timedelta


@dataclass(frozen=True)
class Entry:
    group_id: str
    created_at: object  # datetime of the requirement's first line
    key: dict  # the requirement's value for every consolidation.match_on field
    params: dict  # consolidation parameters of the requirement's policy version


@dataclass
class PurchaseOrder:
    po_id: str
    first: Entry
    entries: list = field(default_factory=list)

    @property
    def group_ids(self):
        return [e.group_id for e in self.entries]


def _within(first, other, window):
    gap = other.created_at - first.created_at
    limit = timedelta(hours=window["length"]) if window["unit"] == "hours" else timedelta(days=window["length"])
    if gap < timedelta(0):
        return False
    return gap <= limit if window["inclusive"] else gap < limit


def consolidate(entries):
    pos = []
    for entry in sorted(entries, key=lambda e: (e.created_at, e.group_id)):
        params = None
        home = None
        for po in pos:
            params = po.first.params
            if all(po.first.key.get(f) == entry.key.get(f) for f in params["match_on"]) and \
                    _within(po.first, entry, params["window"]):
                home = po
                break
        if home is None:
            home = PurchaseOrder(f"PO-{len(pos) + 1:04d}", entry)
            pos.append(home)
        home.entries.append(entry)
    return pos
