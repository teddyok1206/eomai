"""Explicit lifecycle for queued Item Revision HWPX application builds."""

from __future__ import annotations

from enum import StrEnum


class ApplicationBuildState(StrEnum):
    REQUESTED = "REQUESTED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


APPLICATION_BUILD_TRANSITIONS: dict[ApplicationBuildState, frozenset[ApplicationBuildState]] = {
    ApplicationBuildState.REQUESTED: frozenset(
        {ApplicationBuildState.RUNNING, ApplicationBuildState.FAILED}
    ),
    ApplicationBuildState.RUNNING: frozenset(
        {ApplicationBuildState.VALIDATING, ApplicationBuildState.FAILED}
    ),
    ApplicationBuildState.VALIDATING: frozenset(
        {ApplicationBuildState.SUCCEEDED, ApplicationBuildState.FAILED}
    ),
    ApplicationBuildState.SUCCEEDED: frozenset(),
    ApplicationBuildState.FAILED: frozenset(),
}


def require_application_transition(
    current: ApplicationBuildState, target: ApplicationBuildState
) -> None:
    if target not in APPLICATION_BUILD_TRANSITIONS[current]:
        raise RuntimeError(f"invalid application HWPX build transition: {current} -> {target}")
