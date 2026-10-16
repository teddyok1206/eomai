"""Additive request 1.1 audit and exact control-reference closure, without grants."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingExecutablePolicy,
    LocalEmbeddingExecutionPolicy,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_executable_policy,
)
from eom_workflow.local_embedding_index_refresh import (
    LocalEmbeddingIndexRefreshRequest,
    parse_index_refresh_request,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingActorAudit as LocalEmbeddingActorAudit,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingOperatorAudit as LocalEmbeddingOperatorAudit,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingServiceAudit as LocalEmbeddingServiceAudit,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingServiceWorkflowRequest as LocalEmbeddingServiceWorkflowRequest,
)
from eom_workflow.local_embedding_request_values import (
    LocalEmbeddingWorkflowRequestBody,
)
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_REQUEST_V11_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/1.1"
)
LOCAL_EMBEDDING_SERVICE_REQUEST_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/1.2"
)
LOCAL_INDEXING_WORKFLOW_ACTOR_TYPE: Literal["local_indexing_service"] = "local_indexing_service"


class LocalEmbeddingWorkflowRequestV11(LocalEmbeddingWorkflowRequestBody):
    """Original request: service branch stays audit-only and non-executable."""

    schema_version: Literal["local-embedding-workflow-request/1.1"] = (
        "local-embedding-workflow-request/1.1"
    )
    actor_context: LocalEmbeddingActorAudit


type LocalEmbeddingExecutableRequest = (
    LocalEmbeddingWorkflowRequestV11
    | LocalEmbeddingServiceWorkflowRequest
    | LocalEmbeddingIndexRefreshRequest
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
            if value.get("schema_version") == "local-embedding-workflow-request/1.3":
                return parse_index_refresh_request(value)
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
    checked = parse_local_embedding_executable_request(request)
    if not isinstance(checked, LocalEmbeddingServiceWorkflowRequest):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_SERVICE_UNAVAILABLE")
    audit = checked.actor_context
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
