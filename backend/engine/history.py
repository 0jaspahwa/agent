"""PO history helpers: which POs fall in a window (D3, D8), the most recent one (D1), and the history facts
the rules can read (fact catalogue history.*)."""
from datetime import timedelta


def in_window(po_date, on_date, window):
    """Is po_date within `length` days before on_date? Far end per `inclusive`; the reference date itself
    only if include_reference_date (D3: it is not)."""
    start = on_date - timedelta(days=window["length"])
    after_start = po_date >= start if window["inclusive"] else po_date > start
    before_end = po_date <= on_date if window.get("include_reference_date") else po_date < on_date
    return after_start and before_end


def po_number_key(po):
    return (0, int(po.po_number), "") if po.po_number.isdigit() else (1, 0, po.po_number)


def most_recent(pos):
    """The latest PO by date; on a same-date tie the highest PO number (D1)."""
    return max(pos, key=lambda p: (p.po_date, po_number_key(p)), default=None)


def pos_in_window(item_code, on_date, master, window, statuses=None, supplier_id=None):
    """POs for the item in the window, optionally only from suppliers with these statuses or one supplier."""
    return [p for p in master.po_history
            if p.item_code == item_code and in_window(p.po_date, on_date, window)
            and (statuses is None or master.suppliers[p.supplier_id].status in statuses)
            and (supplier_id is None or p.supplier_id == supplier_id)]


def valuation_po(item_code, on_date, master, params):
    """The PO 3.1(b) uses: most recent in the valuation window; any supplier if
    valuation.include_non_active_suppliers (D2), else only purchase-history statuses."""
    statuses = None if params["valuation"]["include_non_active_suppliers"] else \
        params["suppliers"]["allowed_statuses"]["count_for_purchase_history"]
    if params["valuation"]["tie_break"] != "highest_po_number":
        raise ValueError(f"unknown valuation.tie_break {params['valuation']['tie_break']!r}")
    return most_recent(pos_in_window(item_code, on_date, master, params["history"]["valuation_window"], statuses))


def history_facts(item_code, on_date, master, params):
    """history.* facts of the fact catalogue for one requirement."""
    window = params["history"]["purchase_window"]
    allowed = params["suppliers"]["allowed_statuses"]["count_for_purchase_history"]
    all_pos = pos_in_window(item_code, on_date, master, window)
    active = [p for p in all_pos if master.suppliers[p.supplier_id].status in allowed]
    ever = [p for p in master.po_history if p.item_code == item_code and p.po_date < on_date]
    last_ever = most_recent(ever)
    latest = valuation_po(item_code, on_date, master, params)
    return {
        "bought_from_active": bool(active),
        "po_count": len(all_pos),
        "active_po_count": len(active),
        "distinct_active_suppliers": len({p.supplier_id for p in active}),
        "days_since_last_po": (on_date - last_ever.po_date).days if last_ever else None,
        "latest_po_price": latest.unit_price if latest else None,
        "latest_po_number": latest.po_number if latest else None,
        "latest_po_date": latest.po_date.isoformat() if latest else None,
        "latest_po_supplier_id": latest.supplier_id if latest else None,
    }
