"""Save the real API's responses as fixtures for the frontend's render tests (frontend/src/test/fixtures/).

Three states: "nokit" (the app started without the task kit, which is not in the repo), "empty" (the kit then
loaded through POST /api/admin/load-kit, nothing processed) and "sample" (the sample batch processed, one chat
request created, one requirement approved). Needs the kit in data/. Each screen's test renders from both, so "every screen
renders on an empty database and on the sample batch" is checked against what the server really returns.
No LLM is used. Re-run after changing an API:

    python scripts/make_ui_fixtures.py
"""
import io
import json
import os
import zipfile
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "frontend" / "src" / "test" / "fixtures"
BUYER = {"x-user": "Ravi", "x-role": "Buyer"}
REQUESTER = {"x-user": "Meera", "x-role": "Requester"}
PROCUREMENT = {"x-user": "Asha", "x-role": "Procurement"}

# (fixture name, path, headers): one GET per screen's data
GETS = [
    ("health", "/api/health", BUYER),
    ("workspace_runs", "/api/workspace/runs", BUYER),
    ("workspace", "/api/workspace", BUYER),
    ("workspace_chat", "/api/workspace?kind=chat", BUYER),
    ("my_requests", "/api/chat/requests", REQUESTER),
    ("suppliers", "/api/suppliers", BUYER),
    ("runs", "/api/runs", BUYER),
    ("policies", "/api/policies", PROCUREMENT),
    ("policy_1", "/api/policies/1", PROCUREMENT),
    ("contracts", "/api/contracts", BUYER),
    ("items", "/api/items", BUYER),
    ("preferred", "/api/preferred-suppliers?item_code=ITM-1048&as_of=2026-11-01", BUYER),
    ("audit", "/api/audit", PROCUREMENT),
]


def dump(client, state):
    folder = OUT / state
    folder.mkdir(parents=True, exist_ok=True)
    for name, path, headers in GETS:
        r = client.get(path, headers=headers)
        if r.status_code == 404:
            continue  # an endpoint not built yet
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        (folder / f"{name}.json").write_text(json.dumps(r.json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {folder.relative_to(ROOT)}")


def main():
    tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # removed when the script ends
    tmp = tmp_dir.name
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'fixtures.db'}"
    os.environ["LLM_MODELS"], os.environ["LLM_MODEL"], os.environ["CHAT_LLM"] = "", "", "off"
    from fastapi.testclient import TestClient
    import db.seed
    import main as app_main
    from main import app
    from kitdata import DATA_DIR
    nodata = Path(tmp) / "nodata"  # start without the kit, then upload it like a Procurement user
    db.seed.DATA_DIR = app_main.DATA_DIR = nodata
    from services import chat
    from datetime import datetime
    chat.now = lambda: datetime(2026, 11, 17, 10, 30, tzinfo=chat.IST)  # fixed, so the fixtures do not churn
    with TestClient(app) as client:
        dump(client, "nokit")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for f in sorted(DATA_DIR.rglob("*")):
                if f.is_file():
                    z.writestr("Cantill_FullStack_Task_Kit/" + f.relative_to(DATA_DIR).as_posix(), f.read_bytes())
        loaded = client.post("/api/admin/load-kit", files={"kit": ("kit.zip", buf.getvalue())}, headers=PROCUREMENT)
        assert loaded.status_code == 200, loaded.text
        save("nokit", "kit_load", loaded.json())
        dump(client, "empty")
        sample = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
        client.post("/api/process-batch", content=sample)
        conv = client.post("/api/chat/conversations", headers=REQUESTER).json()["id"]
        client.post(f"/api/chat/conversations/{conv}/messages", headers=REQUESTER,
                    json={"text": "need 200 nitrile gloves for Chakan by next Friday"})
        client.post(f"/api/chat/conversations/{conv}/messages", headers=REQUESTER, json={"event": {"type": "create"}})
        view = client.get("/api/workspace", headers=BUYER).json()
        rfq = next(r for r in view["requirements"] if r["route"] == "RFQ" and not r["po"])
        client.post(f"/api/requirements/{rfq['id']}/approve", headers=BUYER,
                    json={"versions": {str(rfq["id"]): rfq["version"]}})
        # a ready draft (by hand: no LLM) with a real change, and its impact preview
        draft = client.post("/api/policies/drafts", json={"from_current": True}, headers=PROCUREMENT).json()
        doc = draft["document"]
        doc["effective_from"] = "2026-11-01"
        doc["parameters"]["limits"]["spot_po"]["value"] = 150000
        client.put(f"/api/policies/drafts/{draft['id']}", content=json.dumps(doc), headers=PROCUREMENT)
        dump(client, "sample")
        save("sample", "policy_draft", client.get(f"/api/policies/{draft['id']}", headers=PROCUREMENT).json())
        save("sample", "policy_preview", client.post(f"/api/policies/drafts/{draft['id']}/preview", headers=PROCUREMENT).json())


def save(state, name, value):
    (OUT / state / f"{name}.json").write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
