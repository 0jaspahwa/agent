"""Shared fixtures. Database tests run on SQLite by default (no setup needed) and also on Postgres when
TEST_DATABASE_URL is set, e.g. postgresql+psycopg://corvo:corvo@localhost:5433/corvo_test
(start one with: docker compose -f docker-compose.test.yml up -d)."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import close_all_sessions

from db.models import Base
from db.session import make_engine

BACKENDS = ["sqlite"] + (["postgres"] if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def db_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    else:
        engine = make_engine(os.environ["TEST_DATABASE_URL"])
        with engine.begin() as conn:  # start from an empty schema every test
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    yield engine
    if request.param == "postgres":
        # A session a test left open holds its locks, and DROP TABLE would wait for it forever (on Postgres only).
        close_all_sessions()
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_engine, monkeypatch):
    """The app on a fresh, seeded database of the same backend as db_engine."""
    monkeypatch.setenv("DATABASE_URL", db_engine.url.render_as_string(hide_password=False))
    from main import app
    with TestClient(app) as c:
        yield c

