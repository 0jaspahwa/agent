"""Build the engine's inputs from the database. Must give exactly what loaders/kit.py gives for the kit."""
from sqlalchemy import select

from db.models import Contract, ContractLine, Item, Plant, PoHistory, PolicyVersion, PrLine, Supplier
from engine import inputs


def load_master(session):
    items = {r.item_code: inputs.Item(r.item_code, r.description, r.uom, r.category, r.item_type, r.standard_price)
             for r in session.scalars(select(Item))}
    suppliers = {r.supplier_id: inputs.Supplier(r.supplier_id, r.name, r.city, tuple(r.categories), r.status,
                                                r.on_time_pct, r.quality_rating)
                 for r in session.scalars(select(Supplier))}
    plants = {r.plant: inputs.Plant(r.plant, r.name) for r in session.scalars(select(Plant))}
    history = tuple(inputs.HistoricalPO(r.po_number, r.po_date, r.supplier_id, r.item_code, r.quantity, r.uom,
                                        r.unit_price, r.plant, r.delivered_on_time)
                    for r in session.scalars(select(PoHistory).order_by(PoHistory.po_date, PoHistory.po_number)))
    lines = {}
    for r in session.scalars(select(ContractLine).order_by(ContractLine.item_code)):
        lines.setdefault(r.contract_id, []).append(inputs.ContractLine(r.item_code, r.description, r.uom, r.rate))
    contracts = tuple(
        inputs.Contract(r.contract_id, r.supplier_id, r.supplier_name, r.start_date, r.end_date, r.value_cap,
                        r.consumed_value, r.consumed_as_of, r.source, tuple(lines.get(r.contract_id, [])))
        for r in session.scalars(select(Contract).order_by(Contract.contract_id)))
    policies = tuple(
        inputs.PolicyVersion(r.version, r.effective_from, r.document, r.approved_at)
        for r in session.scalars(select(PolicyVersion).where(PolicyVersion.status == "approved")
                                 .order_by(PolicyVersion.effective_from, PolicyVersion.approved_at)))
    return inputs.MasterData(items, suppliers, plants, history, contracts, policies)


def _line(r):
    return inputs.PRLine(r.pr_no, r.pr_line, r.created_at, r.requester, r.department, r.plant, r.item_code,
                         r.description, r.quantity, r.uom, r.estimated_unit_price, r.need_by_date, r.urgency, r.source)


def load_pr_lines(session, batch_id):
    """The PR lines of one uploaded batch, in file order."""
    return tuple(_line(r) for r in session.scalars(select(PrLine).where(PrLine.batch_id == batch_id).order_by(PrLine.id)))


def load_lines(session, ids):
    """These PR lines (chat lines), in the order of `ids`."""
    by_id = {r.id: r for r in session.scalars(select(PrLine).where(PrLine.id.in_(ids)))}
    return tuple(_line(by_id[i]) for i in ids)
