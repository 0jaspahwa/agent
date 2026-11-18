"""Apply one policy version's overrides, derived facts and ordered rules to already-computed facts.

This is the part of the engine that reads the policy document; clubbing, contracts, valuation and
ranking (which compute the facts) come later. Pure functions, no I/O apart from load_policy.
"""
import copy
import json
from pathlib import Path

from engine.logic import evaluate

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


def load_policy(version="5.0"):
    return json.loads((POLICY_DIR / f"v{version}.json").read_text(encoding="utf-8"))


def resolve_parameters(policy, line_facts):
    """Parameters after overrides. Overrides are tested at the override stage, on the (first) line and its
    matched item only ({"line": ..., "item": ...}); for each parameter the first matching override wins
    and its `set` fields replace the defaults."""
    params = copy.deepcopy(policy["parameters"])
    done = set()
    for override in policy.get("overrides", []):
        path = override["parameter"]
        if path not in done and evaluate(override["when"], {"line": line_facts.get("line"), "item": line_facts.get("item")}):
            target = params
            for part in path.split("."):
                target = target[part]
            target.update(override["set"])
            done.add(path)
    return params


def failed_line_checks(policy, line_facts):
    """[(check, missing fields)] for every line check that fires; any hit makes the line NOT_PROCESSED."""
    hits = []
    for check in policy.get("line_checks", []):
        missing = []
        if evaluate(check["when"], line_facts, missing):
            hits.append((check, missing))
    return hits


def decide(policy, facts, line_facts, skip=()):
    """Return (rule, data, missing): the first rule whose `when` holds, the data it was judged on
    (facts + params + derived), and {rule id or "derived.<name>": [missing field paths]} for every
    derived fact and rule evaluated on the way, so the reason can say e.g. "5.3 not met: value missing".
    Rules whose id is in `skip` are passed over (a PO rule whose supplier cannot be determined, D25)."""
    data = dict(facts, params=resolve_parameters(policy, line_facts), derived={})
    missing = {}
    for fact in policy.get("derived_facts", []):
        gaps = []
        data["derived"][fact["name"]] = evaluate(fact["expr"], data, gaps)
        if gaps:
            missing["derived." + fact["name"]] = gaps
    for rule in policy["rules"]:
        if rule["id"] in skip:
            continue
        gaps = []
        hit = evaluate(rule["when"], data, gaps)
        if gaps:
            missing[rule["id"]] = gaps
        if hit:
            return rule, data, missing
    raise LookupError("no rule matched: the policy has a gap")
