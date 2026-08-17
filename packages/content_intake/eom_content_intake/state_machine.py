"""Deterministic content intake lifecycle."""

from enum import StrEnum

from eom_content_intake.errors import IntakeError, IntakeErrorCode


class IntakeState(StrEnum):
    RECEIVED = "RECEIVED"
    HASHED = "HASHED"
    ANALYSIS_PENDING = "ANALYSIS_PENDING"
    ANALYSIS_ATTACHED = "ANALYSIS_ATTACHED"
    VALIDATING = "VALIDATING"
    NEEDS_DECISION = "NEEDS_DECISION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    IMPORTED = "IMPORTED"
    FAILED = "FAILED"


TRANSITIONS: dict[IntakeState, frozenset[IntakeState]] = {
    IntakeState.RECEIVED: frozenset({IntakeState.HASHED, IntakeState.FAILED}),
    IntakeState.HASHED: frozenset({IntakeState.ANALYSIS_PENDING, IntakeState.FAILED}),
    IntakeState.ANALYSIS_PENDING: frozenset(
        {IntakeState.ANALYSIS_ATTACHED, IntakeState.SUPERSEDED, IntakeState.FAILED}
    ),
    IntakeState.ANALYSIS_ATTACHED: frozenset(
        {IntakeState.VALIDATING, IntakeState.SUPERSEDED, IntakeState.FAILED}
    ),
    IntakeState.VALIDATING: frozenset({IntakeState.NEEDS_DECISION, IntakeState.FAILED}),
    IntakeState.NEEDS_DECISION: frozenset(
        {
            IntakeState.ACCEPTED,
            IntakeState.REJECTED,
            IntakeState.SUPERSEDED,
            IntakeState.FAILED,
        }
    ),
    IntakeState.ACCEPTED: frozenset({IntakeState.IMPORTED}),
    IntakeState.REJECTED: frozenset(),
    IntakeState.SUPERSEDED: frozenset(),
    IntakeState.IMPORTED: frozenset(),
    IntakeState.FAILED: frozenset(),
}


def require_transition(current: IntakeState, target: IntakeState) -> None:
    if target not in TRANSITIONS[current]:
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_INVALID,
            f"invalid intake transition: {current.value} -> {target.value}",
        )
