"""Fit the preferred-list score (policy 6.2) to every ordering the kit gives (D24), and show the evidence.

Constraints: the three printed rankings (Worked_Examples.pdf p.5), the supplier chosen in worked examples
5-8 (it must beat every other member), and the preferred part of the suggestion lists in examples 3, 9,
10, 11 and 12. Each supplier's inputs are computed from the data by engine/preferred.py. A score is
w . (po_count, recency, contract_held, on_time_pct/100, quality_rating/5); we search small whole-number
weights for the simplest that satisfies every constraint strictly, then show how far each weight can move
with the others fixed before a constraint breaks.

  python scripts/ranking_constraints.py
"""
import itertools
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from engine.preferred import preferred_list  # noqa: E402
from loaders import kit  # noqa: E402

FEATURES = ["po_count", "recency", "contract_held", "on_time", "quality"]
# (source, item, as-of date, the order the kit gives for preferred-list members; "first" = only rank 1 known)
CASES = [
    ("printed ranking", "ITM-1048", date(2026, 11, 1), ["S029", "S030"], "all"),
    ("printed ranking", "ITM-1036", date(2026, 11, 1), ["S023", "S022", "S024"], "all"),
    ("printed ranking", "ITM-1016", date(2026, 11, 1), ["S009", "S010"], "all"),
    ("Ex 5 chosen", "ITM-1038", date(2026, 11, 2), ["S024"], "first"),
    ("Ex 6 chosen", "ITM-1044", date(2026, 11, 2), ["S027"], "first"),
    ("Ex 7 chosen", "ITM-1035", date(2026, 11, 6), ["S023"], "first"),
    ("Ex 8 chosen", "ITM-1026", date(2026, 11, 6), ["S014"], "first"),
    ("Ex 3 suggestions", "ITM-1022", date(2026, 11, 2), ["S014", "S013", "S016"], "all"),
    ("Ex 9 suggestions", "ITM-1066", date(2026, 11, 5), ["S043", "S044"], "all"),
    ("Ex 10 suggestions", "ITM-1006", date(2026, 11, 2), [], "all"),
    ("Ex 11 suggestions", "ITM-1034", date(2026, 11, 4), ["S020"], "all"),
    ("Ex 12 suggestions", "ITM-1071", date(2026, 11, 3), ["S045"], "all"),
]


def features(inputs):
    return [Decimal(inputs["po_count"]), Decimal(inputs["recency"]), Decimal(1 if inputs["contract_held"] else 0),
            inputs["on_time_pct"] / 100, inputs["quality_rating"] / 5]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    master = kit.load_master()
    params = master.policies[0].document["parameters"]
    pairs = []  # (label, winner, loser, winner features, loser features)
    print("Inputs per preferred-list member (computed from the data)\n")
    print(f"| Case | Item, as of | Supplier | POs (548 d) | Last PO | Recency | Contract | On-time | Quality | Kit order |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, item, as_of, order, kind in CASES:
        members = {r.supplier_id: r.inputs for r in preferred_list(item, as_of, master, params)}
        if set(order) - set(members) or (kind == "all" and set(order) != set(members)):
            sys.exit(f"{label}: the kit's members {order} differ from the computed members {sorted(members)}")
        for sid, i in sorted(members.items()):
            pos = order.index(sid) + 1 if sid in order else ("not first" if kind == "first" else "-")
            print(f"| {label} | {item} {as_of} | {sid} | {i['po_count']} | {i['last_po_date']} | {i['recency']} | "
                  f"{'yes' if i['contract_held'] else 'no'} | {i['on_time_pct']}% | {i['quality_rating']} | {pos} |")
        ranked = order if kind == "all" else order + sorted(set(members) - set(order))
        for a, b in (zip(ranked, ranked[1:]) if kind == "all" else ((order[0], s) for s in ranked[1:])):
            pairs.append((label, a, b, features(members[a]), features(members[b])))

    print(f"\n{len(pairs)} pairwise constraints: score(winner) > score(loser)\n")

    def ok(w):
        return all(sum(Decimal(x) * (p - q) for x, p, q in zip(w, fa, fb)) > 0 for _, _, _, fa, fb in pairs)

    grid = itertools.product(range(0, 4), range(0, 11), range(0, 6), range(0, 3), range(0, 3))
    good = [w for w in grid if ok(w)]
    print(f"{len(good)} whole-number weight sets (count 0-3, recency 0-10, contract 0-5, on-time 0-2, quality 0-2) satisfy all")
    if not good:
        sys.exit("no simple score satisfies every constraint: see the table above for the conflict")
    smallest = min(good, key=lambda w: (w[0] != 1, sum(w), w))
    print("smallest total (fragile, ignores on-time; for comparison only):", dict(zip(FEATURES, smallest)))
    policy_weights = params["ranking"]["preferred_score"]["weights"]
    best = tuple(policy_weights[f] for f in FEATURES)
    print(f"policy weights (v5.0.json, every 6.2 factor counts): {policy_weights} -> "
          f"{'satisfy every constraint' if ok(best) else 'BREAK a constraint'}")
    if not ok(best):
        sys.exit("the policy's weights break a constraint")

    print("\nHow far each weight can move, the others fixed (strict inequalities):")
    for k, name in enumerate(FEATURES):
        lo, hi = Decimal("-Infinity"), Decimal("Infinity")
        for label, a, b, fa, fb in pairs:
            d = [p - q for p, q in zip(fa, fb)]
            rest = sum(Decimal(best[j]) * d[j] for j in range(5) if j != k)
            if d[k] > 0:
                lo = max(lo, -rest / d[k])
            elif d[k] < 0:
                hi = min(hi, rest / -d[k])
            elif rest <= 0:
                lo = hi = Decimal("NaN")
        print(f"  {name:14} chosen {best[k]}  allowed range ({lo:.3f}, {hi:.3f})")

    print("\nScores with the chosen weights (margin = winner - loser):")
    for label, a, b, fa, fb in pairs:
        sa = sum(Decimal(x) * f for x, f in zip(best, fa))
        sb = sum(Decimal(x) * f for x, f in zip(best, fb))
        print(f"  {label:18} {a} {sa:6.2f} > {b} {sb:6.2f}   margin {sa - sb:5.2f}")


if __name__ == "__main__":
    main()
