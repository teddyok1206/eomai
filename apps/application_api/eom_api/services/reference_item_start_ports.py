"""Operation-local reference preparation handoff, not source or execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts import EvidenceBundlePublicationResultV5
from eom_operator_identity import ActorContext
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowId, WorkflowRequest
from eom_workflow_runner.item_similarity_preparation import PreparedItemSimilarity
from pydantic import TypeAdapter


@dataclass(frozen=True, slots=True)
class ReferenceItemStartPending:
    reference_query_workflow_id: str

    def __post_init__(self) -> None:
        TypeAdapter(WorkflowId).validate_python(self.reference_query_workflow_id, strict=True)


class ReferenceItemStartPreparationPort(Protocol):
    def prepare(
        self,
        actor: ActorContext,
        *,
        workflow_request: WorkflowRequest,
        expected_resolution: ExpectedWorkflowResolution,
        evidence: EvidenceBundlePublicationResultV5,
        preset: ExecutionPresetRevisionV2,
        idempotency_key: str,
    ) -> PreparedItemSimilarity | ReferenceItemStartPending: ...
