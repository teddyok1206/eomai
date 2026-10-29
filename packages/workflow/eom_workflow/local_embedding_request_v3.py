"""Public-report request3 over the unchanged fixed INDEX2 execution graph."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingResourceProfile,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_service_execution_policy,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingServiceAudit,
    validate_local_embedding_request_control_values,
    validate_local_embedding_request_hash,
)
from eom_workflow.local_embedding_source_plan_v3 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_REQUEST_V3_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/3.0"
)


class LocalEmbeddingWorkflowRequestV3(NativeEmbeddingContract):
    """Independent public-solution service frame; not an instance of a released request1."""

    schema_version: Literal["local-embedding-workflow-request/3.0"] = (
        "local-embedding-workflow-request/3.0"
    )
    request_name: Literal["LOCAL_EMBEDDING_WORKFLOW_REQUEST"] = "LOCAL_EMBEDDING_WORKFLOW_REQUEST"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_definition_key: Literal["local-embedding-index"] = "local-embedding-index"
    workflow_definition_version: Literal["2.0.0"] = "2.0.0"
    workflow_definition_sha256: Sha256
    actor_context: LocalEmbeddingServiceAudit
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: PublicSolutionIndexNamespace
    space: EmbeddingSpace
    runtime_bundle: EmbeddingRuntimeBundlePointer
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    resource_profile: LocalEmbeddingResourceProfile
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> LocalEmbeddingWorkflowRequestV3:
        validate_local_embedding_request_control_values(
            source_plan=self.source_plan,
            source_plan_schema_ref=LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
            native_execution_policy=self.native_execution_policy,
            policy_schema_ref=LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
            graph_snapshot=self.graph_snapshot,
            namespace_space_sha256=self.namespace.space_sha256,
            space=self.space,
            resource_profile=self.resource_profile,
        )
        validate_local_embedding_request_hash(self, self.request_sha256)
        return self


def parse_local_embedding_workflow_request_v3(value: object) -> LocalEmbeddingWorkflowRequestV3:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("public-request", document)
        return LocalEmbeddingWorkflowRequestV3.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_request_service_v3(
    request: LocalEmbeddingWorkflowRequestV3,
) -> LocalIndexingServiceReference:
    audit = parse_local_embedding_workflow_request_v3(request).actor_context
    return LocalIndexingServiceReference(
        service_id=audit.service_id,
        service_revision_id=audit.service_revision_id,
        service_identity_sha256=audit.service_identity_sha256,
    )


def validate_local_embedding_request_references_v3(
    request: LocalEmbeddingWorkflowRequestV3,
    plan: LocalEmbeddingSourcePlanV3,
    policy: LocalEmbeddingServiceExecutionPolicy,
) -> None:
    """Same genuine service/numerical policy type, but new immutable definition/plan."""
    request = parse_local_embedding_workflow_request_v3(request)
    plan = parse_local_embedding_source_plan_v3(plan)
    policy = parse_local_embedding_service_execution_policy(raw_similarity_contract_value(policy))
    if (
        len(plan.sources) > 1024
        or policy.service != local_embedding_request_service_v3(request)
        or any(
            getattr(request, field) != getattr(plan, field)
            for field in (
                "corpus_id",
                "graph_snapshot",
                "access_policy_revision_id",
                "access_policy_sha256",
                "namespace",
                "space",
            )
        )
        or request.source_plan_sha256 != plan.plan_sha256
        or request.source_plan.sha256
        != sha256_bytes(canonical_json_bytes(plan.model_dump(mode="json")))
        or request.native_execution_policy_sha256 != policy.policy_sha256
        or request.native_execution_policy.sha256
        != sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json")))
        or request.workflow_definition_sha256 != policy.workflow_definition_sha256
        or not any(
            profile.space == request.space
            and profile.runtime_bundle == request.runtime_bundle
            and profile.resource_profile == request.resource_profile
            for profile in policy.profiles
        )
    ):
        raise ValueError(
            "public-solution native request differs from exact service, plan or policy"
        )
