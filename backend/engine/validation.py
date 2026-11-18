"""E1: check every PR line before clubbing (policy line_checks and line_flags, evaluated as data).

For each line: pick the policy version in force on its creation date and resolve its item; then, knowing
every line, build its line-check facts (including duplicates and possible duplicates across the batch) and
run the version's line_checks (any hit -> NOT_PROCESSED with reasons) and line_flags (notes that travel with
the line to the reason text but never stop it). A message may name a fact in braces, e.g.
"{line.possible_duplicate_of}", which is filled in from the line's facts.
"""
import dataclasses
import re
from dataclasses import dataclass
from datetime import timedelta

from engine.inputs import PRLine
from engine.lines import canon_code, canon_uom, canon_urgency, line_number_key
from engine.logic import evaluate, get_path
from engine.matching import Match, resolve_item
from engine.versions import latest_version, version_in_force

PLACEHOLDER = re.compile(r"\{([a-z_]+(?:\.[a-z_]+)+)\}")


@dataclass(frozen=True)
class Finding:
    id: str  # the policy's check or flag id (V3, F2, ...), or NO-POLICY
    text: str
    missing: tuple[str, ...] = ()  # fields that had no value while it was evaluated


@dataclass(frozen=True)
class CheckedLine:
    index: int  # position in the batch, file order
    line: PRLine
    version: object  # PolicyVersion used for this line, or None
    plant: str | None  # canonical
    urgency: str | None  # canonical (blank or unknown -> the policy's default)
    match: Match | None
    not_processed: tuple[Finding, ...]
    flags: tuple[Finding, ...]
    facts: dict = dataclasses.field(default=None, compare=False, repr=False)  # line-check stage facts

    @property
    def processed(self):
        return not self.not_processed

    @property
    def item_code(self):
        return self.match.item_code if self.match else None

    @property
    def is_new(self):
        return self.processed and self.item_code is None


def _fired(entries, facts, text_key):
    found = []
    for entry in entries:
        missing = []
        if evaluate(entry["when"], facts, missing):
            text = PLACEHOLDER.sub(lambda m: str(get_path(facts, m.group(1), "")), entry[text_key])
            found.append(Finding(entry["id"], text, tuple(dict.fromkeys(missing))))
    return tuple(found)


def _ref(line):
    return f"{line.pr_no}/{line.pr_line}"


def _possible_duplicates(i, resolved, window, same_item=None):
    """Other lines with the same requester, item, plant, quantity and need-by, created within the window.
    `same_item` (item code -> line indexes) limits the search to lines of the same item."""
    line, match = resolved[i][0], resolved[i][2]
    if not (line.requester and line.created_at and match and match.item_code and line.quantity is not None
            and line.need_by_date):
        return []
    span = timedelta(minutes=window["length"]) if window["unit"] == "minutes" else timedelta(hours=window["length"])
    found = []
    for j in same_item.get(match.item_code, ()) if same_item is not None else range(len(resolved)):
        other, _version, other_match = resolved[j]
        if j == i or not (other.created_at and other_match) or other_match.item_code != match.item_code:
            continue
        gap = abs(other.created_at - line.created_at)
        if (other.requester or "").strip().casefold() == line.requester.strip().casefold() \
                and canon_code(other.plant) == canon_code(line.plant) and other.quantity == line.quantity \
                and other.need_by_date == line.need_by_date and (gap <= span if window["inclusive"] else gap < span):
            found.append(_ref(other))
    return found


def line_facts(line, master, params, match, is_duplicate, possible_duplicates=()):
    """The line-check stage facts for one line (engine/facts.py LINE_CHECK_SCOPE)."""
    item = master.items.get(match.item_code) if match.item_code else None
    plant = master.plants.get(canon_code(line.plant))
    intake = params["intake"]
    urgency, recognised = canon_urgency(line.urgency, intake)
    words = set(re.findall(r"[a-z]+", line.description.lower()))
    uom = canon_uom(line.uom)
    return {
        "line": {**dataclasses.asdict(line), "plant": canon_code(line.plant), "item_code": canon_code(line.item_code),
                 "uom": uom, "urgency": urgency, "is_duplicate": is_duplicate,
                 "uom_mismatch": bool(item and uom and uom != canon_uom(item.uom)),
                 "urgency_recognised": recognised,
                 "description_says_urgent": bool(words & {w.lower() for w in intake["urgency_words"]}),
                 "possible_duplicate": bool(possible_duplicates),
                 "possible_duplicate_of": ", ".join(possible_duplicates) or None},
        "item": dataclasses.asdict(item) if item else None,
        "plant": dataclasses.asdict(plant) if plant else None,
        "match": {"status": match.status, "score": match.score, "item_code_unknown": match.item_code_unknown,
                  "description_disagrees": match.description_disagrees},
        "params": params,
    }


def check_lines(lines, master):
    """CheckedLine for every PR line, in file order. Nothing is dropped."""
    resolved = []  # (line, version, match) in file order
    for line in lines:
        version = (version_in_force(master.policies, line.created_at.date()) if line.created_at
                   else latest_version(master.policies))
        match = resolve_item(line, master.items, version.document["parameters"].get("matching", {})) if version else None
        resolved.append((line, version, match))
    same_item = {}  # item code -> indexes, in file order (so duplicates are reported in the same order)
    for index, (_line, _version, match) in enumerate(resolved):
        if match and match.item_code:
            same_item.setdefault(match.item_code, []).append(index)
    seen, out = set(), []
    for index, (line, version, match) in enumerate(resolved):
        key = (line.pr_no.strip().upper(), line_number_key(line.pr_line))
        is_duplicate = key in seen
        seen.add(key)
        if version is None:
            out.append(CheckedLine(index, line, None, canon_code(line.plant), None, None,
                                   (Finding("NO-POLICY", f"No approved policy version is in force on "
                                                         f"{line.created_at.date()}"),), (), None))
            continue
        params = version.document["parameters"]
        window = params["intake"].get("possible_duplicate_window")
        maybe = _possible_duplicates(index, resolved, window, same_item) if window else []
        facts = line_facts(line, master, params, match, is_duplicate, maybe)
        out.append(CheckedLine(index, line, version, facts["line"]["plant"], facts["line"]["urgency"], match,
                               _fired(version.document.get("line_checks", []), facts, "reason"),
                               _fired(version.document.get("line_flags", []), facts, "message"), facts))
    return tuple(out)
