"""Additive request 1.1 audit and exact control-reference closure, without grants."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from eom_operator_identity.contracts import OperatorId
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingExecutablePolicy,
    LocalEmbeddingExecutionPolicy,
    LocalEmbeddingResourceProfile,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_executable_policy,
)
from eom_workflow.local_embedding_source_plan import (
    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_REQUEST_V11_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/1.1"
)
LOCAL_EMBEDDING_SERVICE_REQUEST_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/1.2"
)
LOCAL_INDEXING_WORKFLOW_ACTOR_TYPE: Literal["local_indexing_service"] = "local_indexing_service"


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


class _LocalEmbeddingWorkflowRequestBody(NativeEmbeddingContract):
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


class LocalEmbeddingWorkflowRequestV11(_LocalEmbeddingWorkflowRequestBody):
    """Original request: service branch stays audit-only and non-executable."""

    schema_version: Literal["local-embedding-workflow-request/1.1"] = (
        "local-embedding-workflow-request/1.1"
    )
    actor_context: LocalEmbeddingActorAudit


class LocalEmbeddingServiceWorkflowRequest(_LocalEmbeddingWorkflowRequestBody):
    """Explicit1.2 service-only intent; execution still requires the actual owner."""

    _policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF
    schema_version: Literal["local-embedding-workflow-request/1.2"] = (
        "local-embedding-workflow-request/1.2"
    )
    actor_context: LocalEmbeddingServiceAudit


type LocalEmbeddingExecutableRequest = (
    LocalEmbeddingWorkflowRequestV11 | LocalEmbeddingServiceWorkflowRequest
)


def parse_local_embedding_workflow_request_v11(value: object) -> LocalEmbeddingWorkflowRequestV11:
    validate_local_embedding_admission_message("request", value)
    try:
        return LocalEmbeddingWorkflowRequestV11.model_validate(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def require_local_embedding_operator_seed(
    request: LocalEmbeddingWorkflowRequestV11,
) -> LocalEmbeddingOperatorAudit:
    """Deny future service branch; operator audit still requires real owner authentication."""
    request = LocalEmbeddingWorkflowRequestV11.model_validate(request)
    request = parse_local_embedding_workflow_request_v11(request.model_dump(mode="json"))
    if not isinstance(request.actor_context, LocalEmbeddingOperatorAudit):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_SERVICE_UNAVAILABLE")
    return request.actor_context


def parse_local_embedding_service_workflow_request(
    value: object,
) -> LocalEmbeddingServiceWorkflowRequest:
    validate_local_embedding_admission_message("service-request", value)
    try:
        return LocalEmbeddingServiceWorkflowRequest.model_validate(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_executable_request(value: object) -> LocalEmbeddingExecutableRequest:
    """Executable message dispatch, preserving request1.1's audit-only service denial."""
    try:
        if isinstance(
            value, (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest)
        ):
            value = type(value).model_validate(value).model_dump(mode="json")
        if isinstance(value, dict):
            if value.get("schema_version") == "local-embedding-workflow-request/1.1":
                request = parse_local_embedding_workflow_request_v11(value)
                require_local_embedding_operator_seed(request)
                return request
            if value.get("schema_version") == "local-embedding-workflow-request/1.2":
                return parse_local_embedding_service_workflow_request(value)
    except LocalEmbeddingAdmissionContractError:
        raise
    except (ValueError, TypeError):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None
    raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def local_embedding_request_actor(
    request: LocalEmbeddingExecutableRequest,
) -> tuple[Literal["human", "local_indexing_service"], str]:
    """Closed Workflow audit pair only, never authentication or authority."""
    checked = parse_local_embedding_executable_request(request)
    if isinstance(checked, LocalEmbeddingServiceWorkflowRequest):
        return LOCAL_INDEXING_WORKFLOW_ACTOR_TYPE, checked.actor_context.service_id
    return "human", require_local_embedding_operator_seed(checked).operator_id


def local_embedding_request_service(
    request: LocalEmbeddingServiceWorkflowRequest,
) -> LocalIndexingServiceReference:
    audit = parse_local_embedding_service_workflow_request(
        LocalEmbeddingServiceWorkflowRequest.model_validate(request).model_dump(mode="json")
    ).actor_context
    return LocalIndexingServiceReference(
        service_id=audit.service_id,
        service_revision_id=audit.service_revision_id,
        service_identity_sha256=audit.service_identity_sha256,
    )


def validate_local_embedding_request_references(
    request: LocalEmbeddingExecutableRequest,
    plan: LocalEmbeddingSourcePlan,
    policy: LocalEmbeddingExecutablePolicy,
) -> None:
    """Exact pure control closure; no lookup, released-policy claim or source authorization."""
    request = parse_local_embedding_executable_request(request)
    plan = LocalEmbeddingSourcePlan.model_validate(plan)
    plan = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
    policy = parse_local_embedding_executable_policy(policy)
    if isinstance(request, LocalEmbeddingServiceWorkflowRequest):
        if not isinstance(
            policy, LocalEmbeddingServiceExecutionPolicy
        ) or policy.service != local_embedding_request_service(request):
            raise ValueError("native service request requires its exact service-only policy")
    elif not isinstance(policy, LocalEmbeddingExecutionPolicy):
        raise ValueError("native operator request cannot use service execution policy")
    common = (
        "corpus_id",
        "graph_snapshot",
        "access_policy_revision_id",
        "access_policy_sha256",
        "namespace",
        "space",
    )
    if (
        any(getattr(request, field) != getattr(plan, field) for field in common)
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
        raise ValueError("native request control references differ from exact plan or policy")
