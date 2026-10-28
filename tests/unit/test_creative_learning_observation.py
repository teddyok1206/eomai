"""Observer cannot infer acceptance, mutate state or expose arbitrary status data."""

from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_service import creative_learning_observation as observation
from eom_catalog_service.creative_learning_runner import write_status

COHORT_ID = "creativecohort_" + "a" * 32


def test_observer_returns_only_bounded_metadata_not_arbitrary_saved_values(tmp_path):
    root = tmp_path / "status"
    root.mkdir(mode=0o750)
    write_status(
        root,
        COHORT_ID,
        {
            "state": "ANALYZING",
            "verified_count": 3,
            "target_count": 1053,
            "private": "not exported",
        },
    )
    result = observation.read_observation(root, COHORT_ID)
    assert result["verified_count"] == 3 and not result["status_stale"]
    assert "private" not in result and "NOT_ACCEPTANCE" in result["authority"]


@pytest.mark.parametrize("completed,total", [(-1, 3), (4, 3), (True, 3), (0, 20001)])
def test_observer_rejects_corrupt_counters(tmp_path, completed, total):
    root = tmp_path / "status"
    root.mkdir(mode=0o750)
    write_status(
        root, COHORT_ID, {"state": "ANALYZING", "verified_count": completed, "target_count": total}
    )
    with pytest.raises(ValueError):
        observation.read_observation(root, COHORT_ID)


def test_stale_status_is_not_reported_as_recent_progress(tmp_path, monkeypatch):
    root = tmp_path / "status"
    root.mkdir(mode=0o750)
    write_status(
        root, COHORT_ID, {"state": "EXTRACTING", "verified_count": 3, "target_count": 1053}
    )
    real = datetime.now(UTC)

    class Clock:
        fromisoformat = datetime.fromisoformat

        @staticmethod
        def now(_tz):
            return real + timedelta(minutes=31)

    monkeypatch.setattr(observation, "datetime", Clock)
    assert observation.read_observation(root, COHORT_ID)["status_stale"]
