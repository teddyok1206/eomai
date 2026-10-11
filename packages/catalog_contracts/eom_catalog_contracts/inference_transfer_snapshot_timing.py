"""Fixed adapter deadlines, not public request options or an authorization grant.

Full-population AUTHORIZE previously completed in 119.2 seconds against a
120-second Catalog deadline and an identical owner HTTP timeout. Its bounded
300-second owner-read budget needs a separate 30-second outer transport margin.
PREPARE, READ and all non-snapshot HTTP behavior retain their existing limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

type SnapshotPhase = Literal["PREPARE", "READ", "AUTHORIZE"]

DEFAULT_SNAPSHOT_TIMEOUT_SECONDS: Final = 120.0


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


def snapshot_phase_deadlines(phase: SnapshotPhase) -> SnapshotPhaseDeadlines:
    """Select only an already validated phase; no caller-supplied numeric timeout."""
    try:
        return _PHASE_DEADLINES[phase]
    except (KeyError, TypeError):
        raise ValueError("unsupported snapshot phase") from None
