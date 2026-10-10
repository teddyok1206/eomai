"""Small shared execution outcome; not an authorization or Artifact resolver."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleExecutionResult:
    job_id: str
    status: str
    worker_slot: str | None
    logical_artifact_id: str
    revision_id: str
    content_hash: str | None
    error_code: str | None
