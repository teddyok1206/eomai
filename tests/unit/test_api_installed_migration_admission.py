"""Catch a stale installed-wheel gate before an expensive release build."""

import re
from pathlib import Path

from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION


def test_installed_simulation_expected_head_matches_the_reviewed_source_head():
    source = (Path(__file__).resolve().parents[2] / "scripts/api/deploy_release.sh").read_text()
    expected = re.findall(r'if CURRENT_MIGRATION_REVISION != "([0-9]{8}_[0-9]{4})":', source)
    assert expected == [CURRENT_MIGRATION_REVISION]
