"""Smoke test: the app starts (creating and seeding a database) and the health endpoint answers, with the kit in
data/ and without it (the kit is not in the repo)."""
from fastapi.testclient import TestClient

import engine  # noqa: F401  (the engine package imports on its own)
from kit_required import needs_kit
from kitdata import NO_KIT_NOTICE
from main import app


def health(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'smoke.db'}")
    with TestClient(app) as client:  # the with-block runs the startup (create tables, seed)
        response = client.get("/api/health")
    assert response.status_code == 200
    return response.json()


@needs_kit
def test_health(monkeypatch, tmp_path):
    body = health(monkeypatch, tmp_path)
    assert body["status"] == "ok" and body["kit_loaded"] is True and "notice" not in body
    assert body["rows"] == {"items": 73, "suppliers": 48, "po_history": 468, "contracts": 12, "policy_versions": 1}


def test_health_without_the_kit(monkeypatch, tmp_path):
    import db.seed
    import main
    monkeypatch.setattr(db.seed, "DATA_DIR", tmp_path / "nodata")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "nodata")
    body = health(monkeypatch, tmp_path)
    assert body["status"] == "ok" and body["kit_loaded"] is False and body["notice"] == NO_KIT_NOTICE
    assert body["rows"] == {"items": 0, "suppliers": 0, "po_history": 0, "contracts": 0, "policy_versions": 1}
