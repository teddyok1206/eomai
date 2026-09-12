from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_api.errors import ApiError
from eom_api.services.query_adapter import QueryAdapter

NOW = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)


def _row(predecessor: str, state: str, *, offset: int = 0) -> SimpleNamespace:
    observed = NOW + timedelta(seconds=offset)
    return SimpleNamespace(
        predecessor_analysis_run_id=predecessor,
        state=state,
        created_at=observed,
        started_at=observed if state not in {"REQUESTED", "RESOLVED"} else None,
        completed_at=observed if state in {"ACCEPTED", "FAILED", "REJECTED", "CANCELLED"} else None,
    )


def test_solution_report_progress_classifies_each_graph_analysis_once() -> None:
    base = {"base-a", "base-b", "base-c", "base-d"}
    result = QueryAdapter._classify_solution_report_progress(
        base,
        (
            _row("base-a", "FAILED", offset=1),
            _row("base-a", "ACCEPTED", offset=2),
            _row("base-b", "RUNNING", offset=3),
            _row("base-c", "REJECTED", offset=4),
        ),
    )

    assert (result.total, result.completed, result.active, result.failed, result.pending) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert result.status == "BLOCKED"
    assert result.updated_at == NOW + timedelta(seconds=4)


def test_solution_report_progress_distinguishes_not_started_and_complete() -> None:
    pending = QueryAdapter._classify_solution_report_progress({"base-a", "base-b"}, ())
    assert pending.status == "NOT_STARTED"
    assert pending.pending == 2
    assert pending.updated_at is None

    completed = QueryAdapter._classify_solution_report_progress(
        {"base-a", "base-b"},
        (_row("base-a", "ACCEPTED"), _row("base-b", "ACCEPTED", offset=1)),
    )
    assert completed.status == "COMPLETED"
    assert completed.completed == 2
    assert completed.updated_at == NOW + timedelta(seconds=1)


@pytest.mark.parametrize(
    "rows",
    [
        (_row("base-a", "RUNNING"), _row("base-a", "QUEUED")),
        (_row("base-a", "ACCEPTED"), _row("base-a", "ACCEPTED")),
        (_row("unknown-base", "ACCEPTED"),),
        (_row("base-a", "UNRECOGNIZED"),),
    ],
)
def test_solution_report_progress_rejects_ambiguous_or_dangling_history(
    rows: tuple[SimpleNamespace, ...],
) -> None:
    with pytest.raises(ApiError) as raised:
        QueryAdapter._classify_solution_report_progress({"base-a"}, rows)
    assert raised.value.error_code == "ASSESSMENT_LEARNING_PROJECTION_INVALID"
