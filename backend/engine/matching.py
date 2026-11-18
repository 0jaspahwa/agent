"""Resolve a PR line to an item master item (policy 1.1). Deterministic; no LLM. Settings: matching.*.

1. A valid item code wins (if the description clearly names another item, that is noted: flag F4).
2. Otherwise the description is matched against every item:
   - normalise: lower case, inch marks, the "x" between dimensions, noise phrases removed, split into tokens
     at punctuation and at letter/digit boundaries ("M10x40" -> m 10 40), abbreviations expanded;
   - specification gate: every number in the description must also be in the item (6205 vs 6308, M10 vs
     M16, i5 vs i7, 2mm vs 3mm); numbers are never fuzzy;
   - word gate: at least min_word_coverage of the description's words must be found in the item ("cutting
     wheel 4 inch" is not "Grinding wheel 4 inch"); a word may match with a typo (similarity >=
     word_similarity, words of at least fuzzy_min_word_length letters);
   - score: shared tokens, Dice style, 2 x shared / (description tokens + item tokens), where a number
     counts number_weight times (part numbers and sizes identify an item more than words do);
   - the best item must reach match_threshold; if the top scores tie within ambiguity_margin (and reach
     ambiguity_floor) the line is ambiguous; both cases make a new item, with the candidates named (D21).
"""
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from difflib import SequenceMatcher
from functools import lru_cache

from engine.lines import canon_code

DIMENSION_X = re.compile(r"(\d)\s*[x*]\s*(?=\d)")  # "1250x2500", "50 x 100": the x only separates numbers
SEPARATORS = re.compile(r"[\s,;:()\[\]{}\"'\-_+*&#]+")
PARTS = re.compile(r"\d+(?:[./]\d+)*|[a-z]+")  # numbers (with . or / inside) and runs of letters


@dataclass(frozen=True)
class Candidate:
    item_code: str
    score: Decimal


@dataclass(frozen=True)
class Match:
    item_code: str | None  # None: a new item (policy 1.2)
    status: str  # code | description | new | ambiguous
    score: Decimal | None = None  # description score 0..1, None when the code decided
    runner_up: Candidate | None = None
    candidates: tuple[Candidate, ...] = ()  # ambiguous: the items that tied; new: the closest (up to 3)
    explanation: str = ""
    item_code_unknown: bool = False  # a code was given but is not in the item master
    description_disagrees: bool = False  # a valid code was given but the description names another item


def _number(text):
    return text if "/" in text else format(Decimal(text).normalize(), "f")  # "08" -> "8", "3.150" -> "3.15"


_SETTINGS_KEYS = {}  # id(settings) -> (settings, key): the object is kept, so its id cannot be reused
_TOKENS = {}


def _settings_key(settings):
    held = _SETTINGS_KEYS.get(id(settings))
    if held is None or held[0] is not settings:
        key = json.dumps([settings["symbols"], settings["noise_phrases"], settings["abbreviations"]], sort_keys=True)
        held = _SETTINGS_KEYS[id(settings)] = (settings, key)
    return held[1]


def tokens(text, settings):
    """(numbers, words) of a description after normalisation. Cached by text and normalisation settings (the
    result depends on nothing else), so the 73 item descriptions are not re-read for every line."""
    key = (text, _settings_key(settings))
    if key not in _TOKENS:
        if len(_TOKENS) > 100_000:  # a long-running server reading many different texts: start again
            _TOKENS.clear()
        _TOKENS[key] = _tokens(text, settings)
    numbers, words = _TOKENS[key]
    return list(numbers), list(words)


def _tokens(text, settings):
    s = f" {text.lower()} "
    for symbol, word in settings["symbols"].items():
        s = re.sub(r"(\d)\s*" + re.escape(symbol), lambda m: f"{m.group(1)} {word} ", s)
    s = DIMENSION_X.sub(lambda m: m.group(1) + " ", s)
    for phrase in sorted(settings["noise_phrases"], key=len, reverse=True):
        s = re.sub(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", " ", s)
    numbers, words = [], []
    for raw in SEPARATORS.split(s):
        for part in PARTS.findall(raw):
            if part[0].isdigit():
                numbers.append(_number(part))
            else:
                words.extend(settings["abbreviations"].get(part, part).split())
    return numbers, words


def _word_score(word, other, settings):
    if word == other:
        return 1.0
    return _fuzzy(word, other, settings["fuzzy_min_word_length"], settings["word_similarity"])


@lru_cache(maxsize=200_000)
def _fuzzy(word, other, min_length, similarity):
    if len(word) >= min_length and len(other) >= min_length:
        ratio = SequenceMatcher(None, word, other).ratio()
        if ratio >= similarity:
            return ratio
    return 0.0


def score(desc_tokens, item_tokens, settings, word_gate=True):
    """Dice score, or None when a gate fails (word_gate=False skips the word gate, for showing the closest
    other items). Also returns the typo pairs used."""
    d_num, d_words = desc_tokens
    i_num, i_words = item_tokens
    if not set(d_num) <= set(i_num) or not (d_num or d_words):
        return None, ()
    weight = settings["number_weight"]
    shared = float(weight * len(d_num))  # every description number is in the item (the gate)
    free = list(i_words)
    typos, found = [], 0
    for word in d_words:
        best = max(((_word_score(word, other, settings), -k, k) for k, other in enumerate(free)), default=(0, 0, None))
        if best[0] > 0:
            shared += best[0]
            found += 1
            if best[0] < 1:
                typos.append((word, free[best[2]]))
            free.pop(best[2])
    if word_gate and d_words and found / len(d_words) < settings["min_word_coverage"]:
        return None, ()
    total = weight * (len(d_num) + len(i_num)) + len(d_words) + len(i_words)
    return 2 * shared / total, tuple(typos)


def _dec(x):
    return Decimal(f"{x:.3f}")


def _names(candidates, items):
    return ", ".join(f"{c.item_code} {items[c.item_code].description!r} ({c.score})" for c in candidates)


def purpose_variants(description, settings):
    """Shorter versions of a description without its purpose clause, shortest removal first:
    bracketed text removed, then a cut at each marker ("for", "as per", "against", or a spaced "-" / "/"
    followed by a word), from the last marker to the first. Yields (text, removed clause)."""
    clause = settings.get("purpose_clause") or {}
    text = description.strip()
    seen = {text.lower()}
    if clause.get("brackets"):
        unbracketed = re.sub(r"\s*[(\[][^)\]]*[)\]]", " ", text).strip()
        if unbracketed.lower() not in seen:
            seen.add(unbracketed.lower())
            yield unbracketed, text[len(unbracketed):].strip() or text
        text = unbracketed
    words = "|".join(re.escape(w) for w in clause.get("words", []))
    seps = "|".join(re.escape(s) for s in clause.get("separators", []))
    patterns = [p for p in (words and rf"\s(?:{words})\s+(?=[a-z0-9])", seps and rf"\s(?:{seps})\s*(?=[a-z])") if p]
    cuts = sorted({m.start() for p in patterns for m in re.finditer(p, text, flags=re.IGNORECASE)}, reverse=True)
    for cut in cuts:
        kept = text[:cut].strip()
        if kept and kept.lower() not in seen:
            seen.add(kept.lower())
            yield kept, text[cut:].strip()


def match_description(description, items, settings):
    """Match the full description first; only if that gives no match, try it without a purpose clause."""
    full = _match_text(description, items, settings)
    if full.status == "description":
        return full
    for text, removed in purpose_variants(description, settings):
        shorter = _match_text(text, items, settings)
        if shorter.status == "description":
            return replace(shorter, explanation=f"{shorter.explanation}; ignored the purpose clause {removed!r}")
    return full


def _match_text(description, items, settings):
    desc = tokens(description, settings)
    scored, nearby = [], []  # scored: passed both gates (can be chosen); nearby: numbers agree (shown only)
    for code in sorted(items):
        item = tokens(items[code].description, settings)
        s, typos = score(desc, item, settings)
        if s:
            scored.append((s, code, typos))
        near, _ = score(desc, item, settings, word_gate=False)
        if near:
            nearby.append((near, code))
    scored.sort(key=lambda t: (-t[0], t[1]))
    nearby.sort(key=lambda t: (-t[0], t[1]))
    if not scored:
        closest = tuple(Candidate(c, _dec(s)) for s, c in nearby[:3])
        return Match(None, "new", None, closest[0] if closest else None, closest,
                     "no item has every number in the description and most of its words"
                     + (f"; closest: {_names(closest, items)}" if closest else ""))
    best_score, best_code, typos = scored[0]
    others = [(s, c) for s, c in nearby if c != best_code]
    runner = Candidate(others[0][1], _dec(others[0][0])) if others else None
    tied = tuple(Candidate(c, _dec(s)) for s, c, _ in scored if best_score - s <= settings["ambiguity_margin"])
    if len(tied) > 1 and best_score >= settings["ambiguity_floor"]:
        return Match(None, "ambiguous", _dec(best_score), runner, tied,
                     f"{len(tied)} items match equally well: {_names(tied, items)}; treated as a new item "
                     f"for the buyer to resolve")
    if best_score < settings["match_threshold"]:
        closest = tuple(Candidate(c, _dec(s)) for s, c in nearby[:3])
        return Match(None, "new", _dec(best_score), runner, closest,
                     f"no item reaches the match threshold {settings['match_threshold']}; closest: "
                     f"{_names(closest, items)}")
    note = f"; typos tolerated: {', '.join(f'{a}~{b}' for a, b in typos)}" if typos else ""
    nums = f"; numbers {' '.join(desc[0])} agree" if desc[0] else ""
    return Match(best_code, "description", _dec(best_score), runner,
                 explanation=f"description matched {best_code} {items[best_code].description!r} "
                             f"(score {_dec(best_score)}){nums}{note}")


def resolve_item(line, items, settings):
    code = canon_code(line.item_code)
    if code and code in items:
        found = match_description(line.description, items, settings)
        own, _ = score(tokens(line.description, settings), tokens(items[code].description, settings), settings)
        disagrees = (found.status == "description" and found.item_code != code
                     and (own is None or own < settings["match_threshold"]))
        note = f"; the description reads as {found.item_code} instead" if disagrees else ""
        return Match(code, "code", explanation=f"item code {code} given{note}", description_disagrees=disagrees)
    return replace(match_description(line.description, items, settings), item_code_unknown=bool(code))
