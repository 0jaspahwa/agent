"""B2: reading a chat message. The LLM only extracts the facts in it (as raw phrases); code normalises them with
the same functions the pattern reader uses, so a plant, a date or a unit means exactly the same whichever read
it. If the LLM is unavailable or its answer is unusable, the pattern reader (chat/reader.py) is used instead.

Short answers to the question just asked ("300", "Chakan", "yes") are read by the pattern reader without the
LLM: they are unambiguous, and the reply comes at once (DECISIONS.md D39).
"""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from chat import reader
from llm.client import LLMError

PROMPT = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "chat_extract.md"
QUESTION_WORDS = {None: "nothing yet (this is the first message)", "item": "what item is needed",
                  "item_detail": "for more detail about the item (size, grade or model)",
                  "choose_item": "which of the listed items is meant", "new_item_offer": "whether to raise a new item",
                  "quantity": "how many are needed", "price": "the estimated price per unit, in rupees",
                  "unit": "the unit the item is bought in", "plant": "which plant it is for",
                  "need_by": "the need-by date", "urgency": "whether it is an emergency", "confirm":
                  "to confirm the request shown"}


def answers_pending(r, pending):
    """True if the pattern reader alone answers the question that was asked (or cancels or confirms)."""
    if r.cancel or (pending == "confirm" and r.confirm):
        return True
    return {"quantity": r.quantity is not None and not r.items, "price": r.price is not None,
            "unit": r.unit is not None, "plant": bool(r.plant or r.plant_unknown), "need_by": r.need_by is not None,
            "urgency": r.urgency is not None}.get(pending, False)


def _number(value):
    try:
        return None if value is None or isinstance(value, bool) else Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def to_reading(data, today, aliases, pending):
    """The LLM's raw facts, normalised by the reader's own rules."""
    r = reader.Reading()
    intent = str(data.get("intent") or "")
    r.confirm, r.cancel = intent == "confirm", intent == "cancel"
    r.correction, r.policy_change = intent == "correction", intent == "policy_change"
    r.instruction = intent == "other" and bool(reader.INSTRUCTION.search(json.dumps(data)))
    for item in data.get("items") or []:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            unit = reader.UNITS.get(str(item.get("unit") or "").strip().lower())
            r.items.append({"text": str(item["text"]).strip()[:200], "quantity": _number(item.get("quantity")), "unit": unit})
    r.quantity = _number(data.get("quantity"))
    r.price = _number(data.get("unit_price"))
    plant = str(data.get("plant") or "").strip()
    if plant:
        r.plant = next((code for word, code in aliases.items() if re.search(rf"\b{re.escape(word)}\b", plant.lower())), None)
        r.plant_unknown = None if r.plant else plant.upper()
    if data.get("need_by"):
        r.need_by, r.date_text = reader.read_date(str(data["need_by"]), today)
    urgency = str(data.get("urgency") or "").lower()
    r.urgency = {"emergency": "Emergency", "normal": "Normal"}.get(urgency)
    r.urgency_hint = urgency == "urgent"
    return r


def read_message(text, today, aliases, pending, client):
    """(reading, how): how is 'reader', 'llm:<model>', or 'reader (AI unavailable)'."""
    quick = reader.read(text, today, aliases, pending)
    if client is None or answers_pending(quick, pending):
        return quick, "reader"
    system, user = PROMPT.read_text(encoding="utf-8").split("---USER---", 1)
    user = user.replace("{today}", today.isoformat()).replace("{pending}", QUESTION_WORDS.get(pending, str(pending)))
    user = user.replace("{message}", text)
    try:
        result = client.complete(system.strip(), user.strip())
        raw = result.text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (LLMError, ValueError) as exc:
        return quick, f"reader (AI unavailable: {str(exc)[:120]})"
    r = to_reading(data, today, aliases, pending)
    r.instruction = r.instruction or quick.instruction  # the code's own check always applies too
    if r.instruction:
        r.items = []
    return r, f"llm:{result.provider}:{result.model}"
