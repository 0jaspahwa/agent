"""E3: clubbing (policy 2.2, 2.3), driven by the policy's clubbing parameters."""
import copy
import dataclasses
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from engine.clubbing import club
from engine.inputs import PolicyVersion, PRLine
from engine.validation import check_lines
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
SAMPLE = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
SAMPLE_REQS = club(check_lines(SAMPLE, MASTER), MASTER)


def group_of(pr_no, reqs=SAMPLE_REQS):
    return next(r for r in reqs if any(c.line.pr_no == pr_no for c in r.lines))


def members(req):
    return [c.line.pr_no for c in req.lines]


# ---------------------------------------------------------------- worked examples, as printed
def test_ex3_free_text_and_coded_bearing_lines_club():
    r = group_of("PR-26-00004")
    assert members(r) == ["PR-26-00004", "PR-26-00026"]
    assert (r.item_code, r.plant, r.requirement_date, r.total_quantity) == ("ITM-1022", "CHK1", date(2026, 11, 2), 380)


def test_ex5_three_split_prs_are_one_requirement():
    r = group_of("PR-26-00146")
    assert members(r) == ["PR-26-00146", "PR-26-00144", "PR-26-00145"]
    assert (r.item_code, r.requirement_date, r.total_quantity, r.is_emergency) == ("ITM-1038", date(2026, 11, 2), 760, False)


def test_ex6_same_item_different_plants_are_not_clubbed():
    pun, chk = group_of("PR-26-00106"), group_of("PR-26-00103")
    assert members(pun) == ["PR-26-00106"] and members(chk) == ["PR-26-00103"]
    assert (pun.item_code, pun.plant, pun.total_quantity) == ("ITM-1044", "PUN1", 7370)
    assert (chk.item_code, chk.plant, chk.total_quantity) == ("ITM-1044", "CHK1", 6480)


def test_ex14_clubbing_anchors_on_the_first_line():
    a, b = group_of("PR-26-00034"), group_of("PR-26-00031")
    assert members(a) == ["PR-26-00034", "PR-26-00032"]  # 00032 need-by 11-29 is 4 days from 11-25
    assert members(b) == ["PR-26-00031", "PR-26-00035"]  # 00035 is 8 days from 11-25 but 5 from 11-12
    assert (a.total_quantity, b.total_quantity) == (4610, 3290)  # Ex 4 and Ex 14 values: x 7.06


def test_sample_batch_summary():
    assert len(SAMPLE_REQS) == 149
    assert sum(len(r.lines) for r in SAMPLE_REQS) == 184  # 186 lines minus the two NOT_PROCESSED
    assert sorted(members(r)[0] for r in SAMPLE_REQS if r.is_new) == ["PR-26-00170", "PR-26-00171"]
    assert [r.group_id for r in SAMPLE_REQS] == [f"R-{n:04d}" for n in range(1, 150)]


def test_group_ids_are_deterministic_and_follow_first_line_creation():
    again = club(check_lines(SAMPLE, MASTER), MASTER)
    assert [(r.group_id, members(r)) for r in again] == [(r.group_id, members(r)) for r in SAMPLE_REQS]
    firsts = [r.created_at for r in SAMPLE_REQS]
    assert firsts == sorted(firsts)
    shuffled = club(check_lines(tuple(reversed(SAMPLE)), MASTER), MASTER)  # file order does not matter
    assert [(r.group_id, sorted(members(r))) for r in shuffled] == [(r.group_id, sorted(members(r))) for r in SAMPLE_REQS]


# ---------------------------------------------------------------- synthetic boundaries (D4, D5)
BASE = datetime(2026, 11, 2, 10, 0)


def pr(pr_no, created_at=BASE, need_by=date(2026, 11, 20), item_code="ITM-1038", plant="CHK1", quantity="100",
       description="Hydraulic oil HLP 68", urgency="Normal", pr_line="1", uom="LTR"):
    return PRLine(pr_no, pr_line, created_at, None, None, plant, item_code, description, Decimal(quantity), uom,
                  None, need_by, urgency)


def requirements(*lines, master=MASTER):
    return club(check_lines(lines, master), master)


@pytest.mark.parametrize("second, together", [
    (pr("B", created_at=BASE + timedelta(days=14)), True),                        # day 14 joins
    (pr("B", created_at=datetime(2026, 11, 16, 23, 59)), True),                   # 14 calendar days, >14x24h elapsed
    (pr("B", created_at=BASE + timedelta(days=15)), False),                       # day 15 does not
    (pr("B", created_at=BASE + timedelta(days=1), need_by=date(2026, 11, 27)), True),   # need-by +7 joins
    (pr("B", created_at=BASE + timedelta(days=1), need_by=date(2026, 11, 13)), True),   # need-by -7 joins
    (pr("B", created_at=BASE + timedelta(days=1), need_by=date(2026, 11, 28)), False),  # +8 does not
    (pr("B", plant="PUN1"), False),                                               # different plant
    (pr("B", item_code="ITM-1054", description="Way lube oil 68"), False),         # different item
])
def test_clubbing_windows_and_keys(second, together):
    reqs = requirements(pr("A"), second)
    assert (len(reqs) == 1) is together


def test_a_line_that_could_join_two_requirements_joins_the_earliest():
    a = pr("A", need_by=date(2026, 11, 20))
    b = pr("B", created_at=BASE + timedelta(days=1), need_by=date(2026, 11, 30))  # 10 days from A: separate
    c = pr("C", created_at=BASE + timedelta(days=2), need_by=date(2026, 11, 25))  # 5 from A and 5 from B
    reqs = requirements(a, b, c)
    assert [members(r) for r in reqs] == [["A", "C"], ["B"]]


def test_a_multi_line_pr_clubs_its_lines_by_item():
    lines = [pr("M", pr_line="1"), pr("M", pr_line="2", quantity="50"),
             pr("M", pr_line="3", item_code="ITM-1054", description="Way lube oil 68")]
    reqs = requirements(*lines)
    assert [[c.line.pr_line for c in r.lines] for r in reqs] == [["1", "2"], ["3"]]
    assert reqs[0].total_quantity == 150
    sample_multi = [r for r in SAMPLE_REQS if any(c.line.pr_no == "PR-26-00169" for c in r.lines)]
    assert len(sample_multi) == 3  # PR-26-00169 has three lines for three different items


def test_new_items_are_never_clubbed_and_not_processed_lines_are_left_out():
    new = dict(item_code=None, description="Ultrasonic thickness gauge", uom="NOS")
    reqs = requirements(pr("A", **new), pr("B", **new), pr("C", quantity="0"))
    assert [members(r) for r in reqs] == [["A"], ["B"]] and all(r.is_new for r in reqs)


def test_one_emergency_line_makes_the_requirement_an_emergency():
    reqs = requirements(pr("A"), pr("B", created_at=BASE + timedelta(hours=3), urgency="EMERGENCY"))
    assert len(reqs) == 1 and reqs[0].is_emergency


def with_policy(document, effective_from=date(2026, 4, 1), version="5.1", keep_v5=False):
    policy = PolicyVersion(version, effective_from, document)
    policies = (*MASTER.policies, policy) if keep_v5 else (policy,)
    return dataclasses.replace(MASTER, policies=policies)


def test_an_override_widens_the_window_for_one_category_only():
    doc = copy.deepcopy(MASTER.policies[0].document)
    doc["overrides"] = [{"id": "OV-1", "parameter": "clubbing.creation_window",
                         "when": {"==": [{"var": "item.category"}, "Hydraulics & Pneumatics"]}, "set": {"length": 30}}]
    master = with_policy(doc)
    late = BASE + timedelta(days=25)
    oil = requirements(pr("A"), pr("B", created_at=late, need_by=date(2026, 11, 20)), master=master)
    assert len(oil) == 1  # hydraulic oil: 30-day window
    gloves = dict(item_code="ITM-1048", description="Nitrile coated gloves", uom="PAIR")
    other = requirements(pr("A", **gloves), pr("B", created_at=late, **gloves), master=master)
    assert len(other) == 2  # safety gloves: still 14 days


def test_a_joining_line_is_judged_by_the_first_lines_policy_version():
    doc = copy.deepcopy(MASTER.policies[0].document)
    doc["parameters"]["clubbing"]["need_by_window"]["length"] = 1  # v5.1 from 11-10: need-by within 1 day
    master = with_policy(doc, effective_from=date(2026, 11, 10), keep_v5=True)
    before = requirements(pr("A", created_at=datetime(2026, 11, 5, 9, 0), need_by=date(2026, 11, 20)),
                          pr("B", created_at=datetime(2026, 11, 12, 9, 0), need_by=date(2026, 11, 24)), master=master)
    assert len(before) == 1 and before[0].version.version == "5.0"  # A's version (5.0): 4 days is fine
    after = requirements(pr("A", created_at=datetime(2026, 11, 11, 9, 0), need_by=date(2026, 11, 20)),
                         pr("B", created_at=datetime(2026, 11, 12, 9, 0), need_by=date(2026, 11, 24)), master=master)
    assert len(after) == 2 and after[0].version.version == "5.1"


def test_the_clubbing_key_is_policy_data():
    doc = copy.deepcopy(MASTER.policies[0].document)
    doc["parameters"]["clubbing"]["match_on"] = ["item_code"]  # plant no longer separates requirements
    reqs = requirements(pr("A"), pr("B", plant="PUN1"), master=with_policy(doc))
    assert len(reqs) == 1
