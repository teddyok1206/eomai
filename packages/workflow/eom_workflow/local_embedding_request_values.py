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


def validate_local_embedding_request_control_values(
    *,
    source_plan: ArtifactMemberPointer,
    source_plan_schema_ref: str,
    native_execution_policy: ArtifactMemberPointer,
    policy_schema_ref: str,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    namespace_space_sha256: str,
    space: EmbeddingSpace,
    resource_profile: LocalEmbeddingResourceProfile,
) -> None:
    """Shared value closure; concrete wire parsers choose their fixed schema families."""
    for pointer, member, schema in (
        (source_plan, "source-plan.json", source_plan_schema_ref),
        (native_execution_policy, "policy.json", policy_schema_ref),
    ):
        if (
            pointer.member_path != member
            or pointer.schema_ref != schema
            or pointer.media_type != "application/json"
        ):
            raise ValueError("native request control pointer differs")
    if (
        graph_snapshot.manifest_sha256 != graph_snapshot.manifest_artifact.sha256
        or namespace_space_sha256 != space.space_sha256
        or space.purpose != "DOCUMENT"
        or resource_profile.device != space.runtime.device
    ):
        raise ValueError("native request Graph, space or device pins differ")


def validate_local_embedding_request_hash(
    value: NativeEmbeddingContract, expected_sha256: str
) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > 64 * 1024:
        raise ValueError("native request exceeds its envelope bound")
    if expected_sha256 != content_sha256(value.model_dump(mode="json", exclude={"request_sha256"})):
        raise ValueError("native request canonical hash differs")


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
        validate_local_embedding_request_control_values(
            source_plan=self.source_plan,
            source_plan_schema_ref=LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
            native_execution_policy=self.native_execution_policy,
            policy_schema_ref=self._policy_schema_ref,
            graph_snapshot=self.graph_snapshot,
            namespace_space_sha256=self.namespace.space_sha256,
            space=self.space,
            resource_profile=self.resource_profile,
        )
        validate_local_embedding_request_hash(self, self.request_sha256)
        return self


class LocalEmbeddingServiceWorkflowRequest(LocalEmbeddingWorkflowRequestBody):
    """Explicit1.2 service-only intent; execution still requires the actual owner."""

    _policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF
    schema_version: Literal["local-embedding-workflow-request/1.2"] = (
        "local-embedding-workflow-request/1.2"
    )
    actor_context: LocalEmbeddingServiceAudit
