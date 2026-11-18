"""F6: the whole decision for a PR batch. Pure and deterministic: dataclasses in, plain results out.

decide(pr_lines, master, contracts=None, policies=None):
  E1 check every line -> E2 match its item -> E3 club lines into requirements -> for each requirement, in
  order of its first line's creation: F1 choose a contract (running ceiling) -> F2 value it -> F3 rank the
  preferred suppliers -> F4 build the facts, run the policy's ordered rules and apply the outcome (the
  ceiling is consumed only when the deciding rule uses the contract) -> F5 consolidate POs -> one row per
  PR line in the brief's export format, with a reason sentence.
"""
import dataclasses
from dataclasses import dataclass

from engine.clubbing import club
from engine.consolidation import Entry, consolidate
from engine.contracts import CeilingBook, choose_contract, number_text
from engine.outcome import apply_outcome
from engine.policy import decide as run_rules
from engine.preferred import preferred_list
from engine.requirement_facts import requirement_facts
from engine.validation import check_lines
from engine.valuation import value_requirement

EXPORT_COLUMNS = ["pr_no", "pr_line", "resolved_item_code", "group_id", "po_id", "decision", "route", "supplier_id",
                  "unit_price", "group_value_inr", "suggested_supplier_ids", "policy_version", "reason"]


@dataclass
class DecidedRequirement:
    requirement: object  # engine.clubbing.Requirement
    choice: object  # engine.contracts.ContractChoice, None for a new item
    valuation: object  # engine.valuation.Valuation
    preferred: tuple  # engine.preferred.RankedSupplier, in rank order
    outcome: object  # engine.outcome.Outcome
    missing: dict  # fields that had no value while the rules were evaluated
    notes: list  # e.g. a PO rule skipped because no supplier could be determined (D25)
    po_id: str = ""


@dataclass(frozen=True)
class Row:
    index: int  # position in the input batch
    values: dict  # the 13 export columns, as text

    def __getitem__(self, column):
        return self.values[column]


@dataclass(frozen=True)
class BatchResult:
    rows: tuple[Row, ...]  # in input order
    requirements: tuple[DecidedRequirement, ...]  # in group id order
    purchase_orders: tuple  # engine.consolidation.PurchaseOrder
    ceiling_baseline: dict  # contract id -> consumed at the start of the run
    ceiling_final: dict  # contract id -> consumed at the end of the run


def _decide_requirement(req, master, book):
    params, document = req.params, req.version.document
    choice = None if req.is_new else choose_contract(req.item_code, req.requirement_date, req.total_quantity,
                                                     master, params, book)
    valuation = value_requirement(req, choice, master, params)
    preferred = () if req.is_new else preferred_list(req.item_code, req.requirement_date, master, params)
    facts = requirement_facts(req, choice, valuation, preferred, master, params)
    first_facts = req.first.facts or {}
    skip, notes = [], []
    while True:
        rule, _data, missing = run_rules(document, facts, {"line": first_facts.get("line"), "item": first_facts.get("item")}, skip)
        outcome = apply_outcome(rule, req, choice, preferred, master, params)
        if outcome:
            break
        skip.append(rule["id"])
        notes.append(f"{rule['id']} matched but no eligible supplier or contract could be found, so the next rule decided (D25)")
    if outcome.uses_contract:
        book.consume(outcome.uses_contract.contract.contract_id, outcome.uses_contract.value)
    return DecidedRequirement(req, choice, valuation, preferred, outcome, missing, notes)


def _money(value):
    return "" if value is None else f"{value:.2f}"


def _requirement_reason(d, checked):
    o, v, req = d.outcome, d.valuation, d.requirement
    parts = [f"{o.rule['id']} {o.rule['title']} (policy v{req.version.version})"]
    if o.uses_contract:
        c = o.uses_contract
        parts.append(f"contract {c.contract.contract_id} with {o.supplier_id} at its rate {number_text(o.unit_price)} "
                     f"({c.remaining_before - c.value:.2f} of its ceiling left after this)")
    elif o.decision == "PO":
        parts.append(f"{o.supplier_id} at {number_text(o.unit_price)}: {o.price_note}")
    elif o.suggestions:
        found = f"{len(o.suggestions)} of {o.suggest_requested}" if len(o.suggestions) < o.suggest_requested else "preferred list first, then category top-ups"
        parts.append(f"suggested {', '.join(o.suggestions)} ({found})")
    elif req.is_new:
        parts.append("new item: no item master match, so no suppliers are suggested (1.2, 6.4)")
    if v.value is None:
        parts.append(v.note)
    else:
        parts.append(f"value {v.value:.2f} = {number_text(req.total_quantity)} x {number_text(v.unit_price)}, {v.note}")
    if len(req.lines) > 1:
        parts.append(f"{len(req.lines)} PR lines clubbed from {req.requirement_date} (2.2)")
    if req.is_emergency:
        parts.append("emergency (a line is marked Emergency, 2.3)")
    if d.choice and d.choice.applicable and not d.choice.chosen and not o.uses_contract:
        parts.append(f"{', '.join(x.contract.contract_id for x in d.choice.applicable)} applies but lacks ceiling (4.2)")
    parts += d.notes
    if checked.match and checked.match.status == "description":
        parts.append(f"item matched from the description (score {checked.match.score})")
    if checked.match and checked.match.status == "ambiguous":
        parts.append(checked.match.explanation)
    parts += [f"note {f.id}: {f.text}" for f in checked.flags]
    missing = d.missing.get(o.rule["id"])
    if missing:
        parts.append(f"no value for {', '.join(missing)}")
    return "; ".join(parts)


def _row(checked, d):
    line = checked.line
    if not checked.processed:
        version = checked.version.version if checked.version else ""
        return {"pr_no": line.pr_no, "pr_line": line.pr_line, "resolved_item_code": checked.item_code or "",
                "group_id": "", "po_id": "", "decision": "", "route": "NOT_PROCESSED", "supplier_id": "",
                "unit_price": "", "group_value_inr": "", "suggested_supplier_ids": "", "policy_version": version,
                "reason": "Not processed: " + "; ".join(f"{f.id} {f.text}" for f in checked.not_processed)}
    o = d.outcome
    return {"pr_no": line.pr_no, "pr_line": line.pr_line, "resolved_item_code": d.requirement.item_code or "NEW",
            "group_id": d.requirement.group_id, "po_id": d.po_id, "decision": o.decision, "route": o.route,
            "supplier_id": o.supplier_id or "", "unit_price": "" if o.unit_price is None else number_text(o.unit_price),
            "group_value_inr": _money(d.valuation.value), "suggested_supplier_ids": ";".join(o.suggestions),
            "policy_version": d.requirement.version.version, "reason": _requirement_reason(d, checked)}


def decide(pr_lines, master, contracts=None, policies=None):
    if contracts is not None:
        master = dataclasses.replace(master, contracts=tuple(contracts))
    if policies is not None:
        master = dataclasses.replace(master, policies=tuple(policies))
    checked = check_lines(tuple(pr_lines), master)
    requirements = club(checked, master)
    book = CeilingBook(master.contracts)
    baseline = book.snapshot()
    decided = [_decide_requirement(req, master, book) for req in requirements]  # group ids are in creation order

    entries = []
    for d in decided:
        if d.outcome.is_po:
            first = d.requirement.first
            key = {"supplier_id": d.outcome.supplier_id, "plant": d.requirement.plant, "route": d.outcome.route,
                   "decision": d.outcome.decision, **{k: v for k, v in (first.facts or {}).get("line", {}).items()
                                                      if k not in ("plant", "route")}}
            entries.append(Entry(d.requirement.group_id, d.requirement.created_at, key,
                                 d.requirement.params["consolidation"]))
    pos = consolidate(entries)
    po_of = {gid: po.po_id for po in pos for gid in po.group_ids}
    for d in decided:
        d.po_id = po_of.get(d.requirement.group_id, "")

    by_index = {c.index: d for d in decided for c in d.requirement.lines}
    rows = tuple(Row(c.index, _row(c, by_index.get(c.index))) for c in checked)
    return BatchResult(rows, tuple(decided), tuple(pos), baseline, book.snapshot())
