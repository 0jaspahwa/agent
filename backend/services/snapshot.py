"""Turn engine inputs into plain JSON for the run snapshot, and hash it (docs/data_model.md, runs.inputs)."""
import dataclasses
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal


def plain(value):
    """Dataclasses, Decimals (as exact text), dates and tuples -> JSON-ready values."""
    if dataclasses.is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    return value


def run_inputs(lines, master, result):
    """Everything the run read: the batch's lines, master data, contracts with the baseline it started
    from, and every policy version that was available to it. (The batch itself is runs.batch_id; it is
    left out here so the same file processed twice hashes the same.)"""
    return {
        "lines": plain(lines),
        "items": plain(list(master.items.values())),
        "suppliers": plain(list(master.suppliers.values())),
        "plants": plain(list(master.plants.values())),
        "po_history": plain(master.po_history),
        "contracts": plain(master.contracts),
        "contract_baseline": plain(result.ceiling_baseline),
        "policies": plain(master.policies),
    }


def sha256_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()
