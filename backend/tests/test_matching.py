"""E2: deterministic item matching (engine/matching.py), settings from v5.0.json matching.*."""
import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.inputs import PRLine
from engine.matching import match_description, resolve_item, tokens
from engine.validation import check_lines
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
SETTINGS = MASTER.policies[0].document["parameters"]["matching"]
SAMPLE = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")

# The 39 free-text lines of the sample batch and the item each must resolve to (None = new item).
# Same result as the spike's check (docs/engine_test_list.md); worked examples 3, 6, 7, 9, 12, 13 among them.
FREE_TEXT = {
    "PR-26-00002": "ITM-1024", "PR-26-00004": "ITM-1022", "PR-26-00008": "ITM-1016", "PR-26-00018": "ITM-1013",
    "PR-26-00020": "ITM-1015", "PR-26-00023": "ITM-1048", "PR-26-00030": "ITM-1023", "PR-26-00036": "ITM-1039",
    "PR-26-00039": "ITM-1057", "PR-26-00042": "ITM-1036", "PR-26-00047": "ITM-1071", "PR-26-00052": "ITM-1025",
    "PR-26-00058": "ITM-1020", "PR-26-00060": "ITM-1050", "PR-26-00063": "ITM-1043", "PR-26-00066": "ITM-1008",
    "PR-26-00075": "ITM-1030", "PR-26-00083": "ITM-1050", "PR-26-00088": "ITM-1035", "PR-26-00089": "ITM-1066",
    "PR-26-00097": "ITM-1066", "PR-26-00098": "ITM-1008", "PR-26-00103": "ITM-1044", "PR-26-00109": "ITM-1044",
    "PR-26-00114": "ITM-1034", "PR-26-00117": "ITM-1030", "PR-26-00119": "ITM-1028", "PR-26-00124": "ITM-1004",
    "PR-26-00139": "ITM-1051", "PR-26-00141": "ITM-1040", "PR-26-00142": "ITM-1040", "PR-26-00150": "ITM-1058",
    "PR-26-00161": "ITM-1010", "PR-26-00163": "ITM-1013", "PR-26-00165": "ITM-1055", "PR-26-00167": "ITM-1073",
    "PR-26-00169": "ITM-1063", "PR-26-00170": None, "PR-26-00171": None,
}


def match(text):
    return match_description(text, MASTER.items, SETTINGS)


def test_all_39_free_text_lines_resolve_as_expected():
    free = [l for l in SAMPLE if not l.item_code]
    assert len(free) == 39
    got = {l.pr_no: match(l.description).item_code for l in free}
    assert got == FREE_TEXT
    assert sum(v is not None for v in got.values()) == 37


@pytest.mark.parametrize("line", [l for l in SAMPLE if l.item_code], ids=lambda l: f"{l.pr_no}/{l.pr_line}")
def test_every_coded_line_matches_its_own_code_when_the_code_is_hidden(line):
    assert match(line.description).item_code == line.item_code


def test_every_item_description_matches_itself():
    assert all(match(item.description).item_code == code for code, item in MASTER.items.items())


@pytest.mark.parametrize("text", [
    "ball bearing 6206",           # part number differs (6205, 6308 exist)
    "hex bolt M12x40",             # size differs (M10x40, M16x60 exist)
    "laptop i7 16GB",              # grade differs (i5 exists)
    "MS sheet 5mm 1250x2500",      # thickness differs (2mm, 3mm exist)
    "monitor 27\"",                # 24 inch exists
    "cutting wheel 4 inch",        # Cutting wheel is 14 inch; the 4 inch wheel is a Grinding wheel
    "grinding wheel 14 inch",
    "drinking water purifier 50 LPH",
    "urgent",                      # nothing left after the noise is removed
])
def test_hard_negatives_do_not_match(text):
    assert match(text).item_code is None


@pytest.mark.parametrize("text, code", [
    ("safty shoes", "ITM-1046"),             # typo in a word is tolerated
    ("saftey shoes steel toe", "ITM-1046"),
    ("nitrile glove", "ITM-1048"),
    ("brg 6205", "ITM-1021"),                # abbreviation + a part number that identifies one item
    ("brg 6205 2rs", "ITM-1021"),
    ("pneu cylinder 50 x 100", "ITM-1036"),  # spacing around the x does not matter
    ("Hex Bolt M10x40 gr 8.8 (repeat)", "ITM-1009"),
    ("24 inch monitor", "ITM-1057"),
])
def test_tolerated_variations_match(text, code):
    assert match(text).item_code == code


@pytest.mark.parametrize("text, candidates", [
    ("gloves", {"ITM-1047", "ITM-1048"}),
    ("hex bolt", {"ITM-1009", "ITM-1014"}),
    ("MS sheet 1250x2500", {"ITM-1001", "ITM-1002"}),
])
def test_equally_good_items_are_ambiguous_and_named(text, candidates):
    m = match(text)
    assert (m.item_code, m.status) == (None, "ambiguous")
    assert {c.item_code for c in m.candidates} == candidates
    assert all(c in m.explanation for c in candidates)


def test_below_threshold_is_new_with_the_closest_candidates_named():
    m = match("oil")
    assert (m.item_code, m.status) == (None, "new")
    assert m.candidates and m.candidates[0].item_code in m.explanation


def test_numbers_are_never_fuzzy_but_are_normalised():
    assert tokens("Hex bolt M10x40 GR 8.8", SETTINGS)[0] == ["10", "40", "8.8"]
    assert tokens("chain sprocket 08b 20t", SETTINGS)[0] == ["8", "20"]
    assert tokens('monitor 24"', SETTINGS) == (["24"], ["monitor", "inch"])
    assert tokens("brg 6308 ZZ for maintenance", SETTINGS) == (["6308"], ["bearing", "zz"])


def test_result_has_score_runner_up_and_explanation():
    m = match("nitrile coated gloves - urgent")
    assert (m.item_code, m.status, m.score) == ("ITM-1048", "description", Decimal("1.000"))
    assert m.runner_up.item_code == "ITM-1047" and m.runner_up.score < m.score
    assert "ITM-1048" in m.explanation and "Nitrile coated gloves" in m.explanation


def pr(item_code, description):
    return PRLine("PR-T", "1", datetime(2026, 11, 4, 10, 0), None, None, "PUN1", item_code, description,
                  Decimal("5"), "NOS", None, date(2026, 11, 20), "Normal")


def test_a_valid_code_wins_even_if_the_description_names_another_item():
    m = resolve_item(pr("ITM-1002", "Ball bearing 6308-ZZ"), MASTER.items, SETTINGS)
    assert (m.item_code, m.status, m.description_disagrees) == ("ITM-1002", "code", True)
    (checked,) = check_lines([pr("ITM-1002", "Ball bearing 6308-ZZ")], MASTER)
    assert checked.item_code == "ITM-1002" and "F4" in [f.id for f in checked.flags]


def test_a_code_with_a_loose_description_is_not_a_disagreement():
    assert not resolve_item(pr("ITM-1002", "sheet"), MASTER.items, SETTINGS).description_disagrees
    assert not resolve_item(pr("ITM-1002", "MS sheet 3mm 1250x2500"), MASTER.items, SETTINGS).description_disagrees


def test_an_unknown_code_falls_back_to_the_description():
    (checked,) = check_lines([pr("ITM-9999", "MS sheet 3mm 1250x2500")], MASTER)
    assert (checked.item_code, checked.match.status, checked.match.item_code_unknown) == ("ITM-1002", "description", True)
    assert "F3" in [f.id for f in checked.flags]


def test_settings_are_policy_data():
    stricter = {**SETTINGS, "match_threshold": 0.95}
    assert match_description("safty shoes", MASTER.items, stricter).item_code is None
    no_second_pass = {**SETTINGS, "purpose_clause": {"words": [], "separators": [], "brackets": False}}
    assert match_description("MS sheet 3mm 1250x2500 for fabrication", MASTER.items, no_second_pass).item_code is None
    shorthand = {**SETTINGS, "abbreviations": {**SETTINGS["abbreviations"], "glvs": "gloves"}}
    assert match_description("nitrile coated glvs", MASTER.items, shorthand).item_code == "ITM-1048"


def test_matching_reaches_the_line_checks_unit_mismatch():
    line = dataclasses.replace(pr(None, "hyd hose 1/2 inch 2 wire"), uom="NOS")  # the hose is sold in MTR
    (checked,) = check_lines([line], MASTER)
    assert checked.item_code == "ITM-1035" and [f.id for f in checked.not_processed] == ["V5"]


@pytest.mark.parametrize("text, code", [
    ("MS sheet 3mm 1250x2500 for fabrication", "ITM-1002"),
    ("ball bearing 6205-2RS for conveyor line 3", "ITM-1021"),   # the clause's number (3) is dropped with it
    ("nitrile coated gloves - for paint shop", "ITM-1048"),
    ("MS sheet 3mm 1250x2500 (for fabrication)", "ITM-1002"),
    ("hex bolt M10x40 GR 8.8 against PO 123", "ITM-1009"),
    ("Encoder for CNC spindle (Vertex)", "ITM-1034"),            # "for" inside an item name: full text first
])
def test_a_trailing_purpose_clause_is_ignored_when_the_full_text_does_not_match(text, code):
    m = match(text)
    assert m.item_code == code
    if code != "ITM-1034":
        assert "ignored the purpose clause" in m.explanation


@pytest.mark.parametrize("text", [
    "24 inch monitor stand",                     # no clause to remove; "stand" is not in the item
    "laptop bag for i5 laptop",                  # "laptop bag" is not "Laptop i5 16GB 512GB"
    "MS sheet 5mm 1250x2500 for fabrication",    # the number gate still applies in the second pass
])
def test_the_second_pass_does_not_create_false_matches(text):
    assert match(text).item_code is None


def test_dashes_and_slashes_inside_tokens_are_not_clause_markers():
    from engine.matching import purpose_variants
    assert list(purpose_variants("Ball bearing 6205-2RS", SETTINGS)) == []
    assert list(purpose_variants("Solenoid valve 5/2 1/4 inch", SETTINGS)) == []
    assert list(purpose_variants("V-belt B-54", SETTINGS)) == []
