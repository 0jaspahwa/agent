"""F1: rate contracts (policy 4), with a running ceiling per contract for one run.

Applicable (4.1): the contract covers the item, the requirement date is within its validity (both ends per
contracts.validity) and its supplier's status is in suppliers.allowed_statuses.hold_applicable_contract.
Usable (4.2, 4.3): taking applicable contracts from the lowest rate up (same rate: the one ending first,
then contract id; D23), the first whose consumed value plus this requirement's value at its rate passes
contracts.ceiling. The ceiling book starts from the run's baseline and is shared by all of a contract's
items; the engine consumes it only when the deciding rule actually uses the contract.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")
COMPARE = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b}


def money(value):
    """Round half up to paise (D11)."""
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


def number_text(value):
    """A number as its shortest exact text (61, 365, 41415.6, 9168.71), however it was stored: the kit file
    says 365 and the database returns 365.00, so both paths print the same (D16)."""
    return format(Decimal(value).normalize(), "f")


@dataclass(frozen=True)
class ContractOption:
    contract: object  # engine.inputs.Contract
    rate: Decimal
    value: Decimal  # this requirement's value at this contract's rate
    consumed_before: Decimal
    fits: bool

    @property
    def remaining_before(self):
        return self.contract.value_cap - self.consumed_before


@dataclass(frozen=True)
class ContractChoice:
    applicable: tuple[ContractOption, ...]  # in selection order
    chosen: ContractOption | None  # the contract that would be used (4.3), if any has room

    @property
    def lowest_rate(self):
        return min((o.rate for o in self.applicable), default=None)

    @property
    def lowest(self):
        return self.applicable[0] if self.applicable else None


class CeilingBook:
    """Consumed value per contract during one run, starting from the run's baseline."""

    def __init__(self, contracts):
        self.consumed = {c.contract_id: c.consumed_value for c in contracts}

    def consume(self, contract_id, value):
        self.consumed[contract_id] += value

    def snapshot(self):
        return dict(self.consumed)


def _valid_on(contract, on_date, validity):
    after_start = on_date >= contract.start_date if validity["start_inclusive"] else on_date > contract.start_date
    before_end = on_date <= contract.end_date if validity["end_inclusive"] else on_date < contract.end_date
    return after_start and before_end


def applicable_contracts(item_code, on_date, master, params):
    """[(contract, rate)] that apply to the item on the date (4.1), in selection order."""
    statuses = params["suppliers"]["allowed_statuses"]["hold_applicable_contract"]
    found = []
    for contract in master.contracts:
        line = next((l for l in contract.lines if l.item_code == item_code), None)
        supplier = master.suppliers.get(contract.supplier_id)
        if line and supplier and supplier.status in statuses and _valid_on(contract, on_date, params["contracts"]["validity"]):
            found.append((contract, line.rate))
    return sorted(found, key=lambda cr: (cr[1], cr[0].end_date, cr[0].contract_id))


def choose_contract(item_code, on_date, quantity, master, params, book):
    if params["contracts"]["selection"] != "lowest_rate_with_ceiling":
        raise ValueError(f"unknown contracts.selection {params['contracts']['selection']!r}")
    fits = COMPARE[params["contracts"]["ceiling"]["operator"]]
    options = []
    for contract, rate in applicable_contracts(item_code, on_date, master, params):
        value = money(quantity * rate)
        consumed = book.consumed[contract.contract_id]
        options.append(ContractOption(contract, rate, value, consumed, fits(consumed + value, contract.value_cap)))
    chosen = next((o for o in options if o.fits), None)
    return ContractChoice(tuple(options), chosen)
