"""H5: impact preview of a draft on the sample batch (pure, from the kit)."""
import copy

from engine.impact import impact
from engine.pipeline import decide
from engine.policy import load_policy
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

MASTER = kit.load_master()
LINES = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
BASE = load_policy("5.0")
VALUES = {f"{r['pr_no']}/{r['pr_line']}": r["group_value_inr"] for r in decide(LINES, MASTER).rows}


def draft(effective_from="2026-04-01", change=lambda p: None):
    doc = copy.deepcopy(BASE)
    doc.update(version="5.1", supersedes="5.0", effective_from=effective_from)
    change(doc)
    return doc


def test_an_unchanged_copy_changes_nothing_and_says_why():
    result = impact(LINES, MASTER, draft())
    assert (result["changed"], result["lines_under_draft"]) == (0, 186)  # every line, NOT_PROCESSED ones too
    assert "does not alter any of their decisions" in result["explanation"]


def test_a_draft_effective_after_the_batch_reports_no_change_and_the_reason():
    result = impact(LINES, MASTER, draft("2026-12-01", lambda p: p["parameters"]["limits"]["spot_po"].update(value=1)))
    assert result["changed"] == 0
    assert result["explanation"] == ("No decision changes: the effective date 2026-12-01 is after the last requirement "
                                     "in this batch (2026-11-20)")


def test_a_lower_spot_limit_lists_every_line_that_changes_with_before_and_after():
    result = impact(LINES, MASTER, draft(change=lambda p: p["parameters"]["limits"]["spot_po"].update(value=150000)))
    assert result["routes_after"]["SPOT_PO"] < result["routes_before"]["SPOT_PO"] == 72
    rerouted = [c for c in result["changes"] if "route" in c["changes"]]
    assert rerouted and all(c["changes"]["route"] == {"before": "SPOT_PO", "after": "RFQ"} and c["rule_after"] == "5.5"
                            for c in rerouted)
    for c in rerouted:  # exactly the spot POs valued from 1,50,000 up to (not including) 2,00,000
        assert 150000 <= float(VALUES[c["line"]]) < 200000
    others = [c for c in result["changes"] if "route" not in c["changes"]]
    assert all(set(c["changes"]) == {"same_po_as"} for c in others)  # their PO partner became an RFQ
    assert "PR-26-00146/1" not in [c["line"] for c in result["changes"]]  # Ex 5, 1,26,472: still a spot PO


def test_a_mid_batch_effective_date_changes_only_later_requirements():
    result = impact(LINES, MASTER, draft("2026-11-10", lambda p: p["parameters"]["limits"]["spot_po"].update(value=1)))
    assert result["changed"] > 0
    assert all(c["version_after"] == "5.1" for c in result["changes"])
    assert all(c["line"] not in ("PR-26-00146/1", "PR-26-00106/1") for c in result["changes"])  # 11-02 requirements
