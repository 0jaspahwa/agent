"""Spike: can an LLM turn a plain-English amendment into a valid, correct new policy version?

For each run it sends the prompt (scripts/prompts/amendment_to_policy.md, filled with the schema doc,
the fact catalogue, the current policy and the amendment) to the configured LLM, then:
  1. parses the reply as JSON,
  2. validates it with engine.policy_check.validate (including the unknown-field check),
  3. prints a field-by-field diff against v5.0,
  4. runs the amendment's checks file (<amendment>.checks.json): expected parameters, overrides,
     new rules and derived facts, routes for hand-built cases, and no changes outside the allowed paths.
The LLM only drafts the document. Nothing here decides a purchase.

  python scripts/try_amendment.py docs/sample_amendments/A1_limit_change.md --runs 3
  python scripts/try_amendment.py --all --runs 3           # all sample amendments + summary table
  python scripts/try_amendment.py <amendment.md> --print-prompt
  python scripts/try_amendment.py <amendment.md> --candidate draft.json   # check a saved draft, no LLM call
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from engine import facts as catalogue  # noqa: E402
from engine.logic import OPERATORS, get_path  # noqa: E402
from engine.policy import decide, load_policy, resolve_parameters  # noqa: E402
from engine.policy_check import ROUTES, validate  # noqa: E402
from engine.policy_diff import diff, format_diff  # noqa: E402

load_dotenv(ROOT / ".env")
sys.stdout.reconfigure(encoding="utf-8")  # the Windows console default (cp1252) cannot print ₹ or →

# ---- The one setting: which provider drafts the policy (LLM_PROVIDER in .env). ----
PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
DEFAULT_MODELS = {}  # no guessed default: run --list-models and set LLM_MODEL in .env
MODEL = os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(PROVIDER)
AMENDMENTS = ROOT / "docs" / "sample_amendments"
OUT = ROOT / "scripts" / "out"


def call_gemini(system, user, model):
    key = os.getenv("GEMINI") or os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("No Gemini key: set GEMINI=... in .env")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(1, 5):  # retry only transient trouble (overload, timeout), never a quota error
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                reply = json.loads(response.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"Gemini HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc
        except TimeoutError:
            if attempt == 4:
                raise
        print(f"   transient error, retrying in {30 * attempt}s (attempt {attempt}/4)")
        time.sleep(30 * attempt)
    parts = get_path(reply, "candidates.0.content.parts") or []
    return "".join(p.get("text", "") for p in parts)


def list_gemini_models():
    """Models this key can call with generateContent: [(name, display name, output token limit)]."""
    key = os.getenv("GEMINI") or os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("No Gemini key: set GEMINI=... in .env")
    models, token = [], ""
    while True:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000" + (f"&pageToken={token}" if token else "")
        request = urllib.request.Request(url, headers={"x-goog-api-key": key})
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.loads(response.read())
        models += [(m["name"].removeprefix("models/"), m.get("displayName", ""), m.get("outputTokenLimit"))
                   for m in page.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        token = page.get("nextPageToken")
        if not token:
            return models


# To add a provider: write call_<name>(system, user, model) -> str and register it here.
PROVIDERS = {"gemini": call_gemini}
MODEL_LISTERS = {"gemini": list_gemini_models}


def build_prompt(amendment_text, current):
    template = (ROOT / "backend" / "llm" / "prompts" / "amendment_to_policy.md").read_text(encoding="utf-8")
    system, user = template.split("---USER---", 1)
    cat = {f"{stage}_stage": fields for stage, fields in catalogue.SCOPES.items()}
    fills = {
        "{operators}": ", ".join(sorted(OPERATORS)),
        "{routes}": ", ".join(f'"{r}"' for r in sorted(ROUTES)),
        "{schema}": (ROOT / "docs" / "policy_schema.md").read_text(encoding="utf-8"),
        "{catalogue}": json.dumps(cat, indent=1),
        "{current_version}": current["version"],
        "{current_policy}": json.dumps(current, indent=1, ensure_ascii=False),
        "{amendment}": amendment_text,
    }
    for token, value in fills.items():
        system, user = system.replace(token, value), user.replace(token, value)
    return system.strip(), user.strip()


def parse_json(text):
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


# ---- Checks against the amendment's .checks.json ----
def case_facts(case):
    """Requirement- and line-level facts for one hand-built case (only the fields the checks need)."""
    plant = {"plant": case["plant"], "name": case["plant"]}
    item = None if case.get("new_item") else {
        "item_code": "ITM-TEST", "description": "test item", "uom": "NOS",
        "category": case.get("category", "Fasteners"), "item_type": case.get("item_type", "Material"),
        "standard_price": case.get("standard_price", 100)}
    lines = [{"pr_no": "PR-TEST", "pr_line": i + 1, "plant": case["plant"], "urgency": u, "quantity": 1,
              "created_at": "2027-01-10 10:00", "need_by_date": "2027-01-25"}
             for i, u in enumerate(case.get("urgency", ["Normal"]))]
    source = case.get("valuation_source", "latest_po_in_window")
    price = case.get("valuation_price")
    facts = {
        "requirement": {"value_inr": case["value"], "is_new_item": bool(case.get("new_item")),
                        "plant": case["plant"], "date": "2027-01-10", "line_count": len(lines),
                        "valuation_price": price, "valuation_source": source},
        "first_line": lines[0], "lines": lines, "item": item, "plant": plant,
        "contract": {"usable": case.get("contract_usable", False), "any_applicable": case.get("contract_usable", False)},
        "history": {"bought_from_active": case.get("bought_from_active", True),
                    "latest_po_price": price if source == "latest_po_in_window" else None},
    }
    return facts, {"line": lines[0], "item": item, "plant": plant}


def run_checks(policy, current, checks):
    """Return (failures, notes). Only wrong behaviour or a wrong structure the amendment demands is a
    failure; a style difference that behaves the same (e.g. a formula inlined in the rule instead of a
    derived fact) is a note."""
    fails, notes = [], []
    if policy.get("effective_from") != checks["effective_from"]:
        fails.append(f"effective_from is {policy.get('effective_from')!r}, expected {checks['effective_from']!r}")
    for path, expected in checks.get("expect_parameters", {}).items():
        actual = get_path(policy["parameters"], path)
        if actual != expected:
            fails.append(f"parameter {path} is {actual!r}, expected {expected!r}")
    for path in checks.get("require_override_for", []):
        if not any(o.get("parameter") == path for o in policy.get("overrides") or []):
            fails.append(f"no override for {path} (the plant-specific number should be an override, not a rule)")
    for exp in checks.get("expect_resolved_parameters", []):
        line = {"line": {"plant": exp["plant"]}, "plant": {"plant": exp["plant"], "name": exp["plant"]}, "item": None}
        actual = get_path(resolve_parameters(policy, line), exp["path"])
        if actual != exp["equals"]:
            fails.append(f"at {exp['plant']}, {exp['path']} resolves to {actual!r}, expected {exp['equals']!r}")
    old_ids = [r["id"] for r in current["rules"]]
    new_ids = [r.get("id") for r in policy["rules"]]
    added = [r for r in policy["rules"] if r.get("id") not in old_ids]
    for need in checks.get("require_new_rules", []):
        ok = [r for r in added if (r.get("then") or {}).get("route") == need["route"]
              and (r.get("then") or {}).get("suggest_count") == need["suggest_count"]
              and need["after"] in new_ids and need["before"] in new_ids
              and new_ids.index(need["after"]) < new_ids.index(r["id"]) < new_ids.index(need["before"])]
        if not ok:
            fails.append(f"no new {need['route']} rule (suggest {need['suggest_count']}) between {need['after']} "
                         f"and {need['before']}; new rules: {[r.get('id') for r in added]}, order: {new_ids}")
    if [i for i in new_ids if i in old_ids] != old_ids:
        fails.append(f"existing rules were removed or reordered: {new_ids}")
    want = checks.get("expect_new_derived_facts", 0)
    got = len(policy.get("derived_facts") or []) - len(current.get("derived_facts") or [])
    if got != want:
        notes.append(f"{got} new derived fact(s), expected {want} (style only: routes decide pass/fail)")
    for case in checks["cases"]:
        facts, line_facts = case_facts(case)
        try:
            rule, _data, missing = decide(policy, facts, line_facts)
            route = rule["then"]["route"]
        except Exception as exc:  # a broken draft must be reported, not crash the spike
            fails.append(f"case '{case['name']}': evaluation error {exc}")
            continue
        if route != case["expect_route"]:
            note = f"; missing fields {missing}" if missing else ""
            fails.append(f"case '{case['name']}': {route} via rule {rule['id']}, expected {case['expect_route']}{note}")
    allowed = ("version", "supersedes", "effective_from", "source_document", "change_summary",
               "translation_notes", "not_expressed", *checks.get("allowed_change_prefixes", []))
    for kind, path, _old, new in diff(current, policy):
        if path.startswith(allowed):
            continue
        if kind == "+" and path.startswith("parameters."):
            # A brand-new parameter changes nothing by itself; the route cases judge how it is used.
            notes.append(f"new parameter {path} = {new!r}")
        else:
            fails.append(f"unexpected change {kind} {path}")
    return fails, notes


def self_check(current, checks, name):
    """Each case must give its stated v5_route under the current policy, or the case itself is wrong."""
    for case in checks["cases"]:
        facts, line_facts = case_facts(case)
        route = decide(current, facts, line_facts)[0]["then"]["route"]
        if route != case["v5_route"]:
            sys.exit(f"{name}: case '{case['name']}' gives {route} under v{current['version']}, "
                     f"checks file says {case['v5_route']}; fix the checks file first")


def check_draft(text, current, checks):
    """Return (valid, correct, notes) for one draft."""
    try:
        policy = parse_json(text)
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"  NOT JSON: {exc}")
        return False, False, [f"not JSON: {exc}"]
    lists = {k: policy.pop(k, None) or [] for k in ("not_expressed", "translation_notes")}  # as the app does
    policy["translation_notes"] = lists["translation_notes"]
    if not policy["translation_notes"]:
        policy.pop("translation_notes")
    for item in lists["not_expressed"]:
        print(f"  not expressed: {item}")
    errors, warnings = validate(policy, current)
    print(f"  validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    for e in errors + [f"(warning) {w}" for w in warnings]:
        print(f"    {e}")
    print("  diff against v" + current["version"] + ":")
    print("    " + format_diff(diff(current, policy)).replace("\n", "\n    "))
    for note in policy.get("translation_notes") or []:
        print(f"  translation note: {note}")
    if errors:
        return False, False, errors[:3]
    fails, notes = run_checks(policy, current, checks)
    print(f"  checks: {'all passed' if not fails else str(len(fails)) + ' failed'}")
    for f in fails:
        print(f"    FAIL {f}")
    for n in notes:
        print(f"    NOTE {n}")
    return True, not fails, (fails or [f"passed; note: {n}" for n in notes])[:3]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("amendment", nargs="?", help="amendment .md file")
    parser.add_argument("--all", action="store_true", help="every amendment in docs/sample_amendments")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--print-prompt", action="store_true")
    parser.add_argument("--candidate", help="check this saved JSON draft instead of calling the LLM")
    parser.add_argument("--list-models", action="store_true", help="list the models the provider key can use")
    args = parser.parse_args()
    if args.list_models:
        for name, display, out_limit in MODEL_LISTERS[PROVIDER]():
            print(f"{name:45} {display:40} output tokens {out_limit}")
        return
    files = sorted(AMENDMENTS.glob("*.md")) if args.all else [Path(args.amendment)] if args.amendment else []
    if not files:
        parser.error("give an amendment file or --all")
    current = load_policy("5.0")
    summary = []
    for path in files:
        checks = json.loads(path.with_suffix(".checks.json").read_text(encoding="utf-8"))
        self_check(current, checks, path.name)
        system, user = build_prompt(path.read_text(encoding="utf-8"), current)
        if args.print_prompt:
            print(f"===== SYSTEM =====\n{system}\n\n===== USER =====\n{user}")
            continue
        print(f"\n######## {path.name}: {checks['what_it_tests']}")
        drafts = []
        if args.candidate:
            drafts = [("candidate", Path(args.candidate).read_text(encoding="utf-8"))]
        else:
            if PROVIDER not in PROVIDERS:
                sys.exit(f"LLM_PROVIDER={PROVIDER!r} is not one of {sorted(PROVIDERS)}")
            OUT.mkdir(parents=True, exist_ok=True)
            for n in range(1, args.runs + 1):
                print(f"-- run {n}: calling {PROVIDER} / {MODEL} ...")
                try:
                    text = PROVIDERS[PROVIDER](system, user, MODEL)
                except Exception as exc:  # report the failure and carry on with the next run
                    text = f"<<call failed: {exc}>>"
                (OUT / f"{path.stem}_run{n}.json").write_text(text, encoding="utf-8")
                drafts.append((f"run {n}", text))
        results = []
        for label, text in drafts:
            print(f"\n== {path.name} {label}")
            results.append(check_draft(text, current, checks))
        summary.append((path.stem, len(results), sum(r[0] for r in results), sum(r[1] for r in results),
                        "; ".join(dict.fromkeys(n for r in results for n in r[2]))[:300]))
    if summary:
        print("\n| Amendment | Runs | Valid | Correct | Failure notes |\n|---|---|---|---|---|")
        for stem, runs, valid, correct, notes in summary:
            print(f"| {stem} | {runs} | {valid}/{runs} | {correct}/{runs} | {notes or '-'} |")


if __name__ == "__main__":
    main()
