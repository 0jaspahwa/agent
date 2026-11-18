"""RESET_DB_ON_START: one deploy after a schema change drops every table, recreates them and reseeds."""
import logging

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from db.models import PolicyVersion, Run
from kitdata import DATA_DIR

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")


def counts(engine):
    with engine.connect() as c:
        return (c.execute(select(func.count()).select_from(Run)).scalar(),
                c.execute(select(func.count()).select_from(PolicyVersion)).scalar())


def test_reset_drops_everything_and_reseeds_and_says_so(db_engine, monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", db_engine.url.render_as_string(hide_password=False))
    from main import app
    with TestClient(app) as client:
        client.post("/api/process-batch", content=SAMPLE)
        client.post("/api/policies/drafts", json={"from_current": True}, headers={"x-user": "a", "x-role": "Procurement"})
    assert counts(db_engine) == (1, 2)

    monkeypatch.setenv("RESET_DB_ON_START", "true")
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"), TestClient(app) as client:
        assert client.get("/api/health").json()["rows"]["items"] == 73
    assert counts(db_engine) == (0, 1)  # runs and drafts gone; v5.0 reseeded
    assert "dropped every table" in caplog.text and "Set it back to false" in caplog.text


def test_reset_also_replaces_an_older_schema(db_engine, monkeypatch):
    with db_engine.begin() as c:  # a table from an older version, with a column the current model lacks
        c.execute(text("CREATE TABLE policy_versions (id INTEGER PRIMARY KEY, old_column TEXT)"))
    monkeypatch.setenv("DATABASE_URL", db_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("RESET_DB_ON_START", "true")
    from main import app
    with TestClient(app) as client:
        assert client.get("/api/policies").json()[0]["version"] == "5.0"


def test_without_the_flag_nothing_is_dropped(db_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_engine.url.render_as_string(hide_password=False))
    monkeypatch.delenv("RESET_DB_ON_START", raising=False)
    from main import app
    with TestClient(app) as client:
        client.post("/api/process-batch", content=SAMPLE)
    with TestClient(app):
        pass
    assert counts(db_engine)[0] == 1
