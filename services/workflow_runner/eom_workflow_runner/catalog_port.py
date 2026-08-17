"""Typed optional boundary between the workflow engine and catalog use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eom_workflow import ArtifactPointer, WorkflowRequest

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


@dataclass(frozen=True)
class PreparedPrompt:
    text: str
    pointer: dict[str, Any]
    envelope: dict[str, Any]


@dataclass(frozen=True)
class RegistrationOutcome:
    item_id: str
    item_revision_id: str
    revision_number: int
    manifest_artifact_id: str
    manifest_artifact_revision_id: str
    manifest_sha256: str


class WorkflowCatalogPort(Protocol):
    def prepare_prompt(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
    ) -> PreparedPrompt: ...

    def register_workflow(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> RegistrationOutcome: ...
