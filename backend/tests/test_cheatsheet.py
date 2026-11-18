"""Every snippet in docs/manual_amendment_cheatsheet.md, checked the way the manual amendment path uses it.

The cheat sheet marks each case with HTML comments (invisible when rendered): `<!-- case ID [meta] -->`, then edits
`<!-- set PATH -->`, `<!-- insert rules before|after ID -->`, `<!-- append LIST -->` (each followed by a ```json
block) or `<!-- remove rules ID -->`, then `<!-- expect -->` and the sentences the app shows, one per "> " line.

For each case: start from draft_from_current(v5.0) (what "Edit the current version by hand" calls), apply the edits,
then
- validate() reports no error (what the draft page's "Must be fixed before approval" shows);
- explain() gives exactly the expected sentences (What changes), ignoring the metadata lines unless the case is
  marked meta;
- the edited policy decides the whole sample batch without an error (kit needed);
- the same document through the real endpoints (from_current draft, PUT, GET) shows no error and the same sentences.

    python backend/tests/test_cheatsheet.py --fill    rewrites the expected sentences from the code (review them!)
"""
import copy
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amendments.drafting import draft_from_current  # noqa: E402
from engine.inputs import PolicyVersion  # noqa: E402
from engine.policy import load_policy  # noqa: E402
from engine.policy_check import validate  # noqa: E402
from engine.policy_explain import explain  # noqa: E402

DOC = Path(__file__).resolve().parents[2] / "docs" / "manual_amendment_cheatsheet.md"
META = ("Version:", "Supersedes:", "Effective from:", "Source document:", "Change summary:")
DEFAULT_EFFECTIVE = "2026-12-01"
PROCUREMENT = {"x-user": "Ojas", "x-role": "Procurement"}
TOKEN = re.compile(r"<!-- (case|set|insert|append|remove|expect)\b ?([^\n]*?) -->|```json\n([\s\S]*?)\n```|^> ([^\n]*)$",
                   re.M)


def parse(text=None):
    """[{"id", "meta", "ops": [(verb, args, value)], "expect": [sentences], "span": (start, end) of the expect lines}]"""
    text = DOC.read_text(encoding="utf-8") if text is None else text
    cases, pending = [], None
    for m in TOKEN.finditer(text):
        verb, args, block, quote = m.groups()
        if verb == "case":
            ident, *flags = args.split()
            cases.append({"id": ident, "meta": "meta" in flags, "ops": [], "expect": [], "span": None})
        elif verb in ("set", "insert", "append"):
            pending = (verb, args.split())
        elif verb == "remove":
            cases[-1]["ops"].append(("remove", args.split(), None))
        elif block is not None and pending:
            cases[-1]["ops"].append((*pending, json.loads(block)))
            pending = None
        elif verb == "expect":
            cases[-1]["span"] = [m.end() + 1, m.end() + 1]
        elif quote is not None and cases and cases[-1]["span"] and cases[-1]["span"][1] >= m.start() - 1:
            cases[-1]["expect"].append(quote.strip())
            cases[-1]["span"][1] = m.end() + 1
    return cases


def _steps(path):
    return [(name, key or None) for name, key in re.findall(r"([A-Za-z_]\w*)(?:\[([^\]]+)\])?", path)]


def _child(node, name, key):
    node = node[name]
    if key is None:
        return node
    id_key = "name" if name == "derived_facts" else "id"
    return next(e for e in node if e.get(id_key) == key)


def apply(doc, verb, args, value):
    if verb == "set":
        *parents, (name, key) = _steps(args[0])
        node = doc
        for step in parents:
            node = _child(node, *step)
        assert key is None, f"set ends on a list entry: {args[0]}"
        assert name in node, f"{args[0]}: no such key in the document"
        node[name] = value
    elif verb == "append":
        doc[args[0]].append(value)
    elif verb == "insert":
        section, where, ident = args
        ids = [e["id"] for e in doc[section]]
        doc[section].insert(ids.index(ident) + (where == "after"), value)
    elif verb == "remove":
        section, ident = args
        doc[section] = [e for e in doc[section] if e.get("id") != ident]
    else:
        raise ValueError(verb)


def build(case):
    """(base, edited document) for a case, starting exactly like the manual draft path."""
    base = load_policy("5.0")
    doc = copy.deepcopy(draft_from_current(base, "test", {"5.0"}).document)
    doc["effective_from"] = DEFAULT_EFFECTIVE
    for verb, args, value in case["ops"]:
        apply(doc, verb, args, copy.deepcopy(value))
    return base, doc


def shown(case, base, doc):
    sentences = explain(base, doc)
    return sentences if case["meta"] else [s for s in sentences if not s.startswith(META)]


CASES = parse()


def test_the_cheatsheet_covers_every_change_type():
    sections = {re.match(r"\d+", c["id"]).group() for c in CASES}
    assert sections == {str(n) for n in range(1, 15)}
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert all(c["ops"] and c["expect"] and "?" not in c["expect"] for c in CASES), "a case has no edit or no sentence"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_each_snippet_validates_and_shows_exactly_its_sentences(case):
    base, doc = build(case)
    errors, _warnings = validate(doc, base)
    assert errors == []
    assert shown(case, base, doc) == case["expect"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_each_snippet_decides_the_sample_batch(case):
    from kit_required import REASON
    from kitdata import DATA_DIR, kit_present
    if not kit_present():
        pytest.skip(REASON)
    from engine.pipeline import decide
    from loaders import kit
    master = kit.load_master()
    lines = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
    _base, doc = build(case)
    edited = PolicyVersion(doc["version"], date(2026, 11, 1), doc)  # in force for the whole November batch
    result = decide(lines, master, policies=(*master.policies, edited))
    assert len(result.rows) == len(lines)
    assert {row.values["policy_version"] for row in result.rows if row.values["route"] != "NOT_PROCESSED"} == {doc["version"]}


def test_the_manual_path_through_the_api_shows_the_same(client):
    for case in CASES:
        created = client.post("/api/policies/drafts", json={"from_current": True}, headers=PROCUREMENT)
        assert created.status_code == 201, created.text
        draft = created.json()
        base, doc = build(case)
        doc["version"] = draft["version"]  # the label the app proposed (labels used earlier in the loop are taken)
        saved = client.put(f"/api/policies/drafts/{draft['id']}", content=json.dumps(doc), headers=PROCUREMENT)
        assert saved.status_code == 200, (case["id"], saved.text)
        view = client.get(f"/api/policies/{draft['id']}", headers=PROCUREMENT).json()
        assert view["errors"] == [], (case["id"], view["errors"])
        assert view["diff"] == explain(base, doc), case["id"]
        assert client.post(f"/api/policies/drafts/{draft['id']}/discard", headers=PROCUREMENT).status_code == 200


def fill():
    """Rewrite every case's expected sentences from the code (for writing the cheat sheet; review the result)."""
    text = DOC.read_text(encoding="utf-8")
    for case in reversed(parse(text)):
        base, doc = build(case)
        errors, _ = validate(doc, base)
        assert not errors, (case["id"], errors)
        start, end = case["span"]
        text = text[:start] + "".join(f"> {s}\n" for s in shown(case, base, doc)) + text[end:]
    DOC.write_text(text, encoding="utf-8", newline="\n")
    print("filled", len(parse(text)), "cases")


if __name__ == "__main__" and "--fill" in sys.argv:
    fill()
