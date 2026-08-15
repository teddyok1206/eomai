from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.hwpx_reference_live


def test_reference_candidate_exists_for_opt_in_live_pipeline() -> None:
    reference = Path("/mnt/nas/eom/hwpx/poc-v0/reference/inbox/eom_hwpx_reference_v1.hwpx")
    if not reference.is_file():
        pytest.skip("PENDING_REFERENCE_TEMPLATE")
    assert reference.stat().st_size > 0
