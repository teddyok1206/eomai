"""Fixed adapter deadlines, not public request options or an authorization grant.

Full-population AUTHORIZE previously completed in 119.2 seconds against a
120-second Catalog deadline and an identical owner HTTP timeout. Its bounded
300-second owner-read budget needs a separate 30-second outer transport margin.
Comparison submission performs one PREPARE and two READ calls before returning
its command receipt. Only that exact POST composition has a separate outer
deadline; PREPARE, READ and other non-snapshot HTTP limits remain unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

type SnapshotPhase = Literal["PREPARE", "READ", "AUTHORIZE"]

DEFAULT_SNAPSHOT_TIMEOUT_SECONDS: Final = 120.0
COMPARISON_WORKFLOW_READ_TIMEOUT_SECONDS: Final = 120.0


@dataclass(frozen=True, slots=True)
class SnapshotPhaseDeadlines:
    catalog_response_seconds: float
    owner_http_seconds: float


_PHASE_DEADLINES: Final = MappingProxyType(
    {
        "PREPARE": SnapshotPhaseDeadlines(120.0, 120.0),
        "READ": SnapshotPhaseDeadlines(120.0, 120.0),
        "AUTHORIZE": SnapshotPhaseDeadlines(300.0, 330.0),
    }
)

# This is a transport budget, not a hard upper bound on database lock waits,
# session freshness, authorization or model execution. A timeout remains unknown.
COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS: Final = (
    _PHASE_DEADLINES["PREPARE"].catalog_response_seconds
    + 2 * _PHASE_DEADLINES["READ"].catalog_response_seconds
    + 30.0
)

# Explicit retry first performs a current own-creator Workflow/source read,
# then the exact original submission's PREPARE/READ composition.
COMPARISON_RETRY_HTTP_TIMEOUT_SECONDS: Final = (
    COMPARISON_WORKFLOW_READ_TIMEOUT_SECONDS + COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS
)


def snapshot_phase_deadlines(phase: SnapshotPhase) -> SnapshotPhaseDeadlines:
    """Select only an already validated phase; no caller-supplied numeric timeout."""
    try:
        return _PHASE_DEADLINES[phase]
    except (KeyError, TypeError):
        raise ValueError("unsupported snapshot phase") from None
