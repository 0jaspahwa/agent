"""The decision export in the brief's format: one row per PR line, in input order, fixed column order and
CSV dialect (comma, minimal quoting, \n line ends), so the same result always gives the same bytes."""
import csv
import io

from engine.contracts import number_text
from engine.pipeline import EXPORT_COLUMNS
from engine.preferred import preferred_list
from engine.versions import version_in_force

PREFERRED_COLUMNS = ["item_code", "rank", "supplier_id", "reference_price"]


def preferred_csv(master, as_of, top=3):
    """The top `top` suppliers on every item's preferred list as of a date (policy 6.1-6.3), under the policy
    version in force on that date. Category top-ups are for sourcing suggestions and do not appear; an item
    with fewer preferred suppliers has fewer rows, one with none has no rows (D31). Raises LookupError if no
    policy version is in force on the date."""
    version = version_in_force(master.policies, as_of)
    if version is None:
        raise LookupError(f"no approved policy version is in force on {as_of}")
    params = version.document["parameters"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(PREFERRED_COLUMNS)
    for item_code in sorted(master.items):
        for r in preferred_list(item_code, as_of, master, params)[:top]:
            writer.writerow([item_code, r.rank, r.supplier_id,
                             "" if r.reference_price is None else number_text(r.reference_price)])
    return buffer.getvalue()


def to_csv(result):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in result.rows:
        writer.writerow([row[c] for c in EXPORT_COLUMNS])
    return buffer.getvalue()
