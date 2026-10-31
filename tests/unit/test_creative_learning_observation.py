"""Observer cannot infer acceptance, mutate state or expose arbitrary status data."""

from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_service import creative_learning_observation as observation
from eom_catalog_service.creative_learning_runner import write_status

COHORT_ID = "creativecohort_" + "a" * 32


@pytest.mark.parametrize("state", ("ANALYZING", "PROCESSING"))
def test_observer_returns_only_bounded_metadata_not_arbitrary_saved_values(tmp_path, state):
    root = tmp_path / "status"
    root.mkdir(mode=0o750)
    write_status(
        root,
        COHORT_ID,
        {
            "state": state,
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


@pytest.mark.parametrize(
    "fault", [None, "missing_content", "duplicate", "unknown_error", "overcount"]
)
def test_deferred_sources_are_counted_separately_without_becoming_completed(tmp_path, fault):
    root = tmp_path / "status"
    root.mkdir(mode=0o750)
    blocked = [["11400", "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING"]]
    if fault == "missing_content":
        blocked = [["11416", "CREATIVE_SOURCE_ITEM_UNREADABLE"]]
    if fault == "duplicate":
        blocked *= 2
    elif fault == "unknown_error":
        blocked[0][1] = "SOURCE_PERMISSION_DENIED"
    write_status(
        root,
        COHORT_ID,
        {
            "state": "PROCESSING",
            "verified_count": 3 if fault == "overcount" else 2,
            "target_count": 3,
            "blocked_sources": blocked,
        },
    )
    if fault in (None, "missing_content"):
        result = observation.read_observation(root, COHORT_ID)
        assert result["verified_count"] == 2 and result["blocked_source_count"] == 1
        assert "blocked_sources" not in result
    else:
        with pytest.raises(ValueError):
            observation.read_observation(root, COHORT_ID)
