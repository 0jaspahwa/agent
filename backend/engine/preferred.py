"""F3: the preferred supplier list for an item as of a date (policy 6), and category top-ups (6.4).

Membership (6.1): suppliers whose status is in allowed_statuses.join_preferred_list with at least one PO for
the item in history.preferred_window, or a contract covering the item that started on or before the date
(even if it has since expired).
Score (6.2, D24): weights from ranking.preferred_score, applied to
  po_count (POs for the item in the window, any plant) | recency (ranking.recency_buckets on the age of the
  supplier's last PO) | contract_held (1 if it holds such a contract) | on_time_pct / 100 | quality_rating / 5.
Equal scores: ranking.tie_break (supplier_id ascending, D13). Every part of the score is returned, so a
buyer can see why a supplier is ranked where it is.
Reference price (6.3): the supplier's most recent PO price for the item in the window (D1 on ties); if
none, the rate in its most recent contract for the item.
"""
from dataclasses import dataclass
from decimal import Decimal

from engine.history import most_recent, pos_in_window
from engine.logic import exact


@dataclass(frozen=True)
class RankedSupplier:
    supplier_id: str
    rank: int
    score: Decimal
    parts: tuple[tuple[str, Decimal], ...]  # (component, weighted contribution); they add up to score
    inputs: dict  # po_count, last_po_date, recency, contract_held, on_time_pct, quality_rating
    reference_price: Decimal | None
    reference: str | None  # "PO 7300244" or "contract RC-2025-020"


def _contracts_for(item_code, as_of, master, supplier_id=None):
    return [c for c in master.contracts if c.start_date <= as_of and any(l.item_code == item_code for l in c.lines)
            and (supplier_id is None or c.supplier_id == supplier_id)]


def recency_score(age_days, buckets):
    if age_days is not None:
        for bucket in buckets["buckets"]:
            if age_days <= bucket["max_age_days"] if bucket["inclusive"] else age_days < bucket["max_age_days"]:
                return exact(bucket["score"])
    return exact(buckets["older_score"])


def _order(entries, tie_break):
    if tie_break["order_by"] != "supplier_id":
        raise ValueError(f"unknown ranking.tie_break {tie_break!r}")
    reverse_id = tie_break["direction"] == "descending"
    # sort by score descending, then supplier_id in the tie-break direction (two stable sorts)
    return sorted(sorted(entries, key=lambda e: e[0], reverse=reverse_id), key=lambda e: e[1], reverse=True)


def preferred_list(item_code, as_of, master, params):
    window = params["history"]["preferred_window"]
    statuses = params["suppliers"]["allowed_statuses"]["join_preferred_list"]
    ranking = params["ranking"]
    weights = {k: exact(v) for k, v in ranking["preferred_score"]["weights"].items()}
    pos = pos_in_window(item_code, as_of, master, window)
    members = {p.supplier_id for p in pos} | {c.supplier_id for c in _contracts_for(item_code, as_of, master)}
    entries = []
    for sid in members:
        supplier = master.suppliers.get(sid)
        if not supplier or supplier.status not in statuses:
            continue
        own = [p for p in pos if p.supplier_id == sid]
        last = most_recent(own)
        contracts = _contracts_for(item_code, as_of, master, sid)
        inputs = {"po_count": len(own), "last_po_date": last.po_date if last else None,
                  "recency": recency_score((as_of - last.po_date).days if last else None, ranking["recency_buckets"]),
                  "contract_held": bool(contracts), "on_time_pct": supplier.on_time_pct,
                  "quality_rating": supplier.quality_rating}
        parts = (("po_count", weights["po_count"] * inputs["po_count"]),
                 ("recency", weights["recency"] * inputs["recency"]),
                 ("contract_held", weights["contract_held"] * (1 if inputs["contract_held"] else 0)),
                 ("on_time", weights["on_time"] * supplier.on_time_pct / 100),
                 ("quality", weights["quality"] * supplier.quality_rating / 5))
        if last:
            price, ref = last.unit_price, f"PO {last.po_number}"
        else:
            newest = max(contracts, key=lambda c: (c.start_date, c.end_date, c.contract_id))
            price = next(l.rate for l in newest.lines if l.item_code == item_code)
            ref = f"contract {newest.contract_id}"
        entries.append((sid, sum(v for _, v in parts), parts, inputs, price, ref))
    ordered = _order([(e[0], e[1], e) for e in entries], ranking["tie_break"])
    return tuple(RankedSupplier(e[0], n, e[1], e[2], e[3], e[4], e[5]) for n, (_, _, e) in enumerate(ordered, start=1))


def topup_suppliers(item_code, master, params, statuses, exclude=()):
    """Suppliers listing the item's category, best delivery and quality first (6.4, category_topup):
    [(supplier_id, score, parts)], ties by ranking.tie_break."""
    category = master.items[item_code].category
    weights = params["ranking"]["category_topup"]
    entries = []
    for sid, s in master.suppliers.items():
        if sid in exclude or s.status not in statuses or category not in s.categories:
            continue
        parts = (("on_time", exact(weights["on_time_weight"]) * s.on_time_pct / 100),
                 ("quality", exact(weights["quality_weight"]) * s.quality_rating / 5))
        entries.append((sid, sum(v for _, v in parts), parts))
    return [(e[0], e[1], e[2]) for _, _, e in _order([(e[0], e[1], e) for e in entries], params["ranking"]["tie_break"])]
