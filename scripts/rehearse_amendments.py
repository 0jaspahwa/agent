"""H9: end-to-end rehearsal of the amendment flow, nine amendments, through the app's own HTTP API.

For each amendment in docs/sample_amendments (A4 and A7 are uploaded as PDFs):
  draft -> check it is valid -> impact preview on the sample batch -> compare with the expected changes ->
  approve (Procurement) -> Run 2 by date (must match the preview) -> Run 1 with policy_version=5.0 (must equal
  the golden file) -> withdraw, so the next amendment starts from v5.0 again.
At the end the batch is processed once more by date and must equal the golden file (reset to v5.0).

The expected changes are worked out here from the golden file, the batch and the item master only (never by
running the engine under the amendment), so they are an independent check of what the engine does.

Drafting:
  default   no LLM: each draft starts from the current version and the reference edit below is PUT, as a
            reviewer would do on the amendment page. Proves every amendment is expressible without code.
  --llm     the app's LLM drafts each one from the uploaded document (real calls, counted). An LLM draft that
            is invalid or gives the wrong changes is recorded and discarded, and the reference edit is used.

    python scripts/rehearse_amendments.py                       # in-process app on a temporary SQLite database
    python scripts/rehearse_amendments.py --base-url http://localhost:8000
    python scripts/rehearse_amendments.py --llm --out docs/rehearsal/llm_run.md
"""
import argparse
import csv
import io
import json
import os
import sys
import tempfile
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from amendments.simple_pdf import text_pdf  # noqa: E402
from kitdata import DATA_DIR  # noqa: E402
from loaders import kit  # noqa: E402

AMENDMENTS_DIR = ROOT / "docs" / "sample_amendments"
SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (ROOT / "backend" / "tests" / "golden" / "sample_pr_batch_decisions.csv").read_text(encoding="utf-8")
PROCUREMENT = {"x-user": "Rehearsal (Procurement)", "x-role": "Procurement"}


# ---------------------------------------------------------------- the v5.0 decisions, from the golden file
def key(row):
    return f"{row['pr_no']}/{row['pr_line']}"


GOLD = {key(r): r for r in csv.DictReader(io.StringIO(GOLDEN))}
BATCH = {key(r): r for r in csv.DictReader(io.StringIO(SAMPLE))}
ITEMS = kit.load_master().items
GROUPS = defaultdict(list)
for k, r in GOLD.items():
    if r["group_id"]:
        GROUPS[r["group_id"]].append(k)
PO_MEMBERS = defaultdict(set)
for k, r in GOLD.items():
    if r["po_id"]:
        PO_MEMBERS[r["po_id"]].add(k)


def value(k):
    return Decimal(GOLD[k]["group_value_inr"]) if GOLD[k]["group_value_inr"] else None


def category(k):
    item = ITEMS.get(GOLD[k]["resolved_item_code"])
    return item.category if item else None


def requirement_date(k):
    """The first (earliest) line's creation date of the line's requirement."""
    members = GROUPS.get(GOLD[k]["group_id"], [k])
    return min(date.fromisoformat(BATCH[m]["created_at"][:10]) for m in members)


def lines(route=None, where=lambda k: True):
    return {k for k, r in GOLD.items() if (route is None or r["route"] == route) and where(k)}


def with_po_partners(keys):
    out = set(keys)
    for k in keys:
        if GOLD[k]["po_id"]:
            out |= PO_MEMBERS[GOLD[k]["po_id"]]
    return out


# ---------------------------------------------------------------- expectations
@dataclass
class Expect:
    note: str
    routes: dict | None = None  # line -> (before, after): exactly these route changes
    grouping: set | None = None  # exactly these lines change requirement membership
    may_change: set = field(default_factory=set)  # lines allowed to change in any field (plus their PO partners)
    no_change_reason: str | None = None  # the explanation must start with this
    check: object = None  # extra check(changes) -> list of problems

    def problems(self, impact):
        changes = {c["line"]: c["changes"] for c in impact.get("changes", [])}
        found = []
        if self.no_change_reason is not None:
            if changes:
                found.append(f"expected no change, got {len(changes)}")
            if not impact["explanation"].startswith(self.no_change_reason):
                found.append(f"explanation: {impact['explanation']!r}")
            return found
        if self.routes is not None:
            got = {k: (v["route"]["before"], v["route"]["after"]) for k, v in changes.items() if "route" in v}
            if got != self.routes:
                found.append(f"route changes differ: missing {sorted(set(self.routes) - set(got))}, "
                             f"unexpected {sorted(set(got) - set(self.routes))}, "
                             f"wrong {sorted(k for k in set(got) & set(self.routes) if got[k] != self.routes[k])}")
        if self.grouping is not None:
            got = {k for k, v in changes.items() if "grouped_with" in v}
            if got != self.grouping:
                found.append(f"grouping changes differ: missing {sorted(self.grouping - got)}, unexpected {sorted(got - self.grouping)}")
        allowed = with_po_partners(self.may_change | set(self.routes or {}) | (self.grouping or set()))
        # a line that only gains or loses a PO partner, where that partner is an expected change (e.g. a line split
        # off by a shorter clubbing window becomes a spot PO and is consolidated with another PO, policy 7)
        allowed |= {k for k, v in changes.items() if set(v) == {"same_po_as"}
                    and (set(v["same_po_as"]["before"]) | set(v["same_po_as"]["after"])) & allowed}
        if set(changes) - allowed:
            found.append(f"lines changed that should not: {sorted(set(changes) - allowed)[:10]}")
        if not changes:
            found.append("expected changes, got none")
        if self.check:
            found += self.check(changes)
        return found


AFTER_BATCH = "No decision changes: the effective date"


def expect_a4():
    big = lines("RFQ", lambda k: value(k) >= 750000)
    return Expect(f"{len(big)} RFQs valued 7,50,000 or more become RFPs", routes={k: ("RFQ", "RFP") for k in big})


def expect_a5():
    hit = lines("EMERGENCY_PO", lambda k: BATCH[k]["plant"] == "CHK1" and value(k) > 200000)
    return Expect(f"{len(hit)} CHK1 emergency POs above 2,00,000 fall through to RFQ (too large for spot)",
                  routes={k: ("EMERGENCY_PO", "RFQ") for k in hit})


def expect_a6():
    split = set()
    for members in GROUPS.values():
        first = min(date.fromisoformat(BATCH[m]["created_at"][:10]) for m in members)
        if any((date.fromisoformat(BATCH[m]["created_at"][:10]) - first).days > 7 for m in members):
            split |= set(members)
    return Expect(f"the {len(split)} lines of requirements spanning more than 7 days are regrouped (values, "
                  f"routes and POs of those lines may follow)", grouping=split, may_change=split)


def expect_a7():
    hit = lines("SPOT_PO", lambda k: category(k) == "Office & IT")
    return Expect(f"{len(hit)} Office & IT spot POs become RFQs", routes={k: ("SPOT_PO", "RFQ") for k in hit})


def expect_a8():
    tool_room = {g for g, members in GROUPS.items() if any(BATCH[m]["department"] == "Tool Room" for m in members)}
    hit = lines("SPOT_PO", lambda k: GOLD[k]["group_id"] in tool_room and value(k) >= 100000)
    return Expect(f"{len(hit)} spot POs of 1,00,000 or more in requirements with a Tool Room line become RFQs",
                  routes={k: ("SPOT_PO", "RFQ") for k in hit})


def expect_a9():
    late = lines("RFQ", lambda k: requirement_date(k) >= date(2026, 11, 10))

    def check(changes):
        bad = []
        for k, v in changes.items():
            if set(v) != {"suggested_supplier_ids"}:
                bad.append(f"{k}: changed {sorted(v)}")
                continue
            old, new = v["suggested_supplier_ids"]["before"].split(";"), v["suggested_supplier_ids"]["after"].split(";")
            if new[:len(old)] != old or len(new) != len(old) + 1:
                bad.append(f"{k}: {old} -> {new} (expected the same 3 plus one)")
        return bad
    return Expect(f"RFQs dated from 10 Nov get a 4th supplier where one is eligible ({len(late)} RFQ lines dated "
                  f"from 10 Nov; earlier ones unchanged)", may_change=late, check=check)


# ---------------------------------------------------------------- reference edits (what a reviewer types)
def a1(p):
    p["parameters"]["limits"]["spot_po"].update(value=150000, operator="<=", text="at or below 1,50,000")
    p["parameters"]["limits"]["emergency_po"].update(value=750000, text="at or below 7,50,000")


def a2(p):
    p["overrides"].append({"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "line.plant"}, "CHK1"]},
                           "set": {"value": 100000}, "clause": "Amendment A-2 §1"})
    insert_after(p, "5.3", {
        "id": "5.3A", "title": "Lubricants at Chakan go to quotes", "clause_text": "Amendment A-2 §2",
        "when": {"and": [{"==": [{"var": "requirement.plant"}, "CHK1"]}, {"==": [{"var": "item.category"}, "Lubricants"]},
                         {"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfq"]}]},
        "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}})


def a3(p):
    p["derived_facts"].append({"name": "price_premium_pct", "description": "Valuation price above standard, in percent",
                               "expr": {"*": [100, {"/": [{"-": [{"var": "requirement.valuation_price"},
                                                                 {"var": "item.standard_price"}]},
                                                          {"var": "item.standard_price"}]}]}})
    insert_after(p, "5.3", {
        "id": "5.3B", "title": "Price variance", "clause_text": "Amendment A-3",
        "when": {"and": [{"==": [{"var": "requirement.valuation_source"}, "latest_po_in_window"]},
                         {">": [{"var": "derived.price_premium_pct"}, 15]},
                         {"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfq"]}]},
        "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}})


def a4(p):
    p["parameters"]["limits"]["rfq"].update(value=750000, text="below 7,50,000 (rule 5.6, RFP, is everything not below it)")
    rule(p, "5.5")["clause_text"] = "Value below 7,50,000. Suggest 3 suppliers (6.4). Amendment A-4."
    rule(p, "5.6")["clause_text"] = "Value 7,50,000 or more. Suggest 5 suppliers (6.4). Amendment A-4."


def a5(p):
    p["overrides"].append({"id": "OV-1", "parameter": "limits.emergency_po", "clause": "Amendment A-5",
                           "when": {"==": [{"var": "line.plant"}, "CHK1"]},
                           "set": {"value": 200000, "text": "at or below 2,00,000 at CHK1"}})


def a6(p):
    p["parameters"]["clubbing"]["creation_window"]["length"] = 7


def a7(p):
    insert_after(p, "5.3", {
        "id": "5.3C", "title": "Office and IT items are quoted for", "clause_text": "Amendment A-7",
        "when": {"and": [{"==": [{"var": "item.category"}, "Office & IT"]},
                         {"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfq"]}]},
        "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}})


def a8(p):
    p["derived_facts"].append({"name": "has_tool_room_line", "clause": "Amendment A-8",
                               "description": "At least one clubbed line was raised by the Tool Room",
                               "expr": {"some": [{"var": "lines"}, {"==": [{"var": "department"}, "Tool Room"]}]}})
    insert_after(p, "5.3", {
        "id": "5.3D", "title": "Tool Room purchases are quoted for", "clause_text": "Amendment A-8",
        "when": {"and": [{"==": [{"var": "derived.has_tool_room_line"}, True]},
                         {">=": [{"var": "requirement.value_inr"}, 100000]},
                         {"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfq"]}]},
        "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}})


def a9(p):
    rule(p, "5.5")["then"]["suggest_count"] = 4
    rule(p, "5.5")["clause_text"] = "Value below 10,00,000. Suggest 4 suppliers (6.4). Amendment A-9."


def rule(p, rule_id):
    return next(r for r in p["rules"] if r["id"] == rule_id)


def insert_after(p, rule_id, new):
    at = [r["id"] for r in p["rules"]].index(rule_id) + 1
    p["rules"].insert(at, new)


@dataclass
class Amendment:
    id: str
    file: str
    upload_as: str  # "md" or "pdf"
    effective_from: str
    edit: object
    expect: object


AMENDMENTS = [
    Amendment("A1", "A1_limit_change.md", "md", "2026-12-01", a1, lambda: Expect("after the batch", no_change_reason=AFTER_BATCH)),
    Amendment("A2", "A2_chakan_controls.md", "md", "2026-12-01", a2, lambda: Expect("after the batch", no_change_reason=AFTER_BATCH)),
    Amendment("A3", "A3_price_variance.md", "md", "2027-01-01", a3, lambda: Expect("after the batch", no_change_reason=AFTER_BATCH)),
    Amendment("A4", "A4_rfq_ceiling.md", "pdf", "2026-11-01", a4, expect_a4),
    Amendment("A5", "A5_chakan_emergency.md", "md", "2026-11-01", a5, expect_a5),
    Amendment("A6", "A6_clubbing_window.md", "md", "2026-11-01", a6, expect_a6),
    Amendment("A7", "A7_office_it_quotes.md", "pdf", "2026-11-01", a7, expect_a7),
    Amendment("A8", "A8_tool_room_quotes.md", "md", "2026-11-01", a8, expect_a8),
    Amendment("A9", "A9_rfq_suggestions.md", "md", "2026-11-10", a9, expect_a9),
]


def pdf_bytes(markdown):
    """The amendment as a PDF (plain text, wrapped; the PDF font has no rupee sign)."""
    out = []
    for para in markdown.replace("₹", "Rs ").replace("**", "").replace("*", "").replace("# ", "").splitlines():
        out += textwrap.wrap(para, 90) or [""]
    return text_pdf(out)


def write_pdfs():
    for a in AMENDMENTS:
        if a.upload_as == "pdf":
            target = AMENDMENTS_DIR / a.file.replace(".md", ".pdf")
            target.write_bytes(pdf_bytes((AMENDMENTS_DIR / a.file).read_text(encoding="utf-8")))
            print("wrote", target.relative_to(ROOT))


def upload(a):
    text = (AMENDMENTS_DIR / a.file).read_text(encoding="utf-8")
    if a.upload_as == "pdf":
        pdf = AMENDMENTS_DIR / a.file.replace(".md", ".pdf")
        return pdf.name, pdf.read_bytes() if pdf.exists() else pdf_bytes(text), "application/pdf"
    return a.file, text.encode(), "text/markdown"


# ---------------------------------------------------------------- the run
def ok(response, *codes):
    if response.status_code not in (codes or (200, 201)):
        raise SystemExit(f"{response.request.method} {response.request.url}: {response.status_code} {response.text[:500]}")
    return response


def manual_draft(http, a, draft_id=None):
    if draft_id is None:
        draft_id = ok(http.post("/api/policies/drafts", json={"from_current": True}, headers={"x-user": "rehearsal"})).json()["id"]
    doc = http.get(f"/api/policies/{draft_id}").json()["document"]
    doc.update(effective_from=a.effective_from, source_document=a.file, change_summary=f"Amendment {a.id} (reference edit)")
    a.edit(doc)
    return ok(http.put(f"/api/policies/drafts/{draft_id}", content=json.dumps(doc), headers={"x-user": "rehearsal"})).json()


def export_diff(export):
    rows = {key(r): r for r in csv.DictReader(io.StringIO(export))}
    return {k for k in GOLD if any(rows[k][c] != GOLD[k][c] for c in
                                   ("decision", "route", "supplier_id", "unit_price", "group_value_inr", "suggested_supplier_ids"))}


def rehearse(http, use_llm):
    http.headers.update({"x-user": "rehearsal", "x-role": "Procurement"})  # policy changes need Procurement
    approved = [p for p in ok(http.get("/api/policies")).json() if p["status"] == "approved"]
    if [p["version"] for p in approved] != ["5.0"]:
        raise SystemExit(f"The rehearsal needs v5.0 as the only approved version; found {[p['version'] for p in approved]}")
    batch = ok(http.post("/api/process-batch", content=SAMPLE, headers={"x-user": "rehearsal"})).json()["batch_id"]
    results, llm_calls, llm_log, stopped = [], [], [], []
    for a in AMENDMENTS:
        r = {"id": a.id, "format": a.upload_as.upper(), "effective": a.effective_from, "llm": "", "problems": []}
        expect = a.expect()
        r["expected"] = expect.note
        view = None
        if use_llm:
            try:
                view, r["llm"] = llm_draft(http, a, batch, expect, llm_calls)
            except FreeTierRefused as exc:  # stop here, as instructed; report what was done so far
                stopped.append(str(exc))
                llm_log.append({"id": a.id, "stopped": str(exc)})
                break
            llm_log.append(r["llm"])
        if view is None:
            view = manual_draft(http, a)
            r["drafted_by"] = view["drafted_by"] + " (reference edit)"
        else:
            r["drafted_by"] = view["drafted_by"]
        if view["errors"]:
            r["problems"].append(f"draft invalid: {view['errors']}")
            results.append(r)
            ok(http.post(f"/api/policies/drafts/{view['id']}/discard", json={"comment": "rehearsal"}))
            continue
        r["diff"] = view["diff"]
        preview = ok(http.post(f"/api/policies/drafts/{view['id']}/preview?batch_id={batch}")).json()
        r["changed"], r["explanation"] = preview["changed"], preview["explanation"]
        r["problems"] += expect.problems(preview)
        ok(http.post(f"/api/policies/drafts/{view['id']}/approve?batch_id={batch}", headers=PROCUREMENT))
        run2 = ok(http.post("/api/process-batch?format=csv", content=SAMPLE, headers={"x-user": "rehearsal"})).text
        if export_diff(run2) != {c["line"] for c in preview["changes"]
                                 if set(c["changes"]) - {"grouped_with", "same_po_as"}}:
            r["problems"].append("Run 2 differs from the preview")
        r["run2_lines"] = len(export_diff(run2))
        run1 = ok(http.post("/api/process-batch?format=csv&policy_version=5.0", content=SAMPLE,
                            headers={"x-user": "rehearsal"})).text
        r["run1_golden"] = run1 == GOLDEN
        if not r["run1_golden"]:
            r["problems"].append("Run 1 under 5.0 is not the golden file")
        ok(http.post(f"/api/policies/{view['id']}/withdraw", json={"comment": "rehearsal"}, headers=PROCUREMENT))
        results.append(r)
    final = ok(http.post("/api/process-batch?format=csv", content=SAMPLE, headers={"x-user": "rehearsal"})).text
    return results, final == GOLDEN, llm_calls, llm_log, stopped


def reference_changes(a):
    """What the hand-made draft changes on the sample batch (pure engine, kit data)."""
    import copy
    from engine.impact import impact
    from engine.policy import load_policy
    doc = copy.deepcopy(load_policy("5.0"))
    doc.update(version="ref", supersedes="5.0", effective_from=a.effective_from)
    a.edit(doc)
    master = kit.load_master()
    lines = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
    return {c["line"]: c["changes"] for c in impact(lines, master, doc)["changes"]}


def prompt_size(a):
    from amendments.drafting import build_prompt
    from amendments.extract import extract_text
    from engine.policy import load_policy
    name, data, _ = upload(a)
    system, user = build_prompt(extract_text(name, data), load_policy("5.0"))
    return len(system) + len(user)


class FreeTierRefused(SystemExit):
    pass


def llm_draft(http, a, batch, expect, llm_calls):
    """Up to two real drafts. Returns (view of a correct draft or None, record for the report)."""
    import time
    reference = reference_changes(a)
    record = {"id": a.id, "prompt_chars": prompt_size(a), "tries": []}
    for attempt in (1, 2):
        name, data, ctype = upload(a)
        started = time.perf_counter()
        response = ok(http.post("/api/policies/drafts", files={"file": (name, data, ctype)},
                                headers={"x-user": "rehearsal"}), 202)
        body = response.json()
        while body["drafting_status"] == "drafting":  # the AI drafts in the background; poll until done
            time.sleep(2)
            body = ok(http.get(body["poll_url"])).json()
        seconds = round(time.perf_counter() - started, 1)
        attempts = [tuple(x) for x in body.get("llm_attempts", [])]
        llm_calls += attempts
        t = {"seconds": seconds, "llm_seconds": body.get("drafting_seconds"), "status": body["drafting_status"],
             "attempts": [" ".join(map(str, x)) for x in attempts]}
        record["tries"].append(t)
        if body["drafting_status"] != "ready":
            t["problems"] = [str(body.get("drafting_error", ""))[:300]]
            if any("429" in str(x[2]) for x in attempts):
                raise FreeTierRefused(f"The quota refused the call for {a.id}: {t['attempts']}")
            continue
        view = body
        t.update(drafted_by=view["drafted_by"], proposed_version=view.get("proposed_version"),
                 mode=view.get("draft_mode"), operations=view.get("operations"),
                 supersedes=view["document"].get("supersedes"), effective_from=view["effective_from"],
                 not_expressed=view["not_expressed"], translation_notes=view["translation_notes"],
                 output_chars=len(json.dumps(view["document"], ensure_ascii=False)), errors=view["errors"][:3])
        problems = []
        if view["errors"]:
            problems.append(f"{len(view['errors'])} validation errors")
        if view["effective_from"] != a.effective_from:
            problems.append(f"effective_from {view['effective_from']} (document says {a.effective_from})")
        if view["document"].get("supersedes") != "5.0":
            problems.append(f"supersedes {view['document'].get('supersedes')!r}")
        if not view["errors"] and view["effective_from"]:
            preview = ok(http.post(f"/api/policies/drafts/{view['id']}/preview?batch_id={batch}")).json()
            got = {c["line"]: c["changes"] for c in preview["changes"]}
            t["same_changes_as_reference"] = got == reference
            t["changed"] = len(got)
            if got != reference:
                problems.append(f"changes differ from the hand-made draft: {len(got)} vs {len(reference)} lines; "
                                f"only LLM {sorted(set(got) - set(reference))[:5]}, only reference "
                                f"{sorted(set(reference) - set(got))[:5]}, same lines but different "
                                f"{sorted(k for k in set(got) & set(reference) if got[k] != reference[k])[:5]}")
            problems += expect.problems(preview)
        t["problems"] = problems
        if not problems:
            return view, record
        ok(http.post(f"/api/policies/drafts/{view['id']}/discard", json={"comment": "rehearsal: wrong draft"}))
    return None, record


def report(results, reset_ok, llm_calls, llm_log, stopped, use_llm):
    out = [f"STOPPED: {stopped[0]}", ""] if stopped else []
    out += ["| Amendment | Upload | Effective | Drafted by | Expected (from the golden file) | Preview | Run 2 lines | Run 1 = golden | Result |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        out.append(f"| {r['id']} | {r['format']} | {r['effective']} | {r['drafted_by']} | {r['expected']} | "
                   f"{r.get('explanation', '-')} | {r.get('run2_lines', '-')} | {'yes' if r.get('run1_golden') else 'NO'} | "
                   f"{'as expected' if not r['problems'] else 'PROBLEM: ' + '; '.join(r['problems'])} |")
    if use_llm:
        out += ["", "LLM drafts (JSON):", "", "```json", json.dumps(llm_log, indent=1, ensure_ascii=False), "```"]
        answered = [c for c in llm_calls if c[2] == "answered"]
        out += ["", f"LLM calls: {len(llm_calls)} attempts, {len(answered)} answered "
                    f"({', '.join(sorted({f'{p}:{m}' for p, m, _ in answered})) or 'none'})"]
    out += ["", f"Reset to v5.0 (all rehearsal versions withdrawn), batch by date equals the golden file: "
                f"{'yes' if reset_ok else 'NO'}"]
    out += ["", "Plain-language diffs:", ""] + [f"- {r['id']}: " + " / ".join(r.get("diff", [])) for r in results]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", action="store_true", help="draft with the app's LLM (real calls)")
    parser.add_argument("--base-url", help="a running app; default: in-process on a temporary SQLite database")
    parser.add_argument("--out", help="also write the report to this file")
    parser.add_argument("--write-pdfs", action="store_true", help="(re)write the PDF versions of A4 and A7, then stop")
    args = parser.parse_args()
    if args.write_pdfs:
        return write_pdfs()
    if args.base_url:
        import httpx
        with httpx.Client(base_url=args.base_url, timeout=120) as http:
            results = rehearse(http, args.llm)
    else:
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # removed when the script ends
        tmp = tmp_dir.name
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'rehearsal.db'}"
        if args.llm:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        else:
            os.environ["LLM_MODELS"] = ""  # no model configured: a stray call would fail loudly, never reach Gemini
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as http:
            results = rehearse(http, args.llm)
    text = report(*results, args.llm)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    sys.exit(2 if results[4] else 0 if results[1] and not any(r["problems"] for r in results[0]) else 1)


def run_llm_guarded(fn):
    try:
        return fn()
    except FreeTierRefused as exc:
        print(f"STOPPED: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    run_llm_guarded(main)
