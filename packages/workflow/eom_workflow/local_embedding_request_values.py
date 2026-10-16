"""Immutable native request values shared by released and successor contracts."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity.contracts import OperatorId
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingResourceProfile,
)
from eom_workflow.local_embedding_source_plan import LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF
from eom_workflow.schemas import NativeEmbeddingContract


class LocalEmbeddingOperatorAudit(NativeEmbeddingContract):
    kind: Literal["OPERATOR"] = "OPERATOR"
    operator_id: OperatorId
    requester_permissions_sha256: Sha256


class LocalEmbeddingServiceAudit(NativeEmbeddingContract):
    """Service provenance only, never actual runtime identity or a current data grant."""

    kind: Literal["LOCAL_INDEXING_SERVICE"] = "LOCAL_INDEXING_SERVICE"
    service_id: str = Field(pattern=r"^localindexservice_[0-9a-f]{32}$")
    service_revision_id: str = Field(pattern=r"^localindexservicerev_[0-9a-f]{32}$")
    service_identity_sha256: Sha256
    service_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    service_policy_sha256: Sha256
    authorization_audit_sha256: Sha256


type LocalEmbeddingActorAudit = Annotated[
    LocalEmbeddingOperatorAudit | LocalEmbeddingServiceAudit, Field(discriminator="kind")
]


class LocalEmbeddingWorkflowRequestBody(NativeEmbeddingContract):
    """Original all-demand intent; a later owned launch never rewrites this snapshot."""

    _policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_POLICY_SCHEMA_REF
    request_name: Literal["LOCAL_EMBEDDING_WORKFLOW_REQUEST"] = "LOCAL_EMBEDDING_WORKFLOW_REQUEST"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_definition_key: Literal["local-embedding-index"] = "local-embedding-index"
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    workflow_definition_sha256: Sha256
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: EmbeddingIndexNamespace
    space: EmbeddingSpace
    runtime_bundle: EmbeddingRuntimeBundlePointer
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    resource_profile: LocalEmbeddingResourceProfile
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        for pointer, member, schema in (
            (self.source_plan, "source-plan.json", LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF),
            (self.native_execution_policy, "policy.json", self._policy_schema_ref),
        ):
            if (
                pointer.member_path != member
                or pointer.schema_ref != schema
                or pointer.media_type != "application/json"
            ):
                raise ValueError("native request control pointer differs")
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.namespace.space_sha256 != self.space.space_sha256
            or self.space.purpose != "DOCUMENT"
            or self.resource_profile.device != self.space.runtime.device
        ):
            raise ValueError("native request Graph, space or device pins differ")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > 64 * 1024:
            raise ValueError("native request exceeds its envelope bound")
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("native request canonical hash differs")
        return self


class LocalEmbeddingServiceWorkflowRequest(LocalEmbeddingWorkflowRequestBody):
    """Explicit1.2 service-only intent; execution still requires the actual owner."""

    _policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF
    schema_version: Literal["local-embedding-workflow-request/1.2"] = (
        "local-embedding-workflow-request/1.2"
    )
    actor_context: LocalEmbeddingServiceAudit
