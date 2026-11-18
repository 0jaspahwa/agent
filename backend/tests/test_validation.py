"""E1: line checks (NOT_PROCESSED) and flags (notes), all driven by the policy's line_checks and line_flags."""
import copy
import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.inputs import PolicyVersion, PRLine
from engine.validation import check_lines
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()


def pr(pr_no="PR-T-1", pr_line="1", created_at=datetime(2026, 11, 4, 10, 0), plant="PUN1", item_code="ITM-1002",
       description="MS sheet 3mm 1250x2500", quantity=Decimal("15"), uom="NOS", need_by_date=date(2026, 11, 15),
       urgency="Normal", estimated_unit_price=None):
    return PRLine(pr_no, pr_line, created_at, None, None, plant, item_code, description, quantity, uom,
                  estimated_unit_price, need_by_date, urgency)


def ids(findings):
    return [f.id for f in findings]


def check(*lines, master=MASTER):
    return check_lines(lines, master)


def test_a_clean_line_passes_without_flags():
    (r,) = check(pr())
    assert (r.processed, r.not_processed, r.flags, r.item_code, r.version.version) == (True, (), (), "ITM-1002", "5.0")


@pytest.mark.parametrize("changes, expected", [
    ({"quantity": Decimal("0")}, ["V1"]),                      # PR-26-00172 in the sample batch
    ({"quantity": Decimal("-3")}, ["V1"]),
    ({"quantity": None}, ["V6"]),                               # blank or not a number
    ({"plant": "PUN2"}, ["V2"]),                                # PR-26-00173
    ({"need_by_date": None}, ["V4"]),
    ({"uom": "KG"}, ["V5"]),                                    # MS sheet is NOS
    ({"created_at": None}, ["V7"]),
    ({"quantity": None, "plant": "XX9", "need_by_date": None}, ["V2", "V4", "V6"]),  # every reason is kept
])
def test_line_checks_make_the_line_not_processed(changes, expected):
    (r,) = check(dataclasses.replace(pr(), **changes))
    assert (r.processed, ids(r.not_processed)) == (False, expected)


@pytest.mark.parametrize("changes", [
    {"plant": "pun1"}, {"plant": " Pun1 "},                    # plant codes: case and spaces ignored
    {"item_code": "itm-1002"},                                  # item codes too
    {"uom": "nos"}, {"uom": "Nos."},                            # units: case and punctuation ignored
    {"urgency": "EMERGENCY"},                                   # urgency compared case-insensitively
])
def test_case_and_punctuation_are_ignored(changes):
    (r,) = check(dataclasses.replace(pr(), **changes))
    assert r.processed and r.item_code == "ITM-1002" and "F2" not in ids(r.flags)


def test_duplicate_pr_line_only_the_first_is_processed():
    first, second, third = check(pr(), pr(quantity=Decimal("5")), pr(pr_no="pr-t-1", pr_line=" 1 "))
    assert first.processed
    assert ids(second.not_processed) == ids(third.not_processed) == ["V3"]
    assert check(pr(), pr(pr_line="2"))[1].processed  # same PR, another line number: fine


def test_an_unreadable_creation_time_is_checked_under_the_latest_version():
    (r,) = check(pr(created_at=None))
    assert (ids(r.not_processed), r.version.version) == (["V7"], "5.0")


def test_a_line_before_any_policy_is_in_force_is_not_processed():
    (r,) = check(pr(created_at=datetime(2026, 3, 31, 9, 0)))  # v5.0 starts 2026-04-01
    assert ids(r.not_processed) == ["NO-POLICY"] and "2026-03-31" in r.not_processed[0].text


@pytest.mark.parametrize("changes, flag", [
    ({"need_by_date": date(2026, 11, 1)}, "F1"),                # need-by before creation (11-04)
    ({"urgency": None}, "F2"),
    ({"urgency": "urgnt"}, "F2"),
    ({"item_code": "ITM-9999"}, "F3"),                          # unknown code: description is matched instead
    ({"description": "MS sheet 3mm 1250x2500 - URGENT"}, "F5"),  # 4 such lines in the sample batch
    ({"uom": None}, "F6"),
])
def test_flags_note_the_line_but_do_not_stop_it(changes, flag):
    (r,) = check(dataclasses.replace(pr(), **changes))
    assert flag in ids(r.flags)
    assert "V" not in "".join(ids(r.not_processed))  # no line check fired because of the flag's cause


def test_unrecognised_urgency_is_treated_as_normal_and_emergency_is_kept():
    assert check(pr(urgency="soonish"))[0].urgency == "Normal"
    assert check(pr(urgency="emergency"))[0].urgency == "Emergency"


def test_checks_are_policy_data_an_amendment_can_remove_one():
    doc = copy.deepcopy(MASTER.policies[0].document)
    doc["line_checks"] = [c for c in doc["line_checks"] if c["id"] != "V3"]
    master = dataclasses.replace(MASTER, policies=(PolicyVersion("5.1", date(2026, 4, 1), doc),))
    assert all(r.processed for r in check(pr(), pr(), master=master))


def test_sample_batch_has_exactly_the_two_known_bad_lines_and_four_urgent_descriptions():
    results = check_lines(kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"), MASTER)
    assert len(results) == 186
    bad = {(r.line.pr_no, tuple(ids(r.not_processed))) for r in results if not r.processed}
    assert bad == {("PR-26-00172", ("V1",)), ("PR-26-00173", ("V2",))}
    urgent = sorted(r.line.pr_no for r in results if "F5" in ids(r.flags))
    assert urgent == ["PR-26-00018", "PR-26-00023", "PR-26-00139", "PR-26-00167"]


def test_possible_duplicate_flag_names_the_other_line_and_changes_no_decision():
    results = check_lines(kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv"), MASTER)
    flagged = {r.line.pr_no: f.text for r in results for f in r.flags if f.id == "F7"}
    assert set(flagged) == {"PR-26-00174", "PR-26-00175"}  # the only pair in the sample batch
    assert "PR-26-00175/1" in flagged["PR-26-00174"] and "PR-26-00174/1" in flagged["PR-26-00175"]
    assert all(r.processed for r in results if r.line.pr_no in flagged)


@pytest.mark.parametrize("second, flagged", [
    ({"created_at": datetime(2026, 11, 4, 10, 30)}, True),     # exactly 30 minutes later: inclusive
    ({"created_at": datetime(2026, 11, 4, 10, 31)}, False),    # 31 minutes
    ({"quantity": Decimal("16")}, False),                      # different quantity
    ({"need_by_date": date(2026, 11, 16)}, False),
    ({"plant": "CHK1"}, False),
    ({"item_code": "ITM-1001", "description": "MS sheet 2mm 1250x2500"}, False),
])
def test_possible_duplicate_needs_every_field_equal_within_the_window(second, flagged):
    a = dataclasses.replace(pr(), requester="S. Patil")
    b = dataclasses.replace(pr(pr_no="PR-T-2", created_at=datetime(2026, 11, 4, 10, 5)), requester="s. patil ", **second)
    assert ("F7" in ids(check(a, b)[0].flags)) is flagged


def test_a_line_without_a_requester_is_never_a_possible_duplicate():
    assert "F7" not in ids(check(pr(), pr(pr_no="PR-T-2"))[0].flags)
