"""Store an uploaded PR batch CSV: the file exactly as received, and one pr_lines row per line."""
import hashlib

from db.models import PrBatch, PrLine
from loaders.pr_csv import parse_pr_csv


def ingest_batch(session, filename, csv_text, user):
    """Raises loaders.pr_csv.BatchFormatError (nothing stored) if the file cannot be read as a batch."""
    rows = parse_pr_csv(csv_text)
    batch = PrBatch(filename=filename, csv_text=csv_text, csv_sha256=hashlib.sha256(csv_text.encode()).hexdigest(),
                    line_count=len(rows), uploaded_by=user)
    session.add(batch)
    session.flush()
    session.add_all(PrLine(source="batch", batch_id=batch.id, raw=raw, created_by=user, **typed) for raw, typed in rows)
    session.flush()
    return batch
