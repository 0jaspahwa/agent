"""H3: draft a new policy version from an amendment's text. The LLM only proposes; code validates (H4),
previews (H5) and a person approves (H6).

Two output shapes, chosen by DRAFT_MODE (D33):
- "operations" (default): the model returns the version label, effective date, change summary, the reviewer
  lists and a short list of change operations; code applies them to the base policy (amendments/operations.py).
  Short answers, and nothing outside the operations can change.
- "full_document": the model returns the complete new policy (the spike's shape), kept for comparison.
Either way the reviewer lists stay beside the document: not_expressed (what the policy cannot represent; the
amendment is never narrowed silently) and translation_notes. A draft without an effective date is incomplete.
"""
import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from amendments.operations import OperationError, apply_operations
from engine import facts as catalogue
from engine.logic import OPERATORS
from engine.policy_check import ROUTES

PROMPTS = Path(__file__).resolve().parents[1] / "llm" / "prompts"
PROMPT_FILES = {"operations": PROMPTS / "amendment_operations.md", "full_document": PROMPTS / "amendment_to_policy.md"}
SCHEMA_DOC = Path(__file__).resolve().parents[2] / "docs" / "policy_schema.md"
REVIEW_KEYS = ("not_expressed", "translation_notes")
MODES = tuple(PROMPT_FILES)
# Explanatory texts the model does not need to write correct operations (they stay in the real document).
LONG_TEXT_KEYS = {"clause_text", "description", "text", "decisions", "clause", "reason", "message",
                  "source_document", "change_summary"}


class DraftError(ValueError):
    pass


@dataclass
class Draft:
    document: dict  # the proposed policy document, without the reviewer lists
    not_expressed: list = field(default_factory=list)
    translation_notes: list = field(default_factory=list)
    drafted_by: str = "manual"  # "llm:<provider>:<model>" or "manual:<name>"
    attempts: list = field(default_factory=list)
    mode: str = "manual"
    operations: list | None = None  # what the model proposed, in operations mode

    @property
    def incomplete(self):
        return not self.document.get("effective_from")


def draft_mode(env=os.environ):
    mode = (env.get("DRAFT_MODE") or "operations").strip().lower()
    if mode not in MODES:
        raise DraftError(f"DRAFT_MODE must be one of {', '.join(MODES)}, not {mode!r}")
    return mode


def next_version(label, taken=()):
    """'5.0' -> '5.1', skipping labels already used."""
    major, _, minor = str(label).partition(".")
    n = int(minor) + 1 if minor.isdigit() else 1
    while f"{major}.{n}" in set(taken):
        n += 1
    return f"{major}.{n}"


def compact_catalogue():
    """One line per object, e.g. 'item: item_code string, category string?, ...', per stage."""
    out = []
    for stage, fields in catalogue.SCOPES.items():
        groups = {}
        for path, kind in fields.items():
            prefix, _, name = path.rpartition(".")
            groups.setdefault(prefix or "(top)", []).append(f"{name} {kind}")
        out.append(f"[{stage} stage]")
        out += [f"{prefix}: {', '.join(names)}" for prefix, names in groups.items()]
    return "\n".join(out)


def compact_policy(node):
    """The policy without long explanatory texts, as compact JSON."""
    def strip(n):
        if isinstance(n, dict):
            return {k: strip(v) for k, v in n.items() if k not in LONG_TEXT_KEYS}
        if isinstance(n, list):
            return [strip(v) for v in n]
        return n
    return json.dumps(strip(node), ensure_ascii=False, separators=(",", ":"))


def build_prompt(amendment_text, base, mode="operations"):
    system, user = PROMPT_FILES[mode].read_text(encoding="utf-8").split("---USER---", 1)
    fills = {"{operators}": ", ".join(sorted(OPERATORS)), "{routes}": ", ".join(f'"{r}"' for r in sorted(ROUTES)),
             "{current_version}": base["version"], "{amendment}": amendment_text}
    if mode == "operations":
        fills.update({"{catalogue}": compact_catalogue(), "{current_policy}": compact_policy(base)})
    else:
        cat = {f"{stage}_stage": fields for stage, fields in catalogue.SCOPES.items()}
        fills.update({"{schema}": SCHEMA_DOC.read_text(encoding="utf-8"), "{catalogue}": json.dumps(cat, indent=1),
                      "{current_policy}": json.dumps(base, indent=1, ensure_ascii=False)})
    for token, value in fills.items():
        system, user = system.replace(token, value), user.replace(token, value)
    return system.strip(), user.strip()


def _json_object(text):
    text = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    try:
        value = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as exc:
        raise DraftError(f"The AI's draft was not valid JSON ({exc.msg} at character {exc.pos}). Try again, or start "
                         f"from the current policy and edit it.") from exc
    if not isinstance(value, dict):
        raise DraftError("The AI's draft was not a policy document (expected a JSON object).")
    return value


def parse_reply(text):
    """Full-document mode: (document, reviewer lists)."""
    document = _json_object(text)
    lists = {k: [str(x) for x in (document.pop(k, None) or [])] for k in REVIEW_KEYS}
    return document, lists


def parse_operations_reply(text, base):
    """Operations mode: (document with the operations applied, reviewer lists, operations)."""
    reply = _json_object(text)
    operations = reply.get("operations")
    if not isinstance(operations, list):
        raise DraftError("The AI's draft has no list of operations. Try again, or start from the current policy "
                         "and edit it.")
    try:
        document = apply_operations(base, operations)
    except OperationError as exc:
        raise DraftError(f"The AI's draft could not be applied: {exc}. Try again, or start from the current "
                         f"policy and edit it.") from exc
    document.update(version=str(reply.get("version") or next_version(base["version"])), supersedes=base["version"],
                    effective_from=reply.get("effective_from") or None,
                    source_document=str(reply.get("source_document") or "amendment"),
                    change_summary=str(reply.get("change_summary") or ""))
    lists = {k: [str(x) for x in (reply.get(k) or [])] for k in REVIEW_KEYS}
    return document, lists, operations


def draft_with_llm(amendment_text, base, client, mode=None):
    """Raises llm.client.LLMError (service unavailable) or DraftError (unusable reply)."""
    mode = mode or draft_mode()
    result = client.complete(*build_prompt(amendment_text, base, mode))
    if mode == "operations":
        document, lists, operations = parse_operations_reply(result.text, base)
    else:
        (document, lists), operations = parse_reply(result.text), None
    return Draft(document, lists["not_expressed"], lists["translation_notes"],
                 f"llm:{result.provider}:{result.model}", [list(a) for a in result.attempts], mode, operations)


def draft_from_current(base, user, taken=(), version=None, effective_from=None, change_summary=None):
    """A draft that starts as a copy of the base version, for hand editing when no LLM is wanted or available."""
    document = copy.deepcopy(base)
    document.update(version=version or next_version(base["version"], taken), supersedes=base["version"],
                    effective_from=effective_from, source_document="entered by hand",
                    change_summary=change_summary or f"Hand edit of version {base['version']}")
    return Draft(document, drafted_by=f"manual:{user}")
