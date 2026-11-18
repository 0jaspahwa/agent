"""B1: the React interface is served at /, without hiding the API, the operations pages or the API docs."""
import pytest

from api import spa


@pytest.fixture
def built(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root>interface</div>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(spa, "DIST", tmp_path)
    return tmp_path


def test_every_screen_path_returns_the_interface(client, built):
    for path in ("/", "/workspace", "/policies/3", "/chat"):
        r = client.get(path)
        assert r.status_code == 200 and "interface" in r.text, path
    assert client.get("/favicon.svg").text == "<svg/>"


def test_the_api_ops_pages_and_docs_are_not_hidden(client, built):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "Process a PR batch" in client.get("/ops").text
    assert client.get("/docs").status_code == 200
    missing = client.get("/api/no-such-thing")
    assert missing.status_code == 404 and "interface" not in missing.text


def test_without_a_build_the_root_points_to_the_operations_pages(client, tmp_path, monkeypatch):
    monkeypatch.setattr(spa, "DIST", tmp_path / "missing")
    r = client.get("/")
    assert r.status_code == 200 and "/ops" in r.text and "has not been built" in r.text


def test_files_outside_the_build_are_never_served(client, built):
    assert "interface" in client.get("/../backend/main.py").text  # falls back to the interface, not the file
