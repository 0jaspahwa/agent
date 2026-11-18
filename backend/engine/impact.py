"""H5: what a draft policy version would change on a batch. Pure: the same lines are decided under the
approved versions, and again with the draft added as if approved last (it wins on equal dates), and every PR
line whose decision changes is listed. Grouping and PO are compared by membership (which PR lines share a
requirement or a PO), not by their ids, because one new requirement renumbers every later id."""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from engine.inputs import PolicyVersion
from engine.pipeline import decide

FIELDS = ("decision", "route", "supplier_id", "unit_price", "group_value_inr", "suggested_supplier_ids")
LATER_THAN_ANY_APPROVAL = datetime(3000, 1, 1, tzinfo=timezone.utc)


def candidate(document):
    """The draft as an approved version would be, for previewing."""
    return PolicyVersion(document["version"], date.fromisoformat(document["effective_from"]), document,
                         LATER_THAN_ANY_APPROVAL)


def _ref(row):
    return f"{row['pr_no']}/{row['pr_line']}"


def _members(rows, column):
    groups = defaultdict(list)
    for r in rows:
        if r[column]:
            groups[r[column]].append(_ref(r))
    return {_ref(r): tuple(sorted(groups[r[column]])) if r[column] else () for r in rows}


def _rule(row):
    if row["route"] == "NOT_PROCESSED":
        return "not processed"
    return row["reason"].split(" ", 1)[0]


def impact(lines, master, document):
    """Summary of the changes the draft `document` would make to these lines."""
    before = decide(lines, master)
    after = decide(lines, master, policies=(*master.policies, candidate(document)))
    b_rows, a_rows = [r.values for r in before.rows], [r.values for r in after.rows]
    b_groups, a_groups = _members(b_rows, "group_id"), _members(a_rows, "group_id")
    b_pos, a_pos = _members(b_rows, "po_id"), _members(a_rows, "po_id")
    changes = []
    for b, a in zip(b_rows, a_rows):
        key = _ref(b)
        diffs = {f: (b[f], a[f]) for f in FIELDS if b[f] != a[f]}
        if b_groups[key] != a_groups[key]:
            diffs["grouped_with"] = (list(b_groups[key]), list(a_groups[key]))
        if b_pos[key] != a_pos[key]:
            diffs["same_po_as"] = (list(b_pos[key]), list(a_pos[key]))
        if diffs:
            changes.append({"line": key, "changes": {k: {"before": v[0], "after": v[1]} for k, v in diffs.items()},
                            "rule_before": _rule(b), "rule_after": _rule(a),
                            "version_before": b["policy_version"], "version_after": a["policy_version"]})
    under_draft = sum(r["policy_version"] == document["version"] for r in a_rows)
    dates = [l.created_at.date() for l in lines if l.created_at]
    effective = document["effective_from"]
    if changes:
        explanation = f"{len(changes)} of {len(a_rows)} lines change"
    elif dates and date.fromisoformat(effective) > max(dates):
        explanation = (f"No decision changes: the effective date {effective} is after the last requirement in this "
                       f"batch ({max(dates)})")
    elif under_draft == 0:
        explanation = (f"No decision changes: no requirement in this batch falls under the draft "
                       f"(effective {effective}; another approved version wins on these dates)")
    else:
        explanation = (f"No decision changes: {under_draft} lines fall under the draft from {effective}, but what it "
                       f"changes does not alter any of their decisions")
    return {"draft_version": document["version"], "effective_from": effective, "lines": len(a_rows),
            "lines_under_draft": under_draft, "changed": len(changes), "explanation": explanation,
            "routes_before": dict(sorted(Counter(r["route"] for r in b_rows).items())),
            "routes_after": dict(sorted(Counter(r["route"] for r in a_rows).items())),
            "batch_dates": [str(min(dates)), str(max(dates))] if dates else [], "changes": changes}
