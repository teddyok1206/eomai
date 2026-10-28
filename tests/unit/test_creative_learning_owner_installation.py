"""Installation accepts fixed identities only and is separate from execution."""

from pathlib import Path

import pytest

from scripts.catalog.install_creative_learning_owner import render_configuration

PREFIX = Path("/opt/eom/maintenance-releases/" + "a" * 40)
COHORT = "creativecohort_" + "b" * 32
REVISION = "rev_" + "c" * 32


def test_configuration_contains_metadata_only_and_canary_limit():
    result = render_configuration(PREFIX, COHORT, REVISION, 3)
    assert "EOM_CREATIVE_VERIFIED_LIMIT=3\n" in result
    assert set(line.split("=", 1)[0] for line in result.splitlines()) == {
        "EOM_CREATIVE_COHORT_ID",
        "EOM_CREATIVE_COHORT_REVISION_ID",
        "EOM_CREATIVE_VERIFIED_LIMIT",
    }


@pytest.mark.parametrize(
    "prefix,cohort,revision,limit",
    [
        (Path("/tmp/user-code"), COHORT, REVISION, 3),
        (PREFIX, COHORT + "\nEVIL=1", REVISION, 3),
        (PREFIX, COHORT, "latest", 3),
        (PREFIX, COHORT, REVISION, 0),
    ],
)
def test_invalid_identity_or_configuration_injection_is_rejected(prefix, cohort, revision, limit):
    with pytest.raises(ValueError):
        render_configuration(prefix, cohort, revision, limit)
