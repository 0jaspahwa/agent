"""Throwaway spike script: answers two open data questions with evidence from the kit CSVs.

  2a. Two POs on the same most-recent date at different prices: which price does valuation (3.1b) use?
  2b. Does the 3.1(b) valuation PO include POs placed with now Blocked/Inactive suppliers?

Run from the repo root:  .venv/Scripts/python scripts/data_questions.py
Standard library only. Item codes / PR numbers appear here only to check worked examples.
"""
import csv
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load(rel):
    with open(DATA / rel, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


POS = load("master_data/po_history.csv")
for i, po in enumerate(POS):
    po["file_row"] = i + 2  # line number in the CSV (header is line 1)
    po["date"] = date.fromisoformat(po["po_date"])
    po["price"] = float(po["unit_price"])
SUPPLIER_STATUS = {s["supplier_id"]: s["status"] for s in load("master_data/supplier_master.csv")}
ITEMS = {i["item_code"]: i for i in load("master_data/item_master.csv")}
BATCH = load("pr_batches/sample_pr_batch.csv")


def window(item, req_date, active_only, days=365):
    """POs for the item in the `days` days before req_date (req_date itself excluded)."""
    start = req_date - timedelta(days=days)
    return [p for p in POS if p["item_code"] == item and start <= p["date"] < req_date
            and (not active_only or SUPPLIER_STATUS[p["supplier_id"]] == "Active")]


def latest_date_rows(rows):
    if not rows:
        return []
    last = max(p["date"] for p in rows)
    return [p for p in rows if p["date"] == last]


# Each tie-break picks one price from the POs tied on the most recent date.
TIE_BREAKS = {
    "highest PO number":        lambda t, plant: max(t, key=lambda p: int(p["po_number"]))["price"],
    "lowest PO number":         lambda t, plant: min(t, key=lambda p: int(p["po_number"]))["price"],
    "last in file order":       lambda t, plant: max(t, key=lambda p: p["file_row"])["price"],
    "first in file order":      lambda t, plant: min(t, key=lambda p: p["file_row"])["price"],
    "highest price":            lambda t, plant: max(p["price"] for p in t),
    "lowest price":             lambda t, plant: min(p["price"] for p in t),
    "same plant as requirement": lambda t, plant: next((p["price"] for p in t if p["plant"] == plant), None),
    "largest quantity":         lambda t, plant: max(t, key=lambda p: float(p["quantity"]))["price"],
    "average of tied POs":      lambda t, plant: round(sum(p["price"] for p in t) / len(t), 2),
}


def show(rows):
    print(f"    {'row':>4} {'po_number':>9} {'po_date':10} {'supp':5} {'status':8} {'item':8} {'qty':>6} {'price':>10} plant")
    for p in rows:
        print(f"    {p['file_row']:>4} {p['po_number']:>9} {p['po_date']:10} {p['supplier_id']:5} "
              f"{SUPPLIER_STATUS[p['supplier_id']]:8} {p['item_code']:8} {p['quantity']:>6} {p['price']:>10.2f} {p['plant']}")


def head(title):
    print("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


# ---------------------------------------------------------------- 2a
head("2a. Tie-break on the most recent PO date. Worked example 11: ITM-1034, CHK1, req date 2026-11-04, "
     "value 20,70,780 for 50 NOS")
target = 2070780 / 50
tied = latest_date_rows(window("ITM-1034", date(2026, 11, 4), active_only=False))
print(f"  Example unit value = 20,70,780 / 50 = {target:.2f}. POs tied on the most recent date:")
show(tied)
print("\n  Candidate tie-break -> price chosen -> consistent with example?")
for name, pick in TIE_BREAKS.items():
    price = pick(tied, "CHK1")
    verdict = "n/a (does not separate the two rows)" if name == "largest quantity" else \
        ("CONSISTENT" if price is not None and abs(price - target) < 0.01 else "RULED OUT")
    print(f"    {name:28} {str(price):>10}  {verdict}")

head("2a (cont.) Every same-date tie in po_history.csv where prices differ (any item, any date)")
groups = {}
for p in POS:
    groups.setdefault((p["item_code"], p["po_date"]), []).append(p)
ties = {k: v for k, v in groups.items() if len(v) > 1 and len({p["price"] for p in v}) > 1}
survivors = ["highest PO number", "last in file order", "highest price"]
disagree = 0
for (item, d), rows in sorted(ties.items()):
    picks = {n: TIE_BREAKS[n](rows, None) for n in survivors}
    agree = len(set(picks.values())) == 1
    disagree += not agree
    print(f"\n  {item} on {d}: surviving tie-breaks {'AGREE' if agree else 'DISAGREE'} -> {picks}")
    show(rows)
print(f"\n  {len(ties)} same-date ties with different prices; surviving tie-breaks disagree on {disagree}.")

head("2a (cont.) Which of those ties are live in November 2026, i.e. the tie IS the most recent PO date in the "
     "365-day window for some requirement date 2026-11-01..2026-11-30 (all suppliers / Active only)")
for (item, d), rows in sorted(ties.items()):
    for active_only in (False, True):
        live = [r for r in (date(2026, 11, 1) + timedelta(n) for n in range(30))
                if latest_date_rows(window(item, r, active_only)) and
                latest_date_rows(window(item, r, active_only))[0]["po_date"] == d]
        if live:
            print(f"  {item} {d}  ({'Active only' if active_only else 'all suppliers'}): live for req dates "
                  f"{live[0]} .. {live[-1]}")

# ---------------------------------------------------------------- 2b
head("2b. Valuation with vs without Blocked/Inactive POs, for every worked example valued under 3.1(b)/(c)")
# (example, item, plant, req date, total qty, example value). Contract-valued examples (1-4, 14) and the
# new item (13) are left out: 3.1(a) or 1.2 sets their price, so 2b cannot affect them.
EXAMPLES = [
    ("Ex 5",  "ITM-1038", "CHK1", date(2026, 11, 2), 760, 126472),
    ("Ex 6",  "ITM-1044", "PUN1", date(2026, 11, 2), 7370, 156170),
    ("Ex 7",  "ITM-1035", "PUN1", date(2026, 11, 6), 250, 97955),
    ("Ex 8",  "ITM-1026", "PUN1", date(2026, 11, 6), 2380, 253184),
    ("Ex 9",  "ITM-1066", "PUN1", date(2026, 11, 5), 5, 336562),
    ("Ex 10", "ITM-1006", "PUN1", date(2026, 11, 2), 220, 80300),
    ("Ex 11", "ITM-1034", "CHK1", date(2026, 11, 4), 50, 2070780),
    ("Ex 12", "ITM-1071", "PUN1", date(2026, 11, 3), 4, 6036704),
]


def value(item, plant, req, qty, active_only):
    t = latest_date_rows(window(item, req, active_only))
    price = TIE_BREAKS["highest PO number"](t, plant) if t else float(ITEMS[item]["standard_price"])
    return price, round(qty * price), ("PO " + ",".join(p["po_number"] for p in t)) if t else "std price"


for ex, item, plant, req, qty, expected in EXAMPLES:
    print(f"\n  {ex} {item} {plant} req {req}, qty {qty}, example value {expected:,}")
    for active_only in (False, True):
        price, v, src = value(item, plant, req, qty, active_only)
        label = "Active-only POs   " if active_only else "all suppliers' POs"
        print(f"    {label}: price {price:>10.2f} ({src}) value {v:>9,} {'MATCH' if v == expected else 'differs'}")
    excluded = [p for p in window(item, req, False) if SUPPLIER_STATUS[p["supplier_id"]] != "Active"]
    if excluded:
        print("    Blocked/Inactive POs in the 365-day window:")
        show(excluded)

# ---------------------------------------------------------------- blocked-latest list
REQ = date(2026, 11, 2)
head(f"Items whose most recent PO in the 365 days before {REQ} is from a Blocked or Inactive supplier")
contract_items = {}
for line in load("contracts/contract_lines.csv"):
    contract_items.setdefault(line["item_code"], []).append(line["contract_id"])
for item in sorted(ITEMS):
    latest = latest_date_rows(window(item, REQ, active_only=False))
    if not latest or all(SUPPLIER_STATUS[p["supplier_id"]] == "Active" for p in latest):
        continue
    p_all, _, src_all = value(item, None, REQ, 1, False)
    p_act, _, src_act = value(item, None, REQ, 1, True)
    coded = [l for l in BATCH if l["item_code"] == item]
    words = {w for w in ITEMS[item]["description"].lower().split() if len(w) > 2}
    free = [l for l in BATCH if not l["item_code"] and len(words & set(l["description"].lower().split())) >= 2]
    print(f"\n  {item} {ITEMS[item]['description']} ({ITEMS[item]['item_type']}, std {ITEMS[item]['standard_price']})")
    show(latest)
    print(f"    valuation price  all suppliers: {p_all:.2f} ({src_all})   Active only: {p_act:.2f} ({src_act})")
    print(f"    contracts covering item: {contract_items.get(item, 'none')}")
    print(f"    sample batch lines with this item code: {len(coded)} -> "
          + ", ".join(f"{l['pr_no']}/{l['pr_line']} {l['plant']} {l['created_at'][:10]} qty {l['quantity']} {l['urgency']}"
                      for l in coded))
    if free:
        print("    free-text lines that MAY be this item (crude word overlap, check by eye): "
              + "; ".join(f"{l['pr_no']}/{l['pr_line']} '{l['description']}'" for l in free))


# ================================================================ boundary checks (a) to (e)
# Which policy boundaries does the kit data actually sit on? Everything below is a rough stand-in for the
# engine: a crude item matcher, clubbing per 2.2 with switchable readings, and plain date arithmetic.
from datetime import datetime  # noqa: E402

PLANTS = {p["plant"] for p in load("master_data/plants.csv")}
NOISE = ["as per sample", "for maintenance", "(repeat)", "- urgent"]
ABBREV = {"brg": "bearing", "hyd": "hydraulic", "pneu": "pneumatic", '24"': "24 inch"}


def tokens(text):
    text = text.lower()
    for n in NOISE:
        text = text.replace(n, " ")
    for short, full in ABBREV.items():
        text = text.replace(short, full)
    return set(text.replace("-", " ").replace("(", " ").replace(")", " ").split())


def resolve(line):
    """Crude matcher for this check only (the engine gets a proper one): item code if given, else the item
    whose description shares the most words, provided every token with a digit in it agrees."""
    if line["item_code"]:
        return line["item_code"]
    t = tokens(line["description"])
    best, score = "NEW", 0.0
    for code, item in ITEMS.items():
        d = tokens(item["description"])
        if {w for w in t if any(c.isdigit() for c in w)} - d:
            continue
        s = len(t & d) / len(t | d)
        if s > score:
            best, score = code, s
    return best if score >= 0.5 else "NEW"


LINES = []
for raw in BATCH:
    if float(raw["quantity"] or 0) <= 0 or raw["plant"] not in PLANTS:
        continue  # NOT_PROCESSED lines never club
    LINES.append(dict(raw, item=resolve(raw), ts=datetime.fromisoformat(raw["created_at"]),
                      need=date.fromisoformat(raw["need_by_date"])))
LINES.sort(key=lambda l: (l["ts"], l["pr_no"], int(l["pr_line"])))

# Readings of the two clubbing windows. Each takes (first line, candidate line) -> bool.
CREATED = {
    "date diff <= 14 (recommended)": lambda a, b: (b["ts"].date() - a["ts"].date()).days <= 14,
    "date diff < 14":                lambda a, b: (b["ts"].date() - a["ts"].date()).days < 14,
    "timestamp diff <= 14x24h":      lambda a, b: b["ts"] - a["ts"] <= timedelta(days=14),
    "timestamp diff < 14x24h":       lambda a, b: b["ts"] - a["ts"] < timedelta(days=14),
}
NEED = {
    "|need-by diff| <= 7 (recommended)": lambda a, b: abs((b["need"] - a["need"]).days) <= 7,
    "|need-by diff| < 7":                lambda a, b: abs((b["need"] - a["need"]).days) < 7,
}


def club(created_ok, need_ok):
    reqs = []  # each requirement is a list of lines; reqs[i][0] is its first line
    for l in LINES:
        home = None if l["item"] == "NEW" else next(
            (r for r in reqs if r[0]["item"] == l["item"] and r[0]["plant"] == l["plant"]
             and created_ok(r[0], l) and need_ok(r[0], l)), None)
        if home:
            home.append(l)
        else:
            reqs.append([l])
    return reqs


def key(l):
    return f"{l['pr_no']}/{l['pr_line']}"


def show_line(l, first=None):
    extra = ""
    if first is not None:
        extra = (f"  vs first: date diff {(l['ts'].date() - first['ts'].date()).days}d, "
                 f"elapsed {l['ts'] - first['ts']}, need-by diff {(l['need'] - first['need']).days:+d}d")
    print(f"    {key(l):14} {l['plant']} {l['item']:8} created {l['created_at']} need-by {l['need']} "
          f"{l['urgency']:9} qty {l['quantity']:>5} '{l['description']}'{extra}")


head("Boundary check: crude item resolution of free-text lines (check by eye)")
for l in LINES:
    if not l["item_code"]:
        desc = ITEMS[l["item"]]["description"] if l["item"] != "NEW" else "-"
        print(f"    {key(l):14} '{l['description']}' -> {l['item']} {desc}")

BASE = club(CREATED["date diff <= 14 (recommended)"], NEED["|need-by diff| <= 7 (recommended)"])

head("(a)+(b) Same item + plant pairs near a clubbing boundary (13-15 days created, or 6-8 days need-by)")
for i, a in enumerate(LINES):
    for b in LINES[i + 1:]:
        if a["item"] == "NEW" or a["item"] != b["item"] or a["plant"] != b["plant"]:
            continue
        dd = (b["ts"].date() - a["ts"].date()).days
        nd = abs((b["need"] - a["need"]).days)
        if 13 <= dd <= 15 or 6 <= nd <= 8:
            print(f"\n  pair: created date diff {dd}d (elapsed {b['ts'] - a['ts']}), |need-by diff| {nd}d")
            show_line(a)
            show_line(b)

head("(a)+(b) Does any reading change the clubbing? (compared with the recommended reading)")
base_sets = {frozenset(key(l) for l in r) for r in BASE}
for cn, cf in CREATED.items():
    for nn, nf in NEED.items():
        other = {frozenset(key(l) for l in r) for r in club(cf, nf)}
        diff = (base_sets - other) | (other - base_sets)
        verdict = "same as recommended" if not diff else "DIFFERS: " + str(sorted(map(sorted, diff)))
        print(f"  {cn:30} + {nn:34}: {verdict}")
print("\n  Clubbed requirements under the recommended reading:")
for r in BASE:
    if len(r) > 1:
        print(f"  requirement of {len(r)} lines")
        for l in r:
            show_line(l, r[0] if l is not r[0] else None)

head("(c) Requirements in the same plant whose first lines are within 5 minutes of 24 hours apart (7.1)")
# 7.1 also needs the same supplier and route. Without the engine we only know who COULD supply an item:
# Active suppliers with a PO or contract for it. If the two sets do not overlap, the pair can never share a PO.
could_supply = {}
for p in POS:
    if SUPPLIER_STATUS[p["supplier_id"]] == "Active":
        could_supply.setdefault(p["item_code"], set()).add(p["supplier_id"])
contract_supplier = {c["contract_id"]: c["supplier_id"] for c in load("contracts/contract_register.csv")}
contract_supplier.update({"RC-2026-031": "S021", "RC-2026-033": "S035"})
for c in load("contracts/contract_lines.csv"):
    if SUPPLIER_STATUS[contract_supplier[c["contract_id"]]] == "Active":
        could_supply.setdefault(c["item_code"], set()).add(contract_supplier[c["contract_id"]])
firsts = sorted((r[0] for r in BASE if r[0]["item"] != "NEW"), key=lambda l: l["ts"])
for i, a in enumerate(firsts):
    for b in firsts[i + 1:]:
        gap = b["ts"] - a["ts"]
        if a["plant"] == b["plant"] and abs(gap - timedelta(hours=24)) <= timedelta(minutes=5):
            shared = could_supply.get(a["item"], set()) & could_supply.get(b["item"], set())
            capex = [l["item"] for l in (a, b) if ITEMS[l["item"]]["item_type"] == "Capex"]
            print(f"\n  gap {gap}{'  <-- EXACTLY 24h' if gap == timedelta(hours=24) else ''}; "
                  f"suppliers who could serve both: {sorted(shared) or 'none'}"
                  f"{'; Capex (sourcing, never combined): ' + str(capex) if capex else ''}")
            show_line(a)
            show_line(b)

head("(d) Requirement dates on or within 1 day of a contract start or end date (contract must cover the item)")
CONTRACTS = {c["contract_id"]: (c["supplier_id"], date.fromisoformat(c["start_date"]),
                                date.fromisoformat(c["end_date"]))
             for c in load("contracts/contract_register.csv")}
CONTRACTS["RC-2026-031"] = ("S021", date(2026, 11, 15), date(2027, 11, 14))  # PDF only, read from the PDF
CONTRACTS["RC-2026-033"] = ("S035", date(2026, 11, 20), date(2027, 11, 19))  # PDF only, read from the PDF
COVER = {}
for c in load("contracts/contract_lines.csv"):
    COVER.setdefault(c["item_code"], []).append(c["contract_id"])
for code in ("ITM-1036", "ITM-1037", "ITM-1039"):
    COVER.setdefault(code, []).append("RC-2026-031")
for code in ("ITM-1056", "ITM-1057"):
    COVER.setdefault(code, []).append("RC-2026-033")
found = False
for r in BASE:
    req = r[0]["ts"].date()
    for cid in COVER.get(r[0]["item"], []):
        sup, start, end = CONTRACTS[cid]
        for label, edge in (("start", start), ("end", end)):
            if abs((req - edge).days) <= 1:
                found = True
                print(f"\n  req date {req} is {(req - edge).days:+d}d from {cid} {label} {edge} "
                      f"(supplier {sup} {SUPPLIER_STATUS[sup]})")
                for l in r:
                    show_line(l)
if not found:
    print("  none")

head("(e) POs exactly N-1, N or N+1 days before a requirement date (N = 365, 548), and before 2026-11-01")
req_dates = {(r[0]["item"], r[0]["ts"].date()) for r in BASE if r[0]["item"] != "NEW"}
req_dates |= {(code, date(2026, 11, 1)) for code in ITEMS}
for n in (365, 548):
    hits = 0
    for code, req in sorted(req_dates):
        for p in POS:
            if p["item_code"] != code or abs((req - p["date"]).days - n) > 1:
                continue
            hits += 1
            inside = req - timedelta(days=n) <= p["date"]
            in_win = window(code, req, active_only=False, days=n)
            latest = latest_date_rows(in_win)
            act = [q for q in in_win if SUPPLIER_STATUS[q["supplier_id"]] == "Active"]
            if not inside:
                others = [q for q in in_win if SUPPLIER_STATUS[q["supplier_id"]] == "Active"]
                note = ("just outside; if it counted it would be the ONLY Active PO (changes 'bought' facts)"
                        if not others and SUPPLIER_STATUS[p["supplier_id"]] == "Active" else
                        "just outside; if it counted it would be the latest PO" if not in_win else
                        "just outside; no effect even if counted (later POs exist)")
            elif act == [p]:
                note = "the ONLY Active PO in the window"
            elif p in latest:
                note = "the latest PO in the window"
            else:
                note = "not the latest and not the only Active PO: no effect"
            kind = "2026-11-01 list date" if req == date(2026, 11, 1) else "requirement"
            print(f"  N={n}: {kind} {req} {code}: PO {p['po_number']} {p['po_date']} "
                  f"{SUPPLIER_STATUS[p['supplier_id']]} is {(req - p['date']).days}d before -> "
                  f"{'inside' if inside else 'outside'}; {note}")
    print(f"  N={n}: {hits} PO(s) on or within 1 day of the boundary. History starts "
          f"{min(p['date'] for p in POS)}; {n} days before 2026-11-01 is {date(2026, 11, 1) - timedelta(days=n)}.\n")

LIST_DATE = date(2026, 11, 1)
print(f"  Recency buckets for the preferred list as of {LIST_DATE} (1 = last PO within 90 days, 0.5 = within a year):")
last_po = {}
for p in POS:
    k = (p["item_code"], p["supplier_id"])
    if p["date"] < LIST_DATE and (k not in last_po or p["date"] > last_po[k]):
        last_po[k] = p["date"]
edge_hits = 0
for (code, sup), d in sorted(last_po.items()):
    age = (LIST_DATE - d).days
    for edge in (90, 365):
        if abs(age - edge) <= 1 and SUPPLIER_STATUS[sup] == "Active":
            edge_hits += 1
            print(f"    {code} {sup}: last PO {d}, {age}d before {LIST_DATE} (bucket edge {edge}d)")
print(f"    {edge_hits} Active item/supplier pair(s) on or within 1 day of a recency edge.")
