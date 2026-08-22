"""Mandatory typed boundary between the workflow engine and catalog use cases."""

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


@dataclass(frozen=True)
class GeneratedStimulusPointer:
    artifact_id: str
    artifact_revision_id: str
    artifact_member: str
    sha256: str
    media_type: str
    width_px: int
    height_px: int
    source_result_revision_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_revision_id": self.artifact_revision_id,
            "artifact_member": self.artifact_member,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "source_result_revision_id": self.source_result_revision_id,
        }


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

    def materialize_generated_stimulus(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> GeneratedStimulusPointer: ...
