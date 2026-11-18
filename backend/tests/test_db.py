"""Database tests (B2): schema, idempotent seed, types, keys, and the append-only rules."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from db.models import (AuditLog, BuyerAction, Contract, Decision, Item, PolicyVersion, PrBatch, PrLine,
                       Requirement, Run, Supplier)
from db.seed import seed
from db.session import make_session_factory

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

KIT_COUNTS = {"items": 73, "suppliers": 48, "plants": 2, "po_history": 468, "contracts": 12,
              "contract_lines": 31, "policy_versions": 1}


def test_seed_loads_the_kit_and_is_safe_to_run_twice(db_engine):
    assert seed(db_engine) == KIT_COUNTS
    assert seed(db_engine) == KIT_COUNTS  # nothing duplicated, nothing changed


def test_money_is_exact_decimal_and_values_match_the_kit(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        assert s.get(Item, "ITM-1002").standard_price == Decimal("9900.00")
        c = s.get(Contract, "RC-2026-002")
        assert (c.value_cap, c.consumed_value, c.consumed_as_of, c.source) == (
            Decimal("1200000.00"), Decimal("1162000.00"), date(2026, 10, 31), "register")
        assert s.get(Supplier, "S020").categories == ["Electrical Spares", "Capital Equipment"]
        v5 = s.scalars(select(PolicyVersion)).one()
        assert (v5.version, v5.status, v5.effective_from, v5.document["rules"][0]["id"]) == (
            "5.0", "approved", date(2026, 4, 1), "1.2")


def _run_with_line(s):
    batch = PrBatch(filename="b.csv", csv_text="x", csv_sha256="h", line_count=1, uploaded_by="test")
    s.add(batch)
    s.flush()
    line = PrLine(source="batch", batch_id=batch.id, pr_no="PR-1", pr_line="1", created_at=datetime(2026, 11, 4, 12, 40),
                  plant="PUN2", description="x", quantity=Decimal("0"), raw={"plant": "PUN2"}, created_by="test")
    run = Run(kind="batch", batch_id=batch.id, policy_version_ids=[1], inputs={}, inputs_sha256="h",
              engine_version="test", status="done", started_by="test")
    s.add_all([line, run])
    s.flush()
    return run, line


def _decision(run, line, **kw):
    cols = dict(pr_no="PR-1", pr_line="1", resolved_item_code="", group_id="", po_id="", decision="",
                route="NOT_PROCESSED", supplier_id="", unit_price="", group_value_inr="",
                suggested_supplier_ids="", policy_version="5.0", reason="Plant is not in the plant master")
    return Decision(run_id=run.id, pr_line_id=line.id, row_order=1, **{**cols, **kw})


def test_pr_created_at_is_stored_exactly_and_unknown_plants_are_kept(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        _run, line = _run_with_line(s)
        s.commit()
        stored = s.get(PrLine, line.id)
        assert stored.created_at == datetime(2026, 11, 4, 12, 40) and stored.created_at.tzinfo is None
        assert stored.plant == "PUN2"  # not a foreign key: invalid lines are stored and reported


def test_exactly_one_decision_per_pr_line_per_run(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        run, line = _run_with_line(s)
        s.add(_decision(run, line))
        s.commit()
        s.add(_decision(run, line, reason="a second row"))
        with pytest.raises(IntegrityError):
            s.commit()


def _requirement(s, run):
    req = Requirement(run_id=run.id, group_id="R-0001", item_code="ITM-1002", plant="PUN1",
                      requirement_date=date(2026, 11, 4), first_created_at=datetime(2026, 11, 4, 12, 40),
                      total_quantity=Decimal("15"), value_inr=Decimal("137530.65"), valuation_source="contract_to_be_used",
                      policy_version_id=1, rule_id="5.2", decision="PO", route="CONTRACT_PO", supplier_id="S001",
                      unit_price=Decimal("9168.71"), suggested_supplier_ids=[], contract_id="RC-2025-011",
                      relied_on={}, reason="5.2")
    s.add(req)
    s.flush()
    return req


def test_override_needs_a_comment(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        req = _requirement(s, _run_with_line(s)[0])
        s.add(BuyerAction(requirement_id=req.id, action="override", new_route="RFQ", actor="Asha", actor_role="Buyer"))
        with pytest.raises(IntegrityError):
            s.commit()


@pytest.mark.parametrize("table", [AuditLog, BuyerAction])
def test_append_only_tables_reject_update_and_delete(db_engine, table):
    seed(db_engine)
    Session = make_session_factory(db_engine)
    with Session() as s:
        if table is AuditLog:
            s.add(AuditLog(actor="Asha", actor_role="Buyer", action="buyer.approve", entity_type="requirement",
                           entity_id="1", details={}))
        else:
            req = _requirement(s, _run_with_line(s)[0])
            s.add(BuyerAction(requirement_id=req.id, action="approve", actor="Asha", actor_role="Buyer"))
        s.commit()
    for statement in (update(table).values(actor="someone else"), delete(table)):
        with Session() as s, pytest.raises(DBAPIError, match="append-only"):
            s.execute(statement)
            s.commit()
    with Session() as s:
        assert s.scalars(select(table)).one().actor == "Asha"


def test_status_values_are_checked(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s, pytest.raises(IntegrityError):
        s.execute(update(Supplier).where(Supplier.supplier_id == "S001").values(status="Gold"))
        s.commit()


@pytest.mark.parametrize("given, used", [
    ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),        # Render / Heroku style
    ("postgresql://u:p@host/db?sslmode=require", "postgresql+psycopg://u:p@host/db?sslmode=require"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_hosted_database_urls_get_the_psycopg_driver(given, used):
    from db.session import database_url
    assert database_url(given) == used
