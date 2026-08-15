"""Explicit HWPX build state transitions."""

from __future__ import annotations

from enum import StrEnum


class HwpxBuildState(StrEnum):
    CREATED = "CREATED"
    VALIDATING_INPUT = "VALIDATING_INPUT"
    STAGING = "STAGING"
    RENDERING = "RENDERING"
    PACKAGING = "PACKAGING"
    VALIDATING_OUTPUT = "VALIDATING_OUTPUT"
    COMMITTING = "COMMITTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PENDING_MANUAL_VALIDATION = "PENDING_MANUAL_VALIDATION"


TRANSITIONS: dict[HwpxBuildState, frozenset[HwpxBuildState]] = {
    HwpxBuildState.CREATED: frozenset({HwpxBuildState.VALIDATING_INPUT, HwpxBuildState.FAILED}),
    HwpxBuildState.VALIDATING_INPUT: frozenset({HwpxBuildState.STAGING, HwpxBuildState.FAILED}),
    HwpxBuildState.STAGING: frozenset({HwpxBuildState.RENDERING, HwpxBuildState.FAILED}),
    HwpxBuildState.RENDERING: frozenset({HwpxBuildState.PACKAGING, HwpxBuildState.FAILED}),
    HwpxBuildState.PACKAGING: frozenset({HwpxBuildState.VALIDATING_OUTPUT, HwpxBuildState.FAILED}),
    HwpxBuildState.VALIDATING_OUTPUT: frozenset({HwpxBuildState.COMMITTING, HwpxBuildState.FAILED}),
    HwpxBuildState.COMMITTING: frozenset(
        {HwpxBuildState.PENDING_MANUAL_VALIDATION, HwpxBuildState.FAILED}
    ),
    HwpxBuildState.PENDING_MANUAL_VALIDATION: frozenset(
        {HwpxBuildState.SUCCEEDED, HwpxBuildState.FAILED}
    ),
    HwpxBuildState.SUCCEEDED: frozenset(),
    HwpxBuildState.FAILED: frozenset(),
}


class InvalidHwpxBuildTransition(RuntimeError):
    pass


def require_transition(current: HwpxBuildState, target: HwpxBuildState) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidHwpxBuildTransition(f"invalid HWPX build transition: {current} -> {target}")
