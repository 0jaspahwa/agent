"""B2: the chat intake conversation, a small state machine in code. Pure: (state, event, reading) -> (state,
reply). The LLM never writes a reply and never chooses an item: every sentence here is a template, and every item
code shown comes from the deterministic matcher (engine/matching.py) or the item master.

Order of questions, one at a time: for each line its item, then its quantity (a new item also needs an estimated
unit price, policy 1.2, and a unit); then the plant, the need-by date, and urgency (asked only if the message hints
at it; Normal otherwise, and always shown on the card). Then a confirmation card; Create is the one action.

Events: {"type": "message"} (with a Reading), "choose" (an item from the offered candidates), "new_item",
"describe_again", "urgency" (Emergency or Normal), "create", "cancel". The reply's "do" tells the service to create
the PR, cancel, or start a policy draft; this module has no side effects.
"""
import copy
from datetime import date
from decimal import Decimal

from engine import matching
from engine.lines import canon_code, canon_uom

NEW_STATE = {"lines": [], "current": 0, "plant": None, "need_by": None, "date_words": None, "urgency": "Normal",
             "urgency_hint": False, "urgency_asked": False, "pending": None, "told_ai_down": False}
PROCUREMENT = "Procurement"


def new_state():
    return copy.deepcopy(NEW_STATE)


def _line(text, quantity=None, unit=None):
    return {"text": text, "quantity": None if quantity is None else str(quantity), "user_unit": unit, "item_code": None,
            "description": None, "unit": None, "new_item": False, "price": None, "candidates": [], "detail_asked": False}


def say_date(d):
    return d.strftime("%a %d %b %Y").replace(" 0", " ")


def _qty(text):
    return format(Decimal(text).normalize(), "f")


class Context:
    """What the conversation needs from outside: the item master, matching settings, plants, today, the role."""

    def __init__(self, items, settings, plants, aliases, today, role):
        self.items, self.settings, self.plants, self.aliases, self.today, self.role = \
            items, settings, plants, aliases, today, role

    def plant_choices(self):
        return [{"label": f"{p.name} ({code})", "type": "message", "text": code} for code, p in sorted(self.plants.items())]


# ---------------------------------------------------------------- item resolution
def _relevant(text, code, ctx):
    """A closest item is worth offering only if it shares a word with what was asked for."""
    asked = matching.tokens(text, ctx.settings)[1]
    item = matching.tokens(ctx.items[code].description, ctx.settings)[1]
    return any(matching._word_score(a, b, ctx.settings) for a in asked for b in item)


def resolve(line, ctx):
    """Match the line's text. Returns what to ask next for the item ('choose_item', 'item_detail',
    'new_item_offer') or None once the item is known."""
    if line["item_code"] or line["new_item"]:
        return None
    text = line["text"]
    code = canon_code(text)
    if code and code in ctx.items:
        found = matching.Match(code, "code")
    else:
        found = matching.match_description(text, ctx.items, ctx.settings)
    if found.item_code:
        _set_item(line, found.item_code, ctx)
        return None
    candidates = [c.item_code for c in found.candidates if found.status == "ambiguous" or _relevant(text, c.item_code, ctx)]
    line["candidates"] = candidates[:4]
    if line["candidates"]:
        return "choose_item"
    return "new_item_offer" if line["detail_asked"] else "item_detail"


def _set_item(line, code, ctx):
    item = ctx.items[code]
    line.update(item_code=code, description=item.description, unit=item.uom, candidates=[], new_item=False)


# ---------------------------------------------------------------- applying what the user said
def _apply(state, r, ctx, problems):
    lines, pending = state["lines"], state["pending"]
    current = lines[state["current"]] if lines else None

    def valid_quantity(q):
        if q is None:
            return None
        if q <= 0:
            problems.append(f"The quantity must be more than zero ({_qty(str(q))} is not).")
            return None
        return q

    if r.items:
        if current and (pending in ("item", "item_detail", "choose_item", "new_item_offer")
                        or (r.correction and len(r.items) == 1)):
            item = r.items[0]
            keep_qty = current["quantity"]
            current.update(_line(item["text"], valid_quantity(item["quantity"]) or keep_qty, item["unit"]),
                           detail_asked=current["detail_asked"] or pending == "item_detail")
            if current["quantity"] is not None and not isinstance(current["quantity"], str):
                current["quantity"] = str(current["quantity"])
            extra = r.items[1:]
        else:
            extra = r.items
        for item in extra:
            lines.append(_line(item["text"], valid_quantity(item["quantity"]), item["unit"]))
    target = current or (lines[state["current"]] if lines else None)
    if r.quantity is not None:
        q = valid_quantity(r.quantity)
        if q is not None and target is not None:
            target["quantity"] = str(q)
            if r.unit:
                target["user_unit"] = r.unit
        elif q is not None:
            problems.append("Tell me what the item is first.")
    if r.unit and pending == "unit" and target is not None and target["new_item"]:
        target["unit"] = r.unit
    if r.price is not None:
        new_lines = [ln for ln in lines if ln["new_item"]]
        owner = target if target is not None and target["new_item"] else (new_lines[-1] if new_lines else None)
        if r.price <= 0:
            problems.append("The estimated price must be more than zero.")
        elif owner is not None:
            owner["price"] = str(r.price)
    if r.plant:
        state["plant"] = r.plant
    elif r.plant_unknown:
        problems.append(f"I don't know a plant called {r.plant_unknown}. Corvo has "
                        + " and ".join(f"{p.name} ({c})" for c, p in sorted(ctx.plants.items())) + ".")
        state["plant"] = None
        state["ask_plant_again"] = True
    if r.need_by:
        if r.need_by < ctx.today:
            problems.append(f"{say_date(r.need_by)} is in the past, so it cannot be the need-by date.")
        else:
            state["need_by"], state["date_words"] = r.need_by.isoformat(), r.date_text
    if r.urgency:
        state["urgency"], state["urgency_asked"] = r.urgency, True
    if r.urgency_hint:
        state["urgency_hint"] = True


# ---------------------------------------------------------------- what to say next
def _choices_for_item(line, ctx):
    out = [{"label": f"{c} {ctx.items[c].description} ({ctx.items[c].uom})", "type": "choose", "item_code": c}
           for c in line["candidates"]]
    out.append({"label": "None of these", "type": "describe_again"})
    return out


def card(state, ctx):
    plant = ctx.plants.get(state["plant"])
    return {"lines": [{"line": i + 1, "item_code": ln["item_code"] or "NEW", "description": ln["description"] or ln["text"],
                       "quantity": ln["quantity"], "unit": ln["unit"], "new_item": ln["new_item"],
                       "estimated_unit_price": ln["price"]} for i, ln in enumerate(state["lines"])],
            "plant": state["plant"], "plant_name": plant.name if plant else None, "need_by": state["need_by"],
            "urgency": state["urgency"]}


def missing(state):
    """What the draft PR still lacks, for the panel beside the chat."""
    out = []
    if not state["lines"]:
        out.append("item")
    for i, ln in enumerate(state["lines"], start=1):
        tag = f" (line {i})" if len(state["lines"]) > 1 else ""
        if not (ln["item_code"] or ln["new_item"]):
            out.append("item" + tag)
        if ln["quantity"] is None:
            out.append("quantity" + tag)
        if ln["new_item"] and ln["price"] is None:
            out.append("estimated unit price" + tag)
        if ln["new_item"] and not ln["unit"]:
            out.append("unit" + tag)
    if not state["plant"]:
        out.append("plant")
    if not state["need_by"]:
        out.append("need-by date")
    return out


def next_question(state, ctx, found):
    """(text, choices) for the first thing missing, and set state['pending']."""
    for i, ln in enumerate(state["lines"]):
        state["current"] = i
        label = ln["description"] or ln["text"]
        need = resolve(ln, ctx)
        if need == "choose_item":
            state["pending"] = "choose_item"
            return f"Which item do you mean by \"{ln['text']}\"?", _choices_for_item(ln, ctx)
        if need == "item_detail":
            ln["detail_asked"] = True
            state["pending"] = "item_detail"
            return (f"I could not find \"{ln['text']}\" in the item master. Can you describe it more precisely, "
                    f"with its size, grade or model?", [])
        if need == "new_item_offer":
            state["pending"] = "new_item_offer"
            return (f"I still could not find \"{ln['text']}\". I can raise it as a new item, which goes to sourcing "
                    f"(policy 1.2), or you can describe it differently.",
                    [{"label": "Raise as a new item", "type": "new_item"}, {"label": "Describe it differently", "type": "describe_again"}])
        if ln["item_code"] and i not in found:
            found.add(i)
        if ln["quantity"] is None:
            state["pending"] = "quantity"
            unit = f" (in {ln['unit']})" if ln["unit"] else ""
            return f"How many {label}{unit} do you need?", []
        if ln["new_item"] and ln["price"] is None:
            state["pending"] = "price"
            return (f"A new item is valued from your estimate (policy 1.2). What is the estimated price per unit of "
                    f"\"{label}\", in rupees?", [])
        if ln["new_item"] and not ln["unit"]:
            state["pending"] = "unit"
            return f"What unit is \"{label}\" bought in (for example NOS, KG, PAIR, MTR)?", []
    state["current"] = max(len(state["lines"]) - 1, 0)
    if not state["lines"]:
        state["pending"] = "item"
        return "What do you need? For example: 200 nitrile gloves for Chakan by next Friday.", []
    if not state["plant"]:
        state["pending"] = "plant"
        again = state.pop("ask_plant_again", False)
        return ("Which plant is it for?" if not again else "Which of the two plants is it for?"), ctx.plant_choices()
    if not state["need_by"]:
        state["pending"] = "need_by"
        return "By what date do you need it?", []
    if state["urgency_hint"] and not state["urgency_asked"]:
        state["pending"] = "urgency"
        return ("You said it is urgent. Is it an emergency (for example a breakdown), which can be bought at once "
                "under policy 5.3? Otherwise it stays Normal."), [{"label": "Emergency", "type": "urgency", "value": "Emergency"},
                                                                {"label": "Normal", "type": "urgency", "value": "Normal"}]
    state["pending"] = "confirm"
    return "Here is your request. Check it and press Create, or tell me what to change.", []


def _found_note(state, ctx, before):
    notes = []
    for i, ln in enumerate(state["lines"]):
        if ln["item_code"] and before.get(i) != ln["item_code"]:
            notes.append(f"Found {ln['item_code']} {ln['description']} (bought in {ln['unit']}).")
            if ln["user_unit"] and canon_uom(ln["user_unit"]) != canon_uom(ln["unit"]):
                notes.append(f"It is bought in {ln['unit']}, so I have recorded {_qty(ln['quantity'])} {ln['unit']}; "
                             f"correct the quantity if that is not right.")
        if ln["new_item"] and before.get(i) != "NEW":
            notes.append(f"\"{ln['text']}\" will be raised as a new item.")
    return notes


def _change_notes(state, was, ctx):
    """Say what a correction changed, so the requester sees it took effect."""
    notes = []
    for i, (old, ln) in enumerate(zip(was["quantities"], state["lines"])):
        if old is not None and ln["quantity"] != old:
            tag = f" on line {i + 1}" if len(state["lines"]) > 1 else ""
            notes.append(f"Quantity{tag} changed to {_qty(ln['quantity'])} {ln['unit'] or ''}.".replace(" .", "."))
    if was["plant"] and state["plant"] != was["plant"] and state["plant"]:
        p = ctx.plants[state["plant"]]
        notes.append(f"Plant changed to {p.name} ({state['plant']}).")
    if was["urgency"] != state["urgency"] and was["plant"] is not None:
        notes.append(f"Urgency set to {state['urgency']}.")
    return notes


def handle(state, event, reading, ctx):
    """One turn. Returns (state, reply) with reply = {text, choices, card, missing, do}."""
    state = copy.deepcopy(state)
    before = {i: ("NEW" if ln["new_item"] else ln["item_code"]) for i, ln in enumerate(state["lines"])}
    was = {"plant": state["plant"], "need_by": state["need_by"], "urgency": state["urgency"],
           "quantities": [ln["quantity"] for ln in state["lines"]]}
    notes, problems, do = [], [], None
    kind = event.get("type")
    if kind == "cancel" or (kind == "message" and reading.cancel):
        return state, {"text": "Discarded. Nothing was created.", "choices": [], "card": None, "missing": [],
                       "do": "cancel"}
    if kind == "message":
        if reading.policy_change and not state["lines"] and not reading.items:
            if ctx.role == PROCUREMENT:
                return state, {"text": "I will draft that as a policy amendment for review. Nothing changes until "
                                       "it is reviewed and approved.", "choices": [], "card": None, "missing": [],
                               "do": "policy"}
            notes.append("Only the Procurement role can propose a policy change. I can help you raise a purchase request.")
        elif reading.instruction:
            notes.append("I can't act on instructions in a message. I only take down purchase requests; a buyer "
                         "reviews and approves them.")
        elif reading.confirm and state["pending"] == "confirm":
            kind = "create"
        else:
            _apply(state, reading, ctx, problems)
            if reading.empty() and not problems:
                notes.append("Sorry, I did not understand that.")
    elif kind == "choose":
        ln = state["lines"][state["current"]] if state["lines"] else None
        if ln is None or event.get("item_code") not in ln["candidates"]:
            problems.append("Please choose one of the items listed.")  # never accept a code we did not offer
        else:
            _set_item(ln, event["item_code"], ctx)
    elif kind == "new_item":
        ln = state["lines"][state["current"]] if state["lines"] else None
        if ln is None or state["pending"] not in ("new_item_offer", "choose_item", "item_detail"):
            problems.append("There is no item waiting to be raised as new.")
        else:
            ln.update(new_item=True, item_code=None, candidates=[], description=None, unit=canon_uom(ln["user_unit"]) or None)
    elif kind == "describe_again":
        ln = state["lines"][state["current"]] if state["lines"] else None
        if ln is not None:
            ln.update(candidates=[], detail_asked=True, item_code=None)
            ln["describing"] = True
            state["pending"] = "item_detail"
            return state, {"text": f"Describe \"{ln['text']}\" again, with its size, grade or model.", "choices": [],
                           "card": None, "missing": missing(state), "do": None}
    elif kind == "urgency":
        if event.get("value") in ("Emergency", "Normal"):
            state["urgency"], state["urgency_asked"] = event["value"], True
    if kind == "create":
        if missing(state):
            problems.append("The request is not complete yet.")
        else:
            return state, {"text": "Creating your request...", "choices": [], "card": card(state, ctx), "missing": [],
                           "do": "create"}
    found = set()
    question, choices = next_question(state, ctx, found)
    notes += _change_notes(state, was, ctx) + _found_note(state, ctx, before)
    if state["need_by"] and state.get("date_words") and state["date_words"] != state.get("date_said"):
        notes.append(f"Need-by date: {say_date(date.fromisoformat(state['need_by']))} "
                     f"(from \"{state['date_words']}\").")
        state["date_said"] = state["date_words"]
    text = " ".join(problems + notes + [question])
    return state, {"text": text, "choices": choices, "missing": missing(state), "do": do,
                   "card": card(state, ctx) if state["pending"] == "confirm" else None}
