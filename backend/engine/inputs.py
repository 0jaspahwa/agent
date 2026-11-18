"""The engine's inputs as plain, frozen dataclasses (standard library only).

The engine never reads files or the database. A loader builds these objects (loaders/kit.py from the kit
CSVs, loaders/database.py from Postgres), and a test proves both give identical objects for the kit.
Money, rates and quantities are Decimal, never float. PR timestamps are naive, exactly as given.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Item:
    item_code: str
    description: str
    uom: str
    category: str
    item_type: str
    standard_price: Decimal


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    city: str
    categories: tuple[str, ...]
    status: str
    on_time_pct: Decimal
    quality_rating: Decimal


@dataclass(frozen=True)
class Plant:
    plant: str
    name: str


@dataclass(frozen=True)
class HistoricalPO:
    po_number: str
    po_date: date
    supplier_id: str
    item_code: str
    quantity: Decimal
    uom: str
    unit_price: Decimal
    plant: str
    delivered_on_time: bool


@dataclass(frozen=True)
class ContractLine:
    item_code: str
    description: str
    uom: str
    rate: Decimal


@dataclass(frozen=True)
class Contract:
    contract_id: str
    supplier_id: str
    supplier_name: str
    start_date: date
    end_date: date
    value_cap: Decimal
    consumed_value: Decimal  # the run's starting baseline: register value as at consumed_as_of, else 0
    consumed_as_of: date | None
    source: str  # register | pdf | manual
    lines: tuple[ContractLine, ...]  # sorted by item_code


@dataclass(frozen=True)
class PRLine:
    pr_no: str
    pr_line: str  # exactly as given; ordering uses its numeric value (engine.lines.line_order_key)
    created_at: datetime | None  # None when unreadable: that line is NOT_PROCESSED, the batch is not
    requester: str | None
    department: str | None
    plant: str
    item_code: str | None
    description: str
    quantity: Decimal | None  # None when blank or unreadable (line check V6 reports it)
    uom: str | None
    estimated_unit_price: Decimal | None
    need_by_date: date | None
    urgency: str | None
    source: str = "batch"  # batch | chat


@dataclass(frozen=True)
class PolicyVersion:
    version: str
    effective_from: date
    document: dict
    # When it was approved: breaks ties between versions with the same effective_from. Not compared,
    # because the kit file has no approval time; the database records the real one.
    approved_at: datetime | None = field(default=None, compare=False)


@dataclass(frozen=True)
class MasterData:
    items: dict[str, Item]
    suppliers: dict[str, Supplier]
    plants: dict[str, Plant]
    po_history: tuple[HistoricalPO, ...]  # sorted by (po_date, po_number)
    contracts: tuple[Contract, ...]  # sorted by contract_id
    policies: tuple[PolicyVersion, ...]  # approved versions, sorted by (effective_from, version)
