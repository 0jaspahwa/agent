"""F4: turn the deciding rule's `then` into a supplier and price, or a ranked suggestion list.

contract_supplier -> the contract 4.3 chose, at its rate; preferred_rank_1 -> the 1st preferred supplier
whose status may receive a PO, at its reference price (6.3); suggest -> the preferred list in order (status
allowed to be suggested), topped up from the item's category by delivery and quality (6.4), never padded
(D9); none -> no supplier. Returns None when a PO cannot be placed (no contract or no eligible supplier).
"""
from dataclasses import dataclass
from decimal import Decimal

from engine.contracts import number_text
from engine.preferred import topup_suppliers


@dataclass(frozen=True)
class Outcome:
    rule: dict
    decision: str
    route: str
    supplier_id: str | None
    unit_price: Decimal | None
    price_note: str  # where the price came from
    suggestions: tuple[str, ...]
    suggest_requested: int
    uses_contract: object = None  # the ContractOption whose ceiling this consumes

    @property
    def is_po(self):
        return self.decision == "PO"


def apply_outcome(rule, req, choice, preferred, master, params):
    then = rule["then"]
    statuses = params["suppliers"]["allowed_statuses"]
    base = dict(rule=rule, decision=then["decision"], route=then["route"], suggest_requested=then["suggest_count"])
    if then["supplier"] == "contract_supplier":
        o = choice.chosen if choice else None
        if not o or master.suppliers[o.contract.supplier_id].status not in statuses["receive_po"]:
            return None
        return Outcome(**base, supplier_id=o.contract.supplier_id, unit_price=o.rate,
                       price_note=f"rate of {o.contract.contract_id}", suggestions=(), uses_contract=o)
    if then["supplier"] == "preferred_rank_1":
        top = next((r for r in preferred if master.suppliers[r.supplier_id].status in statuses["receive_po"]), None)
        if not top or top.reference_price is None:
            return None
        return Outcome(**base, supplier_id=top.supplier_id, unit_price=top.reference_price,
                       price_note=f"1st preferred supplier (score {number_text(top.score)}), reference price from {top.reference}",
                       suggestions=())
    if then["supplier"] == "suggest":
        listed = [r.supplier_id for r in preferred if master.suppliers[r.supplier_id].status in statuses["be_suggested"]]
        picks = listed[:then["suggest_count"]]
        if len(picks) < then["suggest_count"] and req.item_code:
            extra = topup_suppliers(req.item_code, master, params, statuses["be_suggested"], exclude=set(picks))
            picks += [sid for sid, _, _ in extra][:then["suggest_count"] - len(picks)]
        return Outcome(**base, supplier_id=None, unit_price=None, price_note="", suggestions=tuple(picks))
    return Outcome(**base, supplier_id=None, unit_price=None, price_note="", suggestions=())
