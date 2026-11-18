"""F2: value a requirement (policy 3.1; new items 1.2), following valuation.price_sources in order.

Sources: contract_to_be_used (the contract 4.3 picks), lowest_applicable_contract_rate (only when contracts
apply but every one is out of ceiling), latest_po_in_window (D1, D2), standard_price. A new item is valued
at quantity x the requester's estimate, blank if there is none (D12). Values are rounded half up to paise.
"""
from dataclasses import dataclass
from decimal import Decimal

from engine.contracts import money
from engine.history import valuation_po


@dataclass(frozen=True)
class Valuation:
    unit_price: Decimal | None
    value: Decimal | None
    source: str  # one of valuation.price_sources, or requester_estimate
    reference: str | None  # contract id or PO number it came from
    note: str


def value_requirement(requirement, choice, master, params):
    qty = requirement.total_quantity
    if requirement.is_new:
        if params["valuation"]["new_item_price"] != "requester_estimate":
            raise ValueError(f"unknown valuation.new_item_price {params['valuation']['new_item_price']!r}")
        price = requirement.first.line.estimated_unit_price
        if price is None:
            return Valuation(None, None, "requester_estimate", None, "new item without an estimated price (D12)")
        return Valuation(price, money(qty * price), "requester_estimate", None, "new item at the requester's estimate (1.2)")
    for source in params["valuation"]["price_sources"]:
        if source == "contract_to_be_used" and choice.chosen:
            o = choice.chosen
            return Valuation(o.rate, money(qty * o.rate), source, o.contract.contract_id,
                             f"rate of {o.contract.contract_id}, the contract to be used (3.1a)")
        if source == "lowest_applicable_contract_rate" and choice.applicable and not choice.chosen:
            o = choice.lowest
            return Valuation(o.rate, money(qty * o.rate), source, o.contract.contract_id,
                             f"lowest applicable contract rate, {o.contract.contract_id}; every applicable "
                             f"contract is out of ceiling (3.1a)")
        if source == "latest_po_in_window":
            po = valuation_po(requirement.item_code, requirement.requirement_date, master, params)
            if po:
                return Valuation(po.unit_price, money(qty * po.unit_price), source, po.po_number,
                                 f"latest PO {po.po_number} ({po.po_date}, {po.supplier_id}) in the valuation window (3.1b)")
        if source == "standard_price":
            price = master.items[requirement.item_code].standard_price
            return Valuation(price, money(qty * price), source, None, "item master standard price (3.1c)")
    raise ValueError(f"no valuation source applied to {requirement.group_id}")
