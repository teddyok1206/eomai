from __future__ import annotations

from itertools import pairwise

import pytest
from eom_orchestrator.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    JobState,
    require_transition,
)


def test_happy_path_is_deterministic() -> None:
    path = (
        JobState.CREATED,
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
        JobState.VALIDATING_RESULT,
        JobState.COMMITTING,
        JobState.SUCCEEDED,
    )
    for current, target in pairwise(path):
        require_transition(current, target)


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidStateTransition, match="SUCCEEDED -> RUNNING"):
        require_transition(JobState.SUCCEEDED, JobState.RUNNING)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()
