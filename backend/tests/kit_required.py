"""The task kit is not in the repo (the task rules). Tests that read it skip when data/ does not hold it:

    from kit_required import skip_module_without_kit
    skip_module_without_kit()          # at the top of a module whose tests all need the kit

or @needs_kit on a single test.
"""
import pytest

from kitdata import kit_present

REASON = "kit data not present: put the kit in data/"
needs_kit = pytest.mark.skipif(not kit_present(), reason=REASON)


def skip_module_without_kit():
    if not kit_present():
        pytest.skip(REASON, allow_module_level=True)
