"""Process a PR batch CSV with the engine (policy versions and master data from the kit) and write the export.

  python scripts/run_batch.py                                    # the sample batch
  python scripts/run_batch.py my_batch.csv --out decisions.csv
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from engine.export import to_csv  # noqa: E402
from engine.pipeline import decide  # noqa: E402
from kitdata import DATA_DIR  # noqa: E402
from loaders import kit  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", nargs="?", default=str(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"))
    parser.add_argument("--out", help="where to write the export (default scripts/out/<batch>_decisions.csv)")
    args = parser.parse_args()
    out = Path(args.out) if args.out else ROOT / "scripts" / "out" / f"{Path(args.batch).stem}_decisions.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    master = kit.load_master()
    result = decide(kit.load_pr_batch(args.batch), master)
    out.write_text(to_csv(result), encoding="utf-8", newline="")

    print(f"{len(result.rows)} lines -> {out}")
    for route, n in sorted(Counter(r["route"] for r in result.rows).items(), key=lambda x: -x[1]):
        print(f"  {route:18} {n}")
    print(f"  requirements {len(result.requirements)}, purchase orders {len(result.purchase_orders)}")
    print("\nContract ceilings (consumed at start -> end of the run, of the cap)")
    caps = {c.contract_id: c.value_cap for c in master.contracts}
    for cid in sorted(caps):
        start, end = result.ceiling_baseline[cid], result.ceiling_final[cid]
        print(f"  {cid}  {start:>12.2f} -> {end:>12.2f}  of {caps[cid]:>12.2f}  (used this run {end - start:>11.2f})")


if __name__ == "__main__":
    main()
