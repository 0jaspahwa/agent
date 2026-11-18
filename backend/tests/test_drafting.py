"""H3: drafting a policy version, with a fake LLM only."""
import copy
import json

import pytest

from amendments.drafting import DraftError, build_prompt, draft_from_current, draft_with_llm, next_version, parse_reply
from engine.policy import load_policy
from llm.client import LLMClient, LLMError, Unavailable

BASE = load_policy("5.0")


def fake_client(*replies):
    queue = list(replies)

    def call(system, user, model):
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return LLMClient([("fake", "model-a"), ("fake", "model-b")], {"fake": call}, sleep=lambda s: None)


def proposed(**changes):
    doc = copy.deepcopy(BASE)
    doc.update(version="5.1", supersedes="5.0", effective_from="2026-12-01", source_document="A-1",
               change_summary="spot limit lowered")
    doc["parameters"]["limits"]["spot_po"].update(value=150000, operator="<=")
    doc.update(changes)
    return doc


def test_the_prompt_carries_the_base_policy_schema_catalogue_and_amendment():
    system, user = build_prompt("Spot limit at or below 1,50,000 from 1 Dec 2026.", BASE, "full_document")
    assert "not_expressed" in system and "never invent one" in system
    assert '"version": "5.0"' in user and "Spot limit at or below" in user and "line_check_stage" in user


def test_a_good_reply_becomes_a_draft_with_the_reviewer_lists_kept_apart():
    reply = json.dumps({**proposed(), "not_expressed": ["CFO sign-off by email"], "translation_notes": ["n1"]})
    d = draft_with_llm("amendment", BASE, mode="full_document", client=fake_client(reply))
    assert d.document["parameters"]["limits"]["spot_po"] == {**BASE["parameters"]["limits"]["spot_po"], "value": 150000, "operator": "<="}
    assert (d.not_expressed, d.translation_notes, d.incomplete) == (["CFO sign-off by email"], ["n1"], False)
    assert "not_expressed" not in d.document and d.drafted_by == "llm:fake:model-a"


def test_a_fenced_reply_is_accepted_and_the_answering_model_is_recorded():
    reply = "```json\n" + json.dumps(proposed()) + "\n```"
    d = draft_with_llm("amendment", BASE, mode="full_document", client=fake_client(Unavailable("HTTP 429"), reply))
    assert d.drafted_by == "llm:fake:model-b" and [a[2] for a in d.attempts] == ["unavailable: HTTP 429", "answered"]


def test_no_effective_date_makes_the_draft_incomplete():
    d = draft_with_llm("amendment", BASE, mode="full_document", client=fake_client(json.dumps(proposed(effective_from=None))))
    assert d.incomplete


@pytest.mark.parametrize("reply, message", [("not json at all", "not valid JSON"), ("[1, 2]", "not a policy document")])
def test_an_unusable_reply_is_a_plain_error(reply, message):
    with pytest.raises(DraftError, match=message):
        draft_with_llm("amendment", BASE, mode="full_document", client=fake_client(reply))


def test_an_llm_outage_is_reported_and_the_manual_path_still_works():
    with pytest.raises(LLMError, match="unavailable right now"):
        draft_with_llm("amendment", BASE, mode="full_document", client=fake_client(Unavailable("429"), Unavailable("429")))
    d = draft_from_current(BASE, "Ojas", taken=["5.0", "5.1"])
    assert (d.document["version"], d.document["supersedes"], d.drafted_by, d.incomplete) == ("5.2", "5.0", "manual:Ojas", True)
    assert d.document["rules"] == BASE["rules"]


def test_next_version_skips_labels_in_use():
    assert (next_version("5.0"), next_version("5.0", ["5.1"]), next_version("5")) == ("5.1", "5.2", "5.1")


def test_parse_reply_removes_only_the_reviewer_lists():
    doc, lists = parse_reply(json.dumps({"version": "5.1", "not_expressed": ["x"]}))
    assert doc == {"version": "5.1"} and lists == {"not_expressed": ["x"], "translation_notes": []}



# ---------------------------------------------------------------- operations mode (the default, D33)
from amendments.drafting import (LONG_TEXT_KEYS, PROMPT_FILES, compact_policy, draft_mode,  # noqa: E402
                                 parse_operations_reply)
from engine.policy_check import validate  # noqa: E402


def ops_reply(operations, **fields):
    return json.dumps({"version": "5.1", "effective_from": "2026-12-01", "change_summary": "spot limit lowered",
                       "source_document": "A-1", "operations": operations, "not_expressed": ["email sign-off"],
                       "translation_notes": [], **fields})


SPOT = [{"op": "set", "path": "parameters.limits.spot_po.value", "value": 150000},
        {"op": "set", "path": "parameters.limits.spot_po.operator", "value": "<="}]


def test_operations_mode_is_the_default_and_full_document_stays_available():
    assert draft_mode({}) == "operations" and draft_mode({"DRAFT_MODE": "full_document"}) == "full_document"
    with pytest.raises(DraftError, match="DRAFT_MODE"):
        draft_mode({"DRAFT_MODE": "patch"})


def test_an_operations_reply_is_applied_to_the_base_and_validates():
    d = draft_with_llm("amendment", BASE, fake_client(ops_reply(SPOT)))
    assert d.mode == "operations" and d.operations == SPOT and d.not_expressed == ["email sign-off"]
    assert d.document["parameters"]["limits"]["spot_po"]["value"] == 150000
    assert (d.document["version"], d.document["supersedes"], d.document["effective_from"]) == ("5.1", "5.0", "2026-12-01")
    assert d.document["rules"] == BASE["rules"] and validate(d.document, BASE)[0] == []


def test_an_operation_that_cannot_be_applied_fails_the_draft_plainly():
    bad = SPOT + [{"op": "add", "section": "rules", "after": "9.9", "item": {"id": "5.3C"}}]
    with pytest.raises(DraftError, match=r"could not be applied: Operation 3 .*no rule '9.9'"):
        draft_with_llm("amendment", BASE, fake_client(ops_reply(bad)))
    with pytest.raises(DraftError, match="no list of operations"):
        parse_operations_reply(json.dumps({"version": "5.1"}), BASE)


def test_a_missing_effective_date_or_label_is_handled():
    doc, _, _ = parse_operations_reply(ops_reply(SPOT, effective_from=None, version=None), BASE)
    assert doc["effective_from"] is None and doc["version"] == "5.1"


def test_the_operations_prompt_is_short_and_leaves_out_long_texts():
    system, user = build_prompt("Spot limit at or below 1,50,000 from 1 Dec 2026.", BASE)
    assert len(system) + len(user) < 20000  # the full-document prompt is about 55,000 characters
    assert "Spot limit at or below" in user and "requirement: " in user and '"id":"5.3"' in user
    assert all(f'"{k}":' not in compact_policy(BASE) for k in LONG_TEXT_KEYS)


def test_the_prompts_worked_examples_apply_and_validate():
    import re
    text = PROMPT_FILES["operations"].read_text(encoding="utf-8").split("---USER---")[0].split("EXAMPLES")[1]
    examples = [json.loads(line) for line in text.splitlines() if line.startswith('{"version"')]
    assert len(examples) == 3
    for example in examples:
        doc, _, _ = parse_operations_reply(json.dumps(example), BASE)
        doc["effective_from"] = doc["effective_from"] or "2026-12-01"
        assert validate(doc, BASE)[0] == [], example["source_document"]
