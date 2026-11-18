"""F4: the requirement-level facts the policy's rules read (fact catalogue, engine/facts.py REQUIREMENT_SCOPE).

Dates and timestamps are given to the rules as ISO text ("2026-11-04", "2026-11-04 12:40:00"), so a policy
can compare them with a literal date or use date_diff_days. Money and quantities stay exact decimals.
"""
import dataclasses
from datetime import date, datetime

from engine.history import history_facts


def plain(value):
    """Dates to ISO text, recursively; everything else unchanged."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def _line(checked):
    return plain({k: v for k, v in (checked.facts or {}).get("line", {}).items()})


def requirement_facts(req, choice, valuation, preferred, master, params):
    first = req.first.line
    item = master.items.get(req.item_code) if req.item_code else None
    plant = master.plants.get(req.plant)
    chosen = choice.chosen if choice else None
    rank1 = preferred[0] if preferred else None
    facts = {
        "requirement": {
            "id": req.group_id, "date": req.requirement_date.isoformat(), "created_at": plain(req.created_at),
            "plant": req.plant, "item_code": req.item_code or "NEW", "is_new_item": req.is_new,
            "total_quantity": req.total_quantity, "line_count": len(req.lines),
            "distinct_requesters": len({c.line.requester for c in req.lines if c.line.requester}),
            "distinct_departments": len({c.line.department for c in req.lines if c.line.department}),
            "lead_time_days": (first.need_by_date - req.requirement_date).days if first.need_by_date else None,
            "value_inr": valuation.value, "valuation_price": valuation.unit_price, "valuation_source": valuation.source,
        },
        "first_line": _line(req.first),
        "lines": [_line(c) for c in req.lines],
        "item": plain(dataclasses.asdict(item)) if item else None,
        "plant": dataclasses.asdict(plant) if plant else None,
        "contract": {
            "usable": bool(chosen), "any_applicable": bool(choice and choice.applicable),
            "remaining_ceiling": chosen.remaining_before if chosen else None,
            "lowest_applicable_rate": choice.lowest_rate if choice else None,
            **({"contract_id": chosen.contract.contract_id, "supplier_id": chosen.contract.supplier_id,
                "supplier_name": chosen.contract.supplier_name, "start_date": chosen.contract.start_date.isoformat(),
                "end_date": chosen.contract.end_date.isoformat(), "value_cap": chosen.contract.value_cap,
                "consumed_value": chosen.consumed_before, "rate": chosen.rate,
                "supplier": plain(dataclasses.asdict(master.suppliers[chosen.contract.supplier_id]))} if chosen else {}),
        },
        "history": (history_facts(req.item_code, req.requirement_date, master, params) if item else
                    {"bought_from_active": False, "po_count": 0, "active_po_count": 0, "distinct_active_suppliers": 0}),
        "preferred": {
            "list_size": len(preferred),
            "rank1": ({**plain(dataclasses.asdict(master.suppliers[rank1.supplier_id])),
                       "reference_price": rank1.reference_price} if rank1 else None),
        },
    }
    return facts
