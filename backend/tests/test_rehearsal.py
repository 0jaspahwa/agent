"""H9 guard: every rehearsal amendment, as the reference edit a reviewer would type, is valid and changes
exactly what was predicted from the golden file (pure engine; the full HTTP rehearsal is
scripts/rehearse_amendments.py)."""
import copy
import sys
from pathlib import Path

import pytest

from engine.impact import impact
from engine.policy import load_policy
from engine.policy_check import validate
from kitdata import DATA_DIR
from loaders import kit

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rehearse_amendments as rehearsal  # noqa: E402

MASTER = kit.load_master()
LINES = kit.load_pr_batch(DATA_DIR / "pr_batches" / "sample_pr_batch.csv")
BASE = load_policy("5.0")


@pytest.mark.parametrize("amendment", rehearsal.AMENDMENTS, ids=[a.id for a in rehearsal.AMENDMENTS])
def test_each_amendment_is_expressible_and_changes_what_was_predicted(amendment):
    doc = copy.deepcopy(BASE)
    doc.update(version="5.1", supersedes="5.0", effective_from=amendment.effective_from)
    amendment.edit(doc)
    errors, _ = validate(doc, BASE)
    assert errors == []
    assert amendment.expect().problems(impact(LINES, MASTER, doc)) == []


def test_the_pdf_amendments_read_back_with_their_effective_dates():
    from amendments.extract import extract_text
    for a in rehearsal.AMENDMENTS:
        if a.upload_as == "pdf":
            name, data, _ = rehearsal.upload(a)
            assert "Effective: 1 November 2026" in extract_text(name, data)
