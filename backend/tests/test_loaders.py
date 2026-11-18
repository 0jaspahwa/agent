"""B3: the kit loader and the database loader give identical engine inputs for the kit data."""
import dataclasses
from datetime import datetime
from decimal import Decimal

from db.ingest import ingest_batch
from db.seed import seed
from db.session import make_session_factory
from kitdata import DATA_DIR
from loaders import database, kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = DATA_DIR / "pr_batches" / "sample_pr_batch.csv"


def _no_floats(obj):
    """Walk dataclasses, dicts and tuples; fail on any float (money must be Decimal)."""
    if isinstance(obj, float):
        raise AssertionError(f"float found: {obj!r}")
    if dataclasses.is_dataclass(obj):
        for f in dataclasses.fields(obj):
            if f.name != "document":  # the policy JSON legitimately holds floats (e.g. scores 0.5)
                _no_floats(getattr(obj, f.name))
    elif isinstance(obj, dict):
        for v in obj.values():
            _no_floats(v)
    elif isinstance(obj, (tuple, list)):
        for v in obj:
            _no_floats(v)


def test_both_loaders_give_identical_master_data(db_engine):
    seed(db_engine)
    from_kit = kit.load_master()
    with make_session_factory(db_engine)() as s:
        from_db = database.load_master(s)
    for part in ("items", "suppliers", "plants", "po_history", "contracts", "policies"):
        assert getattr(from_db, part) == getattr(from_kit, part), part
    assert from_db == from_kit
    assert (len(from_kit.items), len(from_kit.suppliers), len(from_kit.po_history), len(from_kit.contracts)) == (73, 48, 468, 12)
    _no_floats(from_kit)
    _no_floats(from_db)
    assert from_db.policies[0].approved_at is not None  # recorded in the database, not in the kit file


def test_both_loaders_give_identical_pr_lines(db_engine):
    seed(db_engine)
    from_kit = kit.load_pr_batch(SAMPLE)
    with make_session_factory(db_engine)() as s:
        batch = ingest_batch(s, SAMPLE.name, SAMPLE.read_text(encoding="utf-8"), "test")
        s.commit()
        from_db = database.load_pr_lines(s, batch.id)
    assert len(from_kit) == 186
    assert from_db == from_kit
    _no_floats(from_db)


def test_pr_line_values_are_parsed_exactly():
    lines = {(l.pr_no, l.pr_line): l for l in kit.load_pr_batch(SAMPLE)}
    first = lines[("PR-26-00019", "1")]  # worked example 1
    assert first.created_at == datetime(2026, 11, 4, 12, 40) and first.created_at.tzinfo is None
    assert (first.item_code, first.quantity, first.urgency) == ("ITM-1002", Decimal("15"), "Normal")
    free_text = lines[("PR-26-00004", "1")]  # worked example 3: free text, no item code
    assert (free_text.item_code, free_text.description) == (None, "brg 6308 ZZ for maintenance")
    assert free_text.estimated_unit_price == Decimal("715.25")
    assert lines[("PR-26-00001", "1")].estimated_unit_price is None  # a blank estimate stays blank
    assert lines[("PR-26-00172", "1")].quantity == Decimal("0")  # kept, reported later as NOT_PROCESSED
    assert lines[("PR-26-00173", "1")].plant == "PUN2"
