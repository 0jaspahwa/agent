"""The exports of the sample batch and of the stress batch must equal their golden files byte for byte.

Both golden files were reviewed by Ojas: tests/golden/sample_pr_batch_decisions.csv, and
tests/golden/stress_batch_decisions.csv (the S1 stress batch, whose every line was also checked against
expectations worked out by hand, test_stress.py). If a test fails, the engine's output changed: read the diff,
and only if the change is intended regenerate the file with
    python scripts/run_batch.py <batch> --out backend/tests/golden/<file>
and explain the change in the commit message.
"""
import csv
import io
from pathlib import Path

from engine.export import to_csv
from engine.pipeline import decide
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

GOLDEN = Path(__file__).parent / "golden" / "sample_pr_batch_decisions.csv"
STRESS_GOLDEN = Path(__file__).parent / "golden" / "stress_batch_decisions.csv"
FIXTURES = Path(__file__).parent / "fixtures"


def readable_diff(expected, actual, limit=40):
    """Per PR line, the columns that changed (old -> new), plus lines added or removed."""
    def rows(text):  # a repeated pr_no/pr_line (the V3 duplicate case) is keyed by its occurrence
        out, seen = {}, {}
        for r in csv.DictReader(io.StringIO(text)):
            ref = (r["pr_no"], r["pr_line"])
            seen[ref] = seen.get(ref, 0) + 1
            out[ref if seen[ref] == 1 else (ref[0], f"{ref[1]}#{seen[ref]}")] = r
        return out
    old, new = rows(expected), rows(actual)
    out = []
    for key in sorted(old.keys() | new.keys()):
        if key not in new:
            out.append(f"{key[0]}/{key[1]}: missing from the new output")
        elif key not in old:
            out.append(f"{key[0]}/{key[1]}: new line")
        else:
            for col, value in old[key].items():
                if new[key][col] != value:
                    out.append(f"{key[0]}/{key[1]} {col}: {value!r} -> {new[key][col]!r}")
    if not out and expected != actual:
        out.append("same values, different bytes (line endings, quoting or column order)")
    return "\n".join(out[:limit] + ([f"... and {len(out) - limit} more"] if len(out) > limit else []))


def test_sample_batch_export_equals_the_golden_file():
    actual = to_csv(decide(kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"), kit.load_master()))
    expected = GOLDEN.read_text(encoding="utf-8")
    assert actual == expected, "the export differs from the golden file:\n" + readable_diff(expected, actual)


def test_stress_batch_export_equals_its_golden_file():
    actual = to_csv(decide(kit.load_pr_batch(FIXTURES / "stress_batch.csv"), kit.load_master()))
    expected = STRESS_GOLDEN.read_text(encoding="utf-8")
    assert actual == expected, "the export differs from the golden file:\n" + readable_diff(expected, actual)


def test_the_diff_is_readable():
    expected = "pr_no,pr_line,route\nPR-1,1,RFQ\nPR-2,1,SPOT_PO\n"
    actual = "pr_no,pr_line,route\nPR-1,1,RFP\nPR-3,1,RFQ\n"
    assert readable_diff(expected, actual).splitlines() == [
        "PR-1/1 route: 'RFQ' -> 'RFP'", "PR-2/1: missing from the new output", "PR-3/1: new line"]


def test_the_diff_tells_repeated_lines_apart():
    expected = "pr_no,pr_line,route\nPR-1,1,RFQ\nPR-1,1,NOT_PROCESSED\n"
    actual = "pr_no,pr_line,route\nPR-1,1,RFQ\nPR-1,1,RFP\n"
    assert readable_diff(expected, actual) == "PR-1/1#2 route: 'NOT_PROCESSED' -> 'RFP'"
