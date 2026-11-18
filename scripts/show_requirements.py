"""Run the first half of the engine (E1 validation, E2 matching, E3 clubbing) on a PR batch CSV and print
what it found: lines not processed, flagged lines, new items and every requirement with its lines.

  python scripts/show_requirements.py                       # the sample batch
  python scripts/show_requirements.py my_batch.csv --min-lines 3
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from engine.clubbing import club  # noqa: E402
from engine.validation import check_lines  # noqa: E402
from kitdata import DATA_DIR  # noqa: E402
from loaders import kit  # noqa: E402


def ref(c):
    return f"{c.line.pr_no}/{c.line.pr_line}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", nargs="?", default=str(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"))
    parser.add_argument("--min-lines", type=int, default=1, help="only list requirements with this many lines")
    args = parser.parse_args()

    master = kit.load_master()
    checked = check_lines(kit.load_pr_batch(args.batch), master)
    reqs = club(checked, master)
    bad = [c for c in checked if not c.processed]
    flagged = [c for c in checked if c.flags]
    new = [r for r in reqs if r.is_new]

    print(f"Batch: {args.batch}")
    print(f"  lines {len(checked)} | not processed {len(bad)} | flagged {len(flagged)} | new items {len(new)}")
    print(f"  requirements {len(reqs)} | clubbed (2+ lines) {sum(len(r.lines) > 1 for r in reqs)} | "
          f"3+ lines {sum(len(r.lines) >= 3 for r in reqs)} | emergency {sum(r.is_emergency for r in reqs)}")
    print(f"  matched by code {sum(c.match and c.match.status == 'code' for c in checked)} | by description "
          f"{sum(c.match and c.match.status == 'description' for c in checked)}")

    print("\nNot processed")
    for c in bad:
        print(f"  {ref(c):16} {c.line.description[:40]:40} " + "; ".join(f"{f.id} {f.text}" for f in c.not_processed))
    print("\nFlagged (processed, with a note)")
    for c in flagged:
        print(f"  {ref(c):16} {c.line.description[:40]:40} " + "; ".join(f"{f.id} {f.text}" for f in c.flags))
    print("\nNew items (never clubbed)")
    for r in new:
        print(f"  {r.group_id} {ref(r.first):16} {r.first.line.description!r}: {r.first.match.explanation}")

    print(f"\nRequirements with at least {args.min_lines} line(s)")
    for r in reqs:
        if len(r.lines) < args.min_lines:
            continue
        item = master.items[r.item_code].description if r.item_code else "NEW"
        print(f"  {r.group_id} {r.item_code or 'NEW'} {item!r} | {r.plant} | requirement date {r.requirement_date} | "
              f"total {r.total_quantity} | {'EMERGENCY' if r.is_emergency else 'normal'} | policy {r.version.version}")
        for c in r.lines:
            how = "code" if c.match.status == "code" else f"description {c.match.score}"
            print(f"      {ref(c):16} created {c.line.created_at:%Y-%m-%d %H:%M}  need-by {c.line.need_by_date}  "
                  f"qty {c.line.quantity:>8} {c.line.uom or '':5} {c.urgency:9} ({how}) {c.line.description[:38]}")


if __name__ == "__main__":
    main()
