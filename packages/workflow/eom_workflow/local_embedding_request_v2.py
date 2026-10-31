"""Explicit mixed service request2; parsing never admits a service or a source."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingExecutablePolicy,
    LocalEmbeddingResourceProfile,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_service_execution_policy,
)
from eom_workflow.local_embedding_request import (
    LocalEmbeddingExecutableRequest,
    LocalEmbeddingServiceWorkflowRequest,
    LocalEmbeddingWorkflowRequestV11,
    local_embedding_request_actor,
    parse_local_embedding_executable_request,
    validate_local_embedding_request_references,
)
from eom_workflow.local_embedding_request_v3 import (
    LocalEmbeddingWorkflowRequestV3,
    parse_local_embedding_workflow_request_v3,
    validate_local_embedding_request_references_v3,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingServiceAudit,
    validate_local_embedding_request_control_values,
    validate_local_embedding_request_hash,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.local_embedding_source_plan_v3 import LocalEmbeddingSourcePlanV3
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_REQUEST_V2_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/2.0"
)


class LocalEmbeddingWorkflowRequestV2(NativeEmbeddingContract):
    """Independent mixed service frame; not an instance of a released request1."""

    schema_version: Literal["local-embedding-workflow-request/2.0"] = (
        "local-embedding-workflow-request/2.0"
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
    namespace: MixedEmbeddingIndexNamespace
    space: EmbeddingSpace
    runtime_bundle: EmbeddingRuntimeBundlePointer
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    resource_profile: LocalEmbeddingResourceProfile
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> LocalEmbeddingWorkflowRequestV2:
        validate_local_embedding_request_control_values(
            source_plan=self.source_plan,
            source_plan_schema_ref=LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
            native_execution_policy=self.native_execution_policy,
            policy_schema_ref=LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
            graph_snapshot=self.graph_snapshot,
            namespace_space_sha256=self.namespace.space_sha256,
            space=self.space,
            resource_profile=self.resource_profile,
        )
        validate_local_embedding_request_hash(self, self.request_sha256)
        return self


def parse_local_embedding_workflow_request_v2(value: object) -> LocalEmbeddingWorkflowRequestV2:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("mixed-request", document)
        return LocalEmbeddingWorkflowRequestV2.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


type SupportedLocalEmbeddingRequest = (
    LocalEmbeddingExecutableRequest
    | LocalEmbeddingWorkflowRequestV2
    | LocalEmbeddingWorkflowRequestV3
)

# Runtime classification is separate from schema/source/actor admission. A PEP 695
# alias cannot be passed to isinstance; keep the closed class set at this dispatch.
LOCAL_EMBEDDING_REQUEST_TYPES = (
    LocalEmbeddingWorkflowRequestV11,
    LocalEmbeddingServiceWorkflowRequest,
    LocalEmbeddingWorkflowRequestV2,
    LocalEmbeddingWorkflowRequestV3,
)


def parse_supported_local_embedding_request(value: object) -> SupportedLocalEmbeddingRequest:
    """One closed request family dispatch; source/service/runtime authority is separate."""
    try:
        document = raw_similarity_contract_value(value)
        if (
            isinstance(document, dict)
            and document.get("schema_version") == "local-embedding-workflow-request/3.0"
        ):
            return parse_local_embedding_workflow_request_v3(document)
        if (
            isinstance(document, dict)
            and document.get("schema_version") == "local-embedding-workflow-request/2.0"
        ):
            return parse_local_embedding_workflow_request_v2(document)
        return parse_local_embedding_executable_request(document)
    except LocalEmbeddingAdmissionContractError:
        raise
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def supported_local_embedding_request_actor(
    request: SupportedLocalEmbeddingRequest,
) -> tuple[Literal["human", "local_indexing_service"], str]:
    checked = parse_supported_local_embedding_request(request)
    if isinstance(checked, (LocalEmbeddingWorkflowRequestV2, LocalEmbeddingWorkflowRequestV3)):
        return "local_indexing_service", checked.actor_context.service_id
    return local_embedding_request_actor(checked)


def local_embedding_request_service_v2(
    request: LocalEmbeddingWorkflowRequestV2,
) -> LocalIndexingServiceReference:
    audit = parse_local_embedding_workflow_request_v2(request).actor_context
    return LocalIndexingServiceReference(
        service_id=audit.service_id,
        service_revision_id=audit.service_revision_id,
        service_identity_sha256=audit.service_identity_sha256,
    )


def supported_local_embedding_request_service(
    request: SupportedLocalEmbeddingRequest,
) -> LocalIndexingServiceReference:
    """Service identity value after family validation, never current runtime authority."""
    checked = parse_supported_local_embedding_request(request)
    if isinstance(checked, (LocalEmbeddingWorkflowRequestV2, LocalEmbeddingWorkflowRequestV3)):
        audit = checked.actor_context
        return LocalIndexingServiceReference(
            service_id=audit.service_id,
            service_revision_id=audit.service_revision_id,
            service_identity_sha256=audit.service_identity_sha256,
        )
    if isinstance(checked, LocalEmbeddingServiceWorkflowRequest):
        from eom_workflow.local_embedding_request import local_embedding_request_service

        return local_embedding_request_service(checked)
    raise ValueError("LOCAL_EMBEDDING_SERVICE_REQUEST_REQUIRED")


def validate_local_embedding_request_references_v2(
    request: LocalEmbeddingWorkflowRequestV2,
    plan: LocalEmbeddingSourcePlanV2,
    policy: LocalEmbeddingServiceExecutionPolicy,
) -> None:
    """Same genuine service/numerical policy type, but new immutable definition/plan."""
    request = parse_local_embedding_workflow_request_v2(request)
    plan = parse_local_embedding_source_plan_v2(plan)
    policy = parse_local_embedding_service_execution_policy(raw_similarity_contract_value(policy))
    if (
        policy.service != local_embedding_request_service_v2(request)
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
        raise ValueError("mixed native request differs from exact service, plan or policy")


def validate_supported_local_embedding_request_references(
    request: SupportedLocalEmbeddingRequest,
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2 | LocalEmbeddingSourcePlanV3,
    policy: LocalEmbeddingExecutablePolicy,
) -> None:
    """Exact family closure only; current source and service authority stay upstream."""
    request = parse_supported_local_embedding_request(request)
    if (
        isinstance(request, LocalEmbeddingWorkflowRequestV3)
        and isinstance(plan, LocalEmbeddingSourcePlanV3)
        and isinstance(policy, LocalEmbeddingServiceExecutionPolicy)
    ):
        validate_local_embedding_request_references_v3(request, plan, policy)
    elif (
        isinstance(request, LocalEmbeddingWorkflowRequestV2)
        and isinstance(plan, LocalEmbeddingSourcePlanV2)
        and isinstance(policy, LocalEmbeddingServiceExecutionPolicy)
    ):
        validate_local_embedding_request_references_v2(request, plan, policy)
    elif not isinstance(
        request, (LocalEmbeddingWorkflowRequestV2, LocalEmbeddingWorkflowRequestV3)
    ) and isinstance(plan, LocalEmbeddingSourcePlan):
        validate_local_embedding_request_references(request, plan, policy)
    else:
        raise ValueError("LOCAL_EMBEDDING_REQUEST_FAMILY_MISMATCH")
