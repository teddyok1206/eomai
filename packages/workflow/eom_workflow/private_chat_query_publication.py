"""Private QUERY launch provenance and text-free reconstruction records, not authority."""

from __future__ import annotations

from typing import Final, Literal

from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    validate_private_chat_query_execution_input,
)
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

PRIVATE_CHAT_QUERY_RECORD_REF: Final = (
    "eom://schemas/workflow/private-chat-query-execution-record/1.0"
)


class _PrivatePublicationValue(NativeEmbeddingContract):
    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-publication", document)
        return document


class PrivateChatQueryLaunchAssociation(_PrivatePublicationValue):
    schema_version: Literal["private-chat-query-launch-association/1.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_private_chat_query"]
    attempt: int = Field(ge=1, le=1, strict=True)
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256
    basis_sha256: Sha256
    native_launch_job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    query_request_sha256: Sha256
    query_input_set_sha256: Sha256
    recipe_sha256: Sha256
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile_sha256: Sha256
    original_command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    original_command_generation: int = Field(ge=1, le=2**31 - 1, strict=True)
    launched_at: UtcDatetime
    association_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> PrivateChatQueryLaunchAssociation:
        if self.association_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"association_sha256"})
        ):
            raise ValueError("private QUERY launch hash differs")
        return self


class PrivateChatQueryExecutionRecord(_PrivatePublicationValue):
    schema_version: Literal["private-chat-query-execution-record/1.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_request: PrivateChatQueryWorkflowRequest
    launch: PrivateChatQueryLaunchAssociation
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_record(self) -> PrivateChatQueryExecutionRecord:
        request, launch = self.workflow_request, self.launch
        if (
            launch.workflow_request_sha256 != request.request_sha256
            or launch.context_request_sha256 != request.context_request.request_sha256
            or launch.basis_sha256 != request.context_request.query_basis.basis_sha256
            or launch.runtime_bundle != request.runtime_bundle
            or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
            or launch.recipe_sha256 != request.context_request.views[0].recipe.recipe_sha256
            or self.record_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        ):
            raise ValueError("private QUERY execution record closure differs")
        return self


def validate_private_chat_query_launch(
    launch: PrivateChatQueryLaunchAssociation,
    request: PrivateChatQueryWorkflowRequest,
    policy: PrivateChatQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
    native: EmbeddingPrivateChatQueryInput,
) -> PrivateChatQueryExecutionRecord:
    """Seal supplied provenance; actual source/session/unit observations are external."""
    launch = PrivateChatQueryLaunchAssociation.model_validate(raw_similarity_contract_value(launch))
    request = PrivateChatQueryWorkflowRequest.model_validate(raw_similarity_contract_value(request))
    policy = PrivateChatQueryExecutionPolicy.model_validate(raw_similarity_contract_value(policy))
    native = validate_private_chat_query_execution_input(request, policy, bundle, native)
    if (
        launch.native_launch_job_id != native.job_id
        or launch.query_request_id != native.query_request_id
        or launch.query_request_sha256 != native.request_sha256
        or launch.query_input_set_sha256 != native.input_set_sha256
        or launch.launched_at < policy.created_at
    ):
        raise ValueError("private QUERY launch differs from exact native input")
    body = {
        "schema_version": "private-chat-query-execution-record/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
        "workflow_request": request.model_dump(mode="json"),
        "launch": launch.model_dump(mode="json"),
    }
    return PrivateChatQueryExecutionRecord.model_validate(
        body | {"record_sha256": content_sha256(body)}
    )
