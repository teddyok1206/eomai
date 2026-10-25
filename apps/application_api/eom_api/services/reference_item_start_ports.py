"""Operation-local reference preparation handoff, not source or execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts import EvidenceBundlePublicationResultV5
from eom_catalog_contracts.authoring_reference import AuthoringReferenceSelection
from eom_catalog_contracts.models import Sha256
from eom_operator_identity import ActorContext
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowId, WorkflowRequest
from eom_workflow_runner.item_similarity_preparation import PreparedItemSimilarity
from pydantic import TypeAdapter


@dataclass(frozen=True, slots=True)
class ReferenceItemStartPending:
    reference_query_workflow_id: str | None
    preparation: ArtifactMemberPointer | None = None
    parent_request_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.reference_query_workflow_id is not None:
            TypeAdapter(WorkflowId).validate_python(self.reference_query_workflow_id, strict=True)
        if (self.preparation is None) != (self.parent_request_sha256 is None) or (
            self.reference_query_workflow_id is None and self.preparation is None
        ):
            raise ValueError("reference pending requires an original preparation or Workflow")
        if self.parent_request_sha256 is not None:
            TypeAdapter(Sha256).validate_python(self.parent_request_sha256, strict=True)


@dataclass(frozen=True, slots=True)
class ReferenceItemSimilarityNotOffered:
    """Exact optional-absence observation, never success, authority or a QUERY receipt."""

    reason: Literal["REFERENCE_NOT_OFFERED", "INDEX_NOT_PREPARED"]
    workflow_request_sha256: str
    evidence_result_sha256: str

    def __post_init__(self) -> None:
        TypeAdapter(Literal["REFERENCE_NOT_OFFERED", "INDEX_NOT_PREPARED"]).validate_python(
            self.reason, strict=True
        )
        for digest in (self.workflow_request_sha256, self.evidence_result_sha256):
            TypeAdapter(Sha256).validate_python(digest, strict=True)


class AuthoringReferenceSelectionPort(Protocol):
    def select(
        self, actor_id: str, evidence: EvidenceBundlePublicationResultV5
    ) -> AuthoringReferenceSelection | None: ...


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
    ) -> PreparedItemSimilarity | ReferenceItemStartPending | ReferenceItemSimilarityNotOffered: ...
