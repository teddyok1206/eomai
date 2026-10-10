"""Small removable local CPU and existing owner-publication boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from eom_protocol.artifact_members import ArtifactMemberPointer


class CpuExperimentRunError(RuntimeError):
    """Only the installed launcher may identify a confirmed terminal failure."""

    def __init__(self, outcome: Literal["KNOWN_FAILED", "UNCERTAIN"]) -> None:
        if outcome not in {"KNOWN_FAILED", "UNCERTAIN"}:
            raise ValueError("invalid CPU execution observation")
        self.outcome = outcome
        super().__init__(outcome)


@dataclass(frozen=True, slots=True)
class LocalExperimentInput:
    workspace: Path
    execution_id: str
    created_at: datetime
    request_sha256: str
    request_bytes: int


class CpuExperimentRunPort(Protocol):
    def run(self, prepared: LocalExperimentInput) -> None:
        """Run the existing harness once; return only after confirmed termination.

        The installed adapter owns explicit compatible CPU runtime and OS
        isolation. It reads only this staged request and writes ``result.json``.
        Timeout/unknown termination raises UNCERTAIN, never a no-op retry grant.
        No unsandboxed or ambient-interpreter fallback exists in this module.
        """
        ...


@dataclass(frozen=True, slots=True)
class LocalExperimentPublication:
    execution_id: str
    created_at: datetime
    result_sha256: str
    source: Path
    member_sha256: str
    member_bytes: int


@dataclass(frozen=True, slots=True)
class PublishedExperimentResult:
    job_id: str
    result: ArtifactMemberPointer
    manifest_sha256: str


class ExperimentResultCommitPort(Protocol):
    def publish(self, prepared: LocalExperimentPublication) -> PublishedExperimentResult:
        """Existing Orchestrator commit owner only, after current source reauthorization."""
        ...
