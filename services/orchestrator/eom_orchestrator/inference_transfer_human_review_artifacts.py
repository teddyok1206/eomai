"""Human-review materialization through the existing Orchestrator Artifact reader."""

from __future__ import annotations

from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member


class OwnedHumanReviewArtifacts:
    """Current source authorization is the calling application's responsibility."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, pointer: ArtifactMemberPointer, *, maximum_bytes: int) -> bytes:
        return resolve_control_artifact_member(self.engine, pointer, maximum_bytes=maximum_bytes)
