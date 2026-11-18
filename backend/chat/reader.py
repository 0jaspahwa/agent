"""B2: the pattern-based reader for chat intake (DECISIONS.md D39). Pure, deterministic, no LLM.

It pulls out what a requester's message says: items with quantities and units, plant, need-by date, urgency,
an estimated unit price, and whether the message confirms, cancels or corrects. It is used when the LLM is
unavailable, and for short answers to the question just asked. It never decides an item: item text goes to
the deterministic matcher (engine/matching.py).

Dates are resolved against `today` and always repeated back to the user. "next Friday" is the first Friday after
today (DECISIONS.md D40).
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
UNITS = {"pcs": "NOS", "pc": "NOS", "piece": "NOS", "pieces": "NOS", "nos": "NOS", "no": "NOS", "numbers": "NOS",
         "each": "NOS", "units": "NOS", "unit": "NOS", "pair": "PAIR", "pairs": "PAIR", "kg": "KG", "kgs": "KG",
         "kilo": "KG", "kilos": "KG", "kilograms": "KG", "litre": "LTR", "litres": "LTR", "liter": "LTR",
         "liters": "LTR", "ltr": "LTR", "l": "LTR", "metre": "MTR", "metres": "MTR", "meter": "MTR", "meters": "MTR",
         "m": "MTR", "mtr": "MTR", "box": "BOX", "boxes": "BOX", "set": "SET", "sets": "SET", "roll": "ROLL",
         "rolls": "ROLL", "drum": "DRUM", "drums": "DRUM", "pack": "PACK", "packs": "PACK", "packet": "PACK",
         "packets": "PACK", "sheet": "NOS", "sheets": "NOS"}
EMERGENCY_WORDS = ("emergency", "breakdown", "line down", "line is down", "plant stopped")
URGENT_WORDS = ("urgent", "urgently", "asap", "as soon as possible", "immediately", "quickly", "rush")
CONFIRM = re.compile(r"^\s*(yes|yep|yeah|ok|okay|confirm|confirmed|create( it)?|go ahead|looks good|correct|"
                     r"that'?s (right|correct)|place it|submit( it)?)\b[\s.!]*$", re.I)
CANCEL = re.compile(r"\b(cancel|discard|never ?mind|forget it|scrap (it|that)|stop)\b", re.I)
CORRECTION = re.compile(r"\b(actually|make it|change|instead|correction|sorry|not .* but|update)\b", re.I)
POLICY = re.compile(r"\b(policy|clause|amend|amendment|threshold|rules? \d|(?:spot|rfq|rfp|emergency|po|value) "
                    r"limit|limits? (?:should|to|from|is|of))\b", re.I)
# Text that tries to instruct the assistant: it is data, never an instruction (it changes nothing).
INSTRUCTION = re.compile(r"\b(ignore|disregard|bypass|override|approve|system prompt|your (?:rules|instructions)|"
                         r"pretend|jailbreak)\b", re.I)
FILLER = re.compile(r"^(?:hi|hello|hey|please|pls|kindly|we|i|need|needs|want|wants|would like|require|"
                    r"actually|instead|sorry|no|change|make|it|correction|update|rather|"
                    r"requires|order|get|buy|raise|request|for|some|a|an|the|few|of|to|me|us|new|more|also|and)\b\s*",
                    re.I)
ITEM_END = re.compile(r"\s+(?:for|by|at|before|on|needed|required|urgent|urgently|asap|in|to be|delivered|"
                      r"from|plant|deliver)\b.*$", re.I)
NUMBER = r"(\d+(?:[.,]\d+)?)"


@dataclass
class Reading:
    items: list = field(default_factory=list)  # [{"text", "quantity" (Decimal | None), "unit" (canonical | None)}]
    quantity: Decimal | None = None  # a quantity on its own ("make it 300", "300")
    unit: str | None = None
    plant: str | None = None  # a plant code
    plant_unknown: str | None = None  # a plant was named but is not one we know
    need_by: date | None = None
    date_text: str | None = None  # the words that gave need_by
    urgency: str | None = None  # "Emergency" when stated; None otherwise
    urgency_hint: bool = False  # "urgent", "asap": ask whether it is an emergency
    price: Decimal | None = None
    confirm: bool = False
    cancel: bool = False
    correction: bool = False
    policy_change: bool = False
    instruction: bool = False  # the message tries to instruct the assistant

    def empty(self):
        return not (self.items or self.quantity is not None or self.plant or self.plant_unknown or self.need_by
                    or self.urgency or self.urgency_hint or self.price is not None or self.confirm or self.cancel)


def plant_aliases(plants):
    """{'chk1': 'CHK1', 'chakan': 'CHK1', 'pune': 'PUN1', 'bhosari': 'PUN1'} from the plant master names."""
    aliases = {}
    for code, plant in plants.items():
        aliases[code.lower()] = code
        for word in re.findall(r"[a-z]+", (plant.name or "").lower()):
            if word not in ("plant", "the", "and", "unit"):
                aliases[word] = code
    return aliases


def _decimal(text):
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _future(month, day, today, year=None):
    """A date without a year is this year's, unless that is more than six months ago (then next year's). A
    recent past date stays in the past, so the conversation can refuse it with a reason."""
    try:
        if year:
            return date(year, month, day)
        candidate = date(today.year, month, day)
        return candidate if (today - candidate).days <= 183 else date(today.year + 1, month, day)
    except ValueError:
        return None


def read_date(text, today):
    """(date, the words that gave it) or (None, None). Understands ISO dates, 25/11/2026, 25 Nov, Nov 25,
    today, tomorrow, day after tomorrow, in N days or weeks, next/this <weekday>, <weekday>, next week."""
    t = text.lower()
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        return _future(int(m[2]), int(m[3]), today, int(m[1])), m[0]
    if m := re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", t):  # Indian order: day/month/year
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return _future(int(m[2]), int(m[1]), today, year), m[0]
    month_names = "|".join(MONTHS)
    if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[a-z]*\.?(?:,?\s+(\d{{4}}))?", t):
        return _future(MONTHS[m[2]], int(m[1]), today, int(m[3]) if m[3] else None), m[0]
    if m := re.search(rf"\b({month_names})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", t):
        return _future(MONTHS[m[1]], int(m[2]), today, int(m[3]) if m[3] else None), m[0]
    if m := re.search(r"\bday after tomorrow\b", t):
        return today + timedelta(days=2), m[0]
    if m := re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1), m[0]
    if m := re.search(r"\btoday\b", t):
        return today, m[0]
    if m := re.search(r"\bin\s+(\d+|a|one|two|three)\s+(day|days|week|weeks)\b", t):
        n = {"a": 1, "one": 1, "two": 2, "three": 3}.get(m[1]) or int(m[1])
        return today + timedelta(days=n * (7 if m[2].startswith("week") else 1)), m[0]
    if m := re.search(r"\bnext week\b", t):
        return today + timedelta(days=7 - today.weekday()), m[0]  # the Monday of next week
    if m := re.search(r"\b(?:(next|this|coming)\s+)?(" + "|".join(WEEKDAYS) + r")\b", t):
        target = WEEKDAYS.index(m[2])
        ahead = (target - today.weekday()) % 7 or 7  # the first such day after today (D40)
        return today + timedelta(days=ahead), m[0]
    return None, None


def _price(text):
    m = re.search(r"(?:rs\.?|inr|₹)\s*" + NUMBER, text, re.I) or \
        re.search(NUMBER + r"\s*(?:rs|rupees|inr)\b", text, re.I) or \
        re.search(NUMBER + r"\s*(?:each|per\s+\w+|/\s*\w+)\b", text, re.I)
    return _decimal(m[1]) if m else None


def _items(text):
    """Quantity + unit + item text segments: '200 nitrile gloves and 50 pairs of cotton gloves for Chakan'."""
    cleaned = re.sub(r"(?:rs\.?|inr|₹)\s*" + NUMBER + r"(?:\s*(?:each|per\s+\w+))?", " ", text, flags=re.I)
    cleaned = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b", " ", cleaned)
    out = []
    # A new item starts only after a comma, a semicolon or "and <number>": numbers inside the item text are its
    # size or model ("aluminium plate 6061 10mm", "air compressor 30HP"), not another item (break-it pass).
    pattern = re.compile(r"(?:^|[\s,;(])" + NUMBER + r"\s*(?:x\s+)?([a-z]+\b)?\s*(?:of\s+)?(.*?)(?=(?:,|;|\band\b\s+\d|$))",
                         re.I)
    for m in pattern.finditer(cleaned):
        quantity, unit_word, rest = _decimal(m[1]), (m[2] or "").lower(), m[3]
        unit = UNITS.get(unit_word)
        # not a unit: the word belongs to the item; keep the text exactly as typed ("v-belt", not "v -belt")
        text_part = rest if unit else (cleaned[m.start(2):m.end(3)] if m[2] else rest)
        item = _item_text(text_part)
        if item and not re.fullmatch(r"(?:days?|weeks?|hours?)\b.*", item, re.I):
            out.append({"text": item, "quantity": quantity, "unit": unit})
    return out


def _item_text(text):
    t = ITEM_END.sub("", " " + (text or "").strip()).strip(" .,!?:;-")
    previous = None
    while previous != t:
        previous, t = t, FILLER.sub("", t).strip(" .,!?:;-")
    t = re.sub(r"\b(and|or|for|by)$", "", t).strip(" .,")
    return t if re.search(r"[a-z]", t, re.I) else ""


def read(text, today, aliases, pending=None):
    """Everything the message says. `pending` is the question just asked, which tells a bare answer apart:
    "300" is a quantity, or a price when the price was asked."""
    text = (text or "").strip()
    low = text.lower()
    r = Reading()
    r.cancel = bool(CANCEL.search(low)) and len(low.split()) <= 6
    r.confirm = bool(CONFIRM.match(low))
    r.correction = bool(CORRECTION.search(low))
    r.policy_change = bool(POLICY.search(low))
    if r.cancel or r.confirm:
        return r
    if r.policy_change:
        return r  # a policy change is not a purchase request: nothing else is read from it
    for word, code in aliases.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            r.plant = code
            break
    else:
        if m := re.search(r"\b(?:for|at|to)\s+(?:the\s+)?([a-z][a-z0-9]+)\s+plant\b|\bplant\s+([a-z][a-z0-9]+)\b", low):
            r.plant_unknown = (m[1] or m[2]).upper()
        elif pending == "plant" and re.fullmatch(r"[a-z][a-z0-9 ]{1,30}", low):
            r.plant_unknown = text.strip().upper()
    r.need_by, r.date_text = read_date(text, today)
    if r.date_text:  # the date's own numbers are not quantities or prices
        text = re.sub(re.escape(r.date_text), " ", text, count=1, flags=re.I)
        low = text.lower()
    if INSTRUCTION.search(low):
        r.instruction = True
    if any(w in low for w in EMERGENCY_WORDS) and not re.search(r"\bnot\s+(an\s+)?emergency\b", low):
        r.urgency = "Emergency"
    elif re.search(r"\b(normal|not urgent|no rush|not an emergency)\b", low):
        r.urgency = "Normal"
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in URGENT_WORDS) and r.urgency is None:
        r.urgency_hint = True
    r.price = _price(text)
    bare = re.fullmatch(r"\s*(?:make it|change it to|it'?s|about|around|approx(?:imately)?)?\s*(?:rs\.?|₹)?\s*"
                        r"(-?\d+(?:[.,]\d+)?)\s*([a-z]+)?\s*(?:each|please)?[\s.!]*", low)
    if bare and (not bare[2] or bare[2] in UNITS):
        value = _decimal(bare[1])
        if pending == "price" or "rs" in low or "₹" in low:
            r.price = value
        else:
            r.quantity, r.unit = value, UNITS.get(bare[2] or "")
        return r
    if pending == "unit" and low.strip(" .") in UNITS:
        r.unit = UNITS[low.strip(" .")]
        return r
    if r.instruction:
        return r  # never read items out of an instruction
    r.items = _items(text)
    if not r.items:
        if m := re.search(r"\bmake it\s+(-?\d+(?:[.,]\d+)?)", low):
            r.quantity = _decimal(m[1])
        elif pending in (None, "item", "item_detail", "choose_item") or (
                r.correction and not (r.plant or r.plant_unknown or r.need_by or r.urgency or r.urgency_hint
                                      or r.price is not None or r.quantity is not None)):
            item = _item_text(re.sub(r"\b(for|at)\s+\w+\s*$", "", text))
            for word in aliases:
                item = re.sub(rf"\b{re.escape(word)}\b", "", item, flags=re.I).strip()
            if item and (not (r.plant or r.need_by or r.urgency or r.urgency_hint or r.price)
                         or pending in ("item", "item_detail", "choose_item")):
                r.items = [{"text": item, "quantity": None, "unit": None}]
    return r
