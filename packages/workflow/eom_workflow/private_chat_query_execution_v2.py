"""Private context2 lifecycle intent around unchanged public numerical QUERY2.

Private source/turn ownership, policy and native admission stay distinct from
reference-query authority. Old request/policy1 remain valid only as their family.
"""

from __future__ import annotations

from typing import Final, Literal, Self

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.private_chat_query_basis import private_chat_query_text_sha256
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingResourceProfile,
    validate_query_runtime_bundle,
)
from eom_workflow.local_embedding_request import LocalEmbeddingOperatorAudit
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
    validate_private_chat_query_request_references,
)
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message

PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF: Final = (
    "eom://schemas/workflow/private-chat-query-execution-policy/2.0"
)
PRIVATE_CHAT_QUERY_REQUEST_VERSIONS: Final = (
    "private-chat-query-workflow-request/1.0",
    "private-chat-query-workflow-request/2.0",
)


class _PrivatePublicExecutionValue(NativeEmbeddingContract):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-public-execution", document)
        return document


class PrivateChatQueryWorkflowRequestV2(_PrivatePublicExecutionValue):
    schema_version: Literal["private-chat-query-workflow-request/2.0"]
    request_name: Literal["PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_definition_key: Literal["local-embedding-private-chat-query"]
    workflow_definition_version: Literal["2.0.0"]
    workflow_definition_sha256: Sha256
    operator_audit: LocalEmbeddingOperatorAudit
    context_request: PrivateChatSimilarityRequestV2
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        selected = self.context_request.views[0]
        if selected.index is None or (
            selected.index.spaces.query.runtime.device != self.resource_profile.device
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST_INVALID")
        return self


class PrivateChatQueryExecutionPolicyV2(_PrivatePublicExecutionValue):
    schema_version: Literal["private-chat-query-execution-policy/2.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    continuation_mode: Literal["OPERATOR_REQUEST_ONLY"]
    workflow_definition_sha256: Sha256
    spaces: ReferenceQuerySpaces
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    gpu_busy: Literal["WAIT"]
    created_at: UtcDatetime
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_policy(self) -> Self:
        if (
            self.spaces.query.runtime.device != self.resource_profile.device
            or self.policy_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_POLICY_INVALID")
        return self


type SupportedPrivateChatQueryWorkflowRequest = (
    PrivateChatQueryWorkflowRequest | PrivateChatQueryWorkflowRequestV2
)
type SupportedPrivateChatQueryExecutionPolicy = (
    PrivateChatQueryExecutionPolicy | PrivateChatQueryExecutionPolicyV2
)


def parse_supported_private_chat_query_workflow_request(
    value: object,
) -> SupportedPrivateChatQueryWorkflowRequest:
    try:
        document = raw_similarity_contract_value(value)
        if isinstance(document, dict) and document.get("schema_version") == (
            "private-chat-query-workflow-request/2.0"
        ):
            return PrivateChatQueryWorkflowRequestV2.model_validate(document)
        return parse_private_chat_query_workflow_request(document)
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST_INVALID") from None


def parse_supported_private_chat_query_execution_policy(
    value: object,
) -> SupportedPrivateChatQueryExecutionPolicy:
    try:
        document = raw_similarity_contract_value(value)
        if isinstance(document, dict) and document.get("schema_version") == (
            "private-chat-query-execution-policy/2.0"
        ):
            return PrivateChatQueryExecutionPolicyV2.model_validate(document)
        return PrivateChatQueryExecutionPolicy.model_validate(document)
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_POLICY_INVALID") from None


def validate_private_chat_public_query_request_references(
    request: PrivateChatQueryWorkflowRequestV2,
    policy: PrivateChatQueryExecutionPolicyV2,
    bundle: EmbeddingRuntimeBundle,
) -> tuple[PrivateChatQueryWorkflowRequestV2, PrivateChatQueryExecutionPolicyV2]:
    """Close private supplied pins; actual actor/source/unit verification is separate."""
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        raw_similarity_contract_value(request)
    )
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(raw_similarity_contract_value(policy))
    validate_query_runtime_bundle(
        policy.spaces, policy.runtime_bundle, policy.resource_profile, bundle
    )
    index = request.context_request.views[0].index
    if index is None or (
        request.native_execution_policy_sha256 != policy.policy_sha256
        or request.native_execution_policy.sha256 != sha256_bytes(canonical_json_bytes(policy))
        or request.workflow_definition_sha256 != policy.workflow_definition_sha256
        or request.runtime_bundle != policy.runtime_bundle
        or request.resource_profile != policy.resource_profile
        or index.spaces != policy.spaces
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_REQUEST_REFERENCES_INVALID")
    return request, policy


def validate_supported_private_chat_query_request_references(
    request: SupportedPrivateChatQueryWorkflowRequest,
    policy: SupportedPrivateChatQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
) -> tuple[SupportedPrivateChatQueryWorkflowRequest, SupportedPrivateChatQueryExecutionPolicy]:
    request = parse_supported_private_chat_query_workflow_request(request)
    policy = parse_supported_private_chat_query_execution_policy(policy)
    if isinstance(request, PrivateChatQueryWorkflowRequestV2) and isinstance(
        policy, PrivateChatQueryExecutionPolicyV2
    ):
        return validate_private_chat_public_query_request_references(request, policy, bundle)
    if isinstance(request, PrivateChatQueryWorkflowRequest) and isinstance(
        policy, PrivateChatQueryExecutionPolicy
    ):
        return validate_private_chat_query_request_references(request, policy, bundle)
    raise ValueError("PRIVATE_CHAT_QUERY_REQUEST_POLICY_FAMILY_MISMATCH")


def validate_private_chat_public_query_execution_input(
    request: PrivateChatQueryWorkflowRequestV2,
    policy: PrivateChatQueryExecutionPolicyV2,
    bundle: EmbeddingRuntimeBundle,
    native: PublicSolutionQueryInput,
) -> PublicSolutionQueryInput:
    """Same numerical QUERY2, privately bound to exact basis text/hash and parent."""
    try:
        request, policy = validate_private_chat_public_query_request_references(
            request, policy, bundle
        )
        native = PublicSolutionQueryInput.model_validate(raw_similarity_contract_value(native))
        selected = request.context_request.views[0]
        assert selected.index is not None
        if (
            native.context_request_sha256 != request.context_request.request_sha256
            or private_chat_query_text_sha256(native.rows[0].text)
            != request.context_request.query_basis.query_text_sha256
            or native.spaces != policy.spaces
            or native.recipe != selected.recipe
            or native.rows[0].encoding.storage_partition != selected.index.storage_partition
            or native.batch_size != request.resource_profile.batch_size
            or native.threads != request.resource_profile.threads
        ):
            raise ValueError()
        return native
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_INPUT_INVALID") from None
