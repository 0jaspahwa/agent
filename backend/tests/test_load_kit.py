"""Load kit data (POST /api/admin/load-kit, and the form on /ops): the kit is not in the repo, so an app started
without data/ must work from an upload of the kit zip as distributed, a zip without its top folder, or the files."""
import io
import zipfile

from kit_required import skip_module_without_kit

skip_module_without_kit()  # the uploads below are built from the kit in data/

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from db.models import PrBatch, PrLine  # noqa: E402
from kitdata import DATA_DIR, KIT_CSVS, NO_KIT_NOTICE  # noqa: E402

PROC = {"x-user": "Ojas", "x-role": "Procurement"}
TOP = "Cantill_FullStack_Task_Kit/"
SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_bytes()
GOLDEN = (DATA_DIR.parent / "backend" / "tests" / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
KIT_FILES = sorted(p for p in DATA_DIR.rglob("*") if p.is_file() and "test_batches" not in p.parts)


def kit_zip(top=TOP, leave_out=()):
    """The kit as distributed: every file (documents and the sample batch included) under one top folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(top, "") if top else None
        for path in KIT_FILES:
            rel = path.relative_to(DATA_DIR).as_posix()
            if rel not in leave_out:
                z.writestr(top + rel, path.read_bytes())
    return buf.getvalue()


@pytest.fixture
def empty_app(tmp_path, monkeypatch):
    """The app started with no kit in DATA_DIR."""
    import db.seed
    import main
    nodata = tmp_path / "nodata"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setattr(db.seed, "DATA_DIR", nodata)
    monkeypatch.setattr(main, "DATA_DIR", nodata)
    with TestClient(main.app) as c:
        yield c


def health(c):
    return c.get("/api/health").json()


def upload(c, files, headers=PROC):
    return c.post("/api/admin/load-kit", files=files, headers=headers)


def test_without_the_kit_the_app_starts_empty_and_says_so(empty_app):
    h = health(empty_app)
    assert h["kit_loaded"] is False and h["notice"] == NO_KIT_NOTICE
    assert h["rows"] == {"items": 0, "suppliers": 0, "po_history": 0, "contracts": 0, "policy_versions": 1}
    assert NO_KIT_NOTICE in empty_app.get("/ops").text and "Load kit data" in empty_app.get("/ops").text
    assert NO_KIT_NOTICE in empty_app.get("/ops/amendments").text
    got = empty_app.post("/api/process-batch", files={"file": ("sample.csv", SAMPLE)})
    assert got.status_code == 409 and got.json()["detail"] == NO_KIT_NOTICE


def test_every_screen_api_answers_without_the_kit(empty_app):
    buyer = {"x-user": "Asha", "x-role": "Buyer"}
    for url in ("/api/workspace", "/api/workspace/runs", "/api/contracts", "/api/policies", "/api/policies/1",
                "/api/audit", "/api/runs", "/api/items", "/api/suppliers", "/api/chat/requests",
                "/api/preferred-suppliers/export.csv?as_of=2026-11-01",
                "/api/preferred-suppliers?item_code=ITM-1048&as_of=2026-11-01"):
        got = empty_app.get(url, headers={**buyer, "x-role": "Procurement"} if "chat" in url else buyer)
        assert got.status_code in (200, 404), (url, got.status_code, got.text[:200])


def test_the_original_zip_loads_the_kit_and_the_sample_batch_then_matches_the_golden_file(empty_app):
    got = upload(empty_app, {"kit": ("Cantill_FullStack_Task_Kit_vf.zip", kit_zip())})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["tables"]["items"] == {"in_kit": 73, "added": 73}
    assert body["tables"]["contracts"] == {"in_kit": 12, "added": 12}
    assert len(body["contract_pdfs"]) == 12
    assert any("sample_pr_batch.csv" in i and "never loaded" in i for i in body["ignored"])
    h = health(empty_app)
    assert h["kit_loaded"] is True and "notice" not in h
    assert h["rows"] == {"items": 73, "suppliers": 48, "po_history": 468, "contracts": 12, "policy_versions": 1}
    pdf_only = {c["contract_id"]: c for c in empty_app.get("/api/contracts", headers=PROC).json()
                if c["source"] == "pdf"}
    assert sorted(pdf_only) == ["RC-2026-031", "RC-2026-033"]
    assert all(float(c["consumed_value"]) == 0 for c in pdf_only.values())
    with empty_app.app.state.session_factory() as s:  # the sample batch in the zip was not stored
        assert s.scalar(select(func.count()).select_from(PrLine)) == 0
        assert s.scalar(select(func.count()).select_from(PrBatch)) == 0
    assert NO_KIT_NOTICE not in empty_app.get("/ops").text
    csv = empty_app.post("/api/process-batch?format=csv", files={"file": ("sample.csv", SAMPLE)})
    assert csv.text == GOLDEN


def test_loading_the_same_kit_again_changes_nothing(empty_app):
    assert upload(empty_app, {"kit": ("kit.zip", kit_zip())}).json()["added"] > 0
    before = health(empty_app)["rows"]
    again = upload(empty_app, {"kit": ("kit.zip", kit_zip())}).json()
    assert again["added"] == 0 and again["message"] == "This kit is already loaded: nothing changed."
    assert health(empty_app)["rows"] == before


def test_a_zip_without_the_top_folder_and_the_loose_files_both_work(empty_app, tmp_path):
    assert upload(empty_app, {"kit": ("kit.zip", kit_zip(top=""))}).json()["tables"]["items"]["added"] == 73
    loose = [("files", (p.name, p.read_bytes())) for p in KIT_FILES
             if p.suffix == ".csv" and "pr_batches" not in p.parts or "pdf" in p.parent.name]
    got = upload(empty_app, loose)
    assert got.status_code == 200 and got.json()["added"] == 0  # the same kit: nothing new


def test_loose_files_into_an_empty_app(empty_app):
    loose = [("files", (p.name, p.read_bytes())) for p in KIT_FILES if p.suffix in (".csv", ".pdf")]
    got = upload(empty_app, loose)
    assert got.status_code == 200 and got.json()["tables"]["po_history"]["added"] == 468


@pytest.mark.parametrize("leave_out,said", [
    (("master_data/po_history.csv",), "master_data/po_history.csv missing"),
    (("contracts/pdf/RC-2026-002.pdf",), "RC-2026-002 but its PDF is missing"),
    (tuple(f"contracts/pdf/{p.name}" for p in (DATA_DIR / "contracts" / "pdf").glob("*.pdf")), "no contract PDFs"),
])
def test_a_missing_file_is_refused_plainly_and_nothing_is_loaded(empty_app, leave_out, said):
    got = upload(empty_app, {"kit": ("kit.zip", kit_zip(leave_out=leave_out))})
    assert got.status_code == 400 and said in got.json()["detail"], got.text
    assert health(empty_app)["kit_loaded"] is False


def test_an_unreadable_contract_pdf_or_csv_is_refused_and_nothing_is_loaded(empty_app):
    files = [("files", (rel.split("/")[-1], (DATA_DIR / rel).read_bytes())) for rel in KIT_CSVS]
    files += [("files", (p.name, b"not a pdf" if p.stem == "RC-2026-031" else p.read_bytes()))
              for p in (DATA_DIR / "contracts" / "pdf").glob("*.pdf")]
    got = upload(empty_app, files)
    assert got.status_code == 400 and "RC-2026-031.pdf" in got.json()["detail"]
    bad_items = [f if f[1][0] != "item_master.csv" else ("files", ("item_master.csv", b"code,name\nX,Y\n")) for f in files]
    got = upload(empty_app, bad_items)
    assert got.status_code == 400 and "item_master.csv" in got.json()["detail"]
    assert health(empty_app)["rows"]["items"] == 0 and health(empty_app)["rows"]["contracts"] == 0


def test_only_procurement_can_load_the_kit_and_an_empty_upload_is_refused(empty_app):
    assert upload(empty_app, {"kit": ("kit.zip", kit_zip())}, {"x-user": "Asha", "x-role": "Buyer"}).status_code == 403
    assert empty_app.post("/api/admin/load-kit", headers=PROC).status_code == 400
    assert upload(empty_app, {"kit": ("kit.zip", b"PK\x03\x04 broken")}).json()["detail"] == "kit.zip: not a readable zip file."


def test_the_ops_form_loads_the_kit(empty_app):
    form = {"user": "Ojas", "role": "Procurement"}
    got = empty_app.post("/ops/load-kit", data=form, files={"files": ("kit.zip", kit_zip())})
    assert got.status_code == 200 and "Kit loaded" in got.text
    assert empty_app.post("/ops/load-kit", data={**form, "role": "Buyer"},
                          files={"files": ("kit.zip", kit_zip())}).status_code == 403
    assert health(empty_app)["kit_loaded"] is True


def test_loading_is_audited(empty_app):
    upload(empty_app, {"kit": ("kit.zip", kit_zip())})
    entries = empty_app.get("/api/audit?action=kit.load", headers=PROC).json()
    entries = entries["entries"] if isinstance(entries, dict) else entries
    assert entries and entries[0]["actor"] == "Ojas"
