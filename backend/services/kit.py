"""Load the task kit through the app (POST /api/admin/load-kit, and the forms on /ops and the Kit data screen).

The kit is not in the repo (the task rules), so after deploying, a Procurement user uploads it once. Accepted:
- the kit zip exactly as distributed (everything under a top-level Cantill_FullStack_Task_Kit/ folder);
- a zip of the kit's folders without that top folder;
- the individual files: the six CSVs and the contract PDFs.

Every file is recognised by its name, copied into a temporary folder in the kit's layout, and loaded by the same
code as the startup seed (db/seed.py seed_kit), in one transaction: all of it or nothing. Rows already present
are left untouched, so loading the same kit again changes nothing. The sample PR batch is never loaded or stored
(a batch is processed under Batches); the kit's PDFs of the brief, policy and worked examples are not data.
Policy v5.0 does not come from the kit: it is seeded from backend/policies/v5.0.json.
"""
import io
import re
import zipfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from sqlalchemy.exc import IntegrityError

from db.models import AuditLog, Contract
from db.seed import KitDataError, kit_rows, seed_kit
from kitdata import KIT_CSVS
from loaders.contract_pdf import ContractPdfError

PLACES = {PurePosixPath(rel).name: rel for rel in KIT_CSVS}  # item_master.csv -> master_data/item_master.csv
DOCUMENTS = {"cantill_fullstack_task_brief.pdf", "corvo_procurement_policy.pdf", "worked_examples.pdf", "readme.txt"}
SAFE_PDF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.pdf$")
MAX_FILE_BYTES = 20 * 1024 * 1024   # per file, also inside a zip
MAX_TOTAL_BYTES = 80 * 1024 * 1024  # everything uploaded, unzipped
MAX_FILES = 500


class KitError(ValueError):
    """The upload is not a usable kit; the message says what is missing or wrong, in plain words."""


def _is_zip(name, data):
    return name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04"


def _members(name, data):
    """(path, bytes) for every file in the upload: a zip's members, or the file itself."""
    if not _is_zip(name, data):
        yield name, data
        return
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise KitError(f"{name}: not a readable zip file.") from exc
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise KitError(f"{name}: more than {MAX_FILES} files; this is not the kit.")
    for info in infos:
        if info.file_size > MAX_FILE_BYTES:
            raise KitError(f"{name}: {info.filename} is larger than {MAX_FILE_BYTES // 2**20} MB; this is not the kit.")
        yield info.filename, archive.read(info)


def sort_files(uploads):
    """uploads: [(file name, bytes)]. Returns ({kit path: bytes}, [ignored: reason]). Raises KitError."""
    files, ignored, total = {}, [], 0
    for upload_name, data in uploads:
        for path, content in _members(upload_name or "upload", data):
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise KitError(f"The upload is larger than {MAX_TOTAL_BYTES // 2**20} MB unzipped; this is not the kit.")
            parts = PurePosixPath(path.replace("\\", "/")).parts
            base = parts[-1] if parts else ""
            if not base or base.startswith(".") or "__MACOSX" in parts:
                continue
            if base in PLACES:
                place = PLACES[base]
            elif base.lower() == "sample_pr_batch.csv" or "pr_batches" in parts:
                ignored.append(f"{path}: a PR batch is processed under Batches, never loaded as kit data")
                continue
            elif base.lower() in DOCUMENTS:
                ignored.append(f"{path}: a kit document, not data")
                continue
            elif base.lower().endswith(".pdf"):
                if not SAFE_PDF_NAME.match(base):
                    raise KitError(f"{path}: a contract PDF's name may hold only letters, digits, '.', '_' and '-'.")
                place = f"contracts/pdf/{base}"
            else:
                ignored.append(f"{path}: not part of the kit data")
                continue
            if place in files and files[place] != content:
                raise KitError(f"The upload has two different copies of {base}.")
            files[place] = content
    return files, ignored


def _check_complete(files):
    missing = [rel for rel in KIT_CSVS if rel not in files]
    if missing:
        raise KitError("The kit is incomplete: " + ", ".join(missing) + " missing. Upload the kit zip as "
                       "distributed, or all six CSV files and the contract PDFs.")
    if not any(p.startswith("contracts/pdf/") for p in files):
        raise KitError("The kit is incomplete: no contract PDFs (contracts/pdf/). The contracts signed after the "
                       "register exist only as PDFs, so they are needed.")


def load_kit(session, uploads, user, role):
    """Load the uploaded kit into the database. Returns a summary dict; raises KitError with a plain message
    (nothing is loaded then)."""
    files, ignored = sort_files(uploads)
    _check_complete(files)
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for rel, content in files.items():
            target = Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        try:
            register = {r["contract_id"] for r in kit_rows(tmp)[Contract]}
            missing_pdfs = sorted(c for c in register if f"contracts/pdf/{c}.pdf" not in files)
            if missing_pdfs:
                raise KitError("The kit is incomplete: the register lists " + ", ".join(missing_pdfs)
                               + " but its PDF is missing from contracts/pdf/.")
            conn = session.connection()
            tables = seed_kit(conn, tmp)
        except (KitDataError, ContractPdfError) as exc:
            session.rollback()
            raise KitError(str(exc)) from exc
        except IntegrityError as exc:
            session.rollback()
            raise KitError("The kit files do not fit together (a row refers to an item, supplier or contract "
                           "that is not in the files).") from exc
    pdfs = sorted(PurePosixPath(p).name for p in files if p.startswith("contracts/pdf/"))
    summary = {"tables": tables, "added": sum(t["added"] for t in tables.values()),
               "contract_pdfs": pdfs, "ignored": ignored}
    summary["message"] = (f"Kit loaded: {summary['added']} rows added." if summary["added"]
                          else "This kit is already loaded: nothing changed.")
    session.add(AuditLog(actor=user, actor_role=role, action="kit.load", entity_type="kit", entity_id="kit",
                         details={"added": summary["added"], "tables": tables, "contract_pdfs": pdfs}))
    session.commit()
    return summary
