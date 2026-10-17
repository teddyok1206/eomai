"""Private owned-question execution intent; validation never grants native authority."""

from __future__ import annotations

from typing import Final, Literal

from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import model_validator

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingResourceProfile,
    validate_query_runtime_bundle,
)
from eom_workflow.local_embedding_request import LocalEmbeddingOperatorAudit
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

PRIVATE_CHAT_QUERY_POLICY_REF: Final = (
    "eom://schemas/workflow/private-chat-query-execution-policy/1.0"
)


class _PrivateExecutionValue(NativeEmbeddingContract):
    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-execution", document)
        return document


class PrivateChatQueryWorkflowRequest(_PrivateExecutionValue):
    schema_version: Literal["private-chat-query-workflow-request/1.0"]
    request_name: Literal["PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_definition_key: Literal["local-embedding-private-chat-query"]
    workflow_definition_version: Literal["1.0.0"]
    workflow_definition_sha256: Sha256
    operator_audit: LocalEmbeddingOperatorAudit
    context_request: PrivateChatSimilarityRequest
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_private_intent(self) -> PrivateChatQueryWorkflowRequest:
        selected = self.context_request.views[0]
        if selected.index is None or (
            selected.index.spaces.query.runtime.device != self.resource_profile.device
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("private QUERY request/index/resource closure differs")
        return self


class PrivateChatQueryExecutionPolicy(_PrivateExecutionValue):
    schema_version: Literal["private-chat-query-execution-policy/1.0"]
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
    def exact_private_policy(self) -> PrivateChatQueryExecutionPolicy:
        if (
            self.spaces.query.runtime.device != self.resource_profile.device
            or self.policy_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        ):
            raise ValueError("private QUERY policy/resource closure differs")
        return self


def validate_private_chat_query_request_references(
    request: PrivateChatQueryWorkflowRequest,
    policy: PrivateChatQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
) -> tuple[PrivateChatQueryWorkflowRequest, PrivateChatQueryExecutionPolicy]:
    """Resolve supplied immutable values only; current source/session checks stay with owners."""
    request = PrivateChatQueryWorkflowRequest.model_validate(raw_similarity_contract_value(request))
    policy = PrivateChatQueryExecutionPolicy.model_validate(raw_similarity_contract_value(policy))
    validate_query_runtime_bundle(
        policy.spaces, policy.runtime_bundle, policy.resource_profile, bundle
    )
    selected = request.context_request.views[0]
    if selected.index is None or (
        request.native_execution_policy_sha256 != policy.policy_sha256
        or request.native_execution_policy.sha256 != sha256_bytes(canonical_json_bytes(policy))
        or request.workflow_definition_sha256 != policy.workflow_definition_sha256
        or request.runtime_bundle != policy.runtime_bundle
        or request.resource_profile != policy.resource_profile
        or selected.index.spaces != policy.spaces
    ):
        raise ValueError("private QUERY request/control/bundle closure differs")
    return request, policy


def validate_private_chat_query_execution_input(
    request: PrivateChatQueryWorkflowRequest,
    policy: PrivateChatQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
    native: EmbeddingPrivateChatQueryInput,
) -> EmbeddingPrivateChatQueryInput:
    """Bind the exact owned question, parent, DOCUMENT recipe and selected QUERY recipe."""
    request, policy = validate_private_chat_query_request_references(request, policy, bundle)
    try:
        native = EmbeddingPrivateChatQueryInput.model_validate(
            raw_similarity_contract_value(native)
        )
    except (ValueError, TypeError, SchemaError):
        # JSON Schema errors can include the entire private question in their
        # default representation. Never expose that through an owner error.
        raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_INPUT_INVALID") from None
    selected = request.context_request.views[0]
    assert selected.index is not None
    if (
        native.context_request_sha256 != request.context_request.request_sha256
        or native.basis != request.context_request.query_basis
        or native.spaces != policy.spaces
        or native.document_recipe != selected.recipe
        or native.row.encoding.storage_partition != selected.index.storage_partition
        or native.batch_size != request.resource_profile.batch_size
        or native.threads != request.resource_profile.threads
    ):
        raise ValueError("private QUERY native input differs from exact execution intent")
    return native
