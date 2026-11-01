"""Private lifecycle2 fixed graph and text-free receipt for common numerical QUERY2."""

from typing import Final, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatPublicQueryExecutionPointer
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_workflow.models import JobId, StepRunId, TerminalStep, WorkflowId, WorkflowLimits
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_publication_v2 import validate_private_chat_public_query_launch
from eom_workflow.private_chat_query_workflow import (
    MAX_PRIVATE_CHAT_QUERY_OUTPUT_BYTES,
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowDefinition,
    PrivateChatQueryWorkflowReceipt,
)
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message

PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_PROTOCOL: Final = "private-chat-query/2.0"
PRIVATE_CHAT_PUBLIC_QUERY_RESULT_SCHEMA: Final = "embedding-reference-query-result@2.0"
PRIVATE_CHAT_PUBLIC_QUERY_RECEIPT_REF: Final = (
    "eom://schemas/workflow/private-chat-query-workflow-receipt/2.0"
)


class _PrivateRunnerV2Value(NativeEmbeddingContract):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-runner-v2", document)
        return document


class PrivateChatPublicQueryStep(NativeEmbeddingContract):
    key: Literal["encode_private_chat_query"] = "encode_private_chat_query"
    type: Literal["application"] = "application"
    operation: Literal["BUILD_PRIVATE_CHAT_QUERY_EMBEDDINGS"] = (
        "BUILD_PRIVATE_CHAT_QUERY_EMBEDDINGS"
    )
    result_schema: Literal["embedding-reference-query-result@2.0"] = (
        PRIVATE_CHAT_PUBLIC_QUERY_RESULT_SCHEMA
    )
    on_success: Literal["complete"] = "complete"


class PrivateChatQueryWorkflowDefinitionV2(_PrivateRunnerV2Value):
    schema_version: Literal["1.3"] = "1.3"
    definition_key: Literal["local-embedding-private-chat-query"] = (
        "local-embedding-private-chat-query"
    )
    definition_version: Literal["2.0.0"] = "2.0.0"
    start_step: Literal["encode_private_chat_query"] = "encode_private_chat_query"
    limits: WorkflowLimits
    steps: tuple[PrivateChatPublicQueryStep, TerminalStep]


class PrivateChatQueryWorkflowReceiptV2(_PrivateRunnerV2Value):
    schema_version: Literal["private-chat-query-workflow-receipt/2.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_id: WorkflowId
    workflow_definition_sha256: Sha256
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256
    origin_sha256: Sha256
    step_run_id: StepRunId
    step_key: Literal["encode_private_chat_query"]
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    query_artifact_owner_job_id: JobId
    native_launch_job_id: JobId
    launch_association_sha256: Sha256
    execution_result_schema: Literal["embedding-reference-query-result@2.0"]
    execution_record: ArtifactMemberPointer
    query_execution: PrivateChatPublicQueryExecutionPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile_sha256: Sha256
    published_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_members(self) -> Self:
        members = (
            self.execution_record,
            self.query_execution.result_member,
            self.shard,
            self.binary,
        )
        if (
            self.query_execution.job_id != self.native_launch_job_id
            or len(
                {
                    self.receipt_owner_job_id,
                    self.query_artifact_owner_job_id,
                    self.native_launch_job_id,
                }
            )
            != 3
            or len({(member.artifact_id, member.artifact_revision_id) for member in members}) != 1
            or self.receipt_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_INVALID")
        return self


class PrivateChatQueryStepOutputV2(_PrivateRunnerV2Value):
    schema_version: Literal["private-chat-query-step-output/2.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_private_chat_query"]
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["embedding-reference-query-result@2.0"]
    receipt_schema: Literal["eom://schemas/workflow/private-chat-query-workflow-receipt/2.0"]
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="after")
    def exact_output(self) -> Self:
        if len(
            canonical_json_bytes(self)
        ) > MAX_PRIVATE_CHAT_QUERY_OUTPUT_BYTES or self.output_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"output_sha256"})
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_OUTPUT_INVALID")
        return self


def validate_private_chat_public_query_definition(
    definition: PrivateChatQueryWorkflowDefinitionV2,
    request: PrivateChatQueryWorkflowRequestV2,
) -> None:
    definition = PrivateChatQueryWorkflowDefinitionV2.model_validate(
        raw_similarity_contract_value(definition)
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        raw_similarity_contract_value(request)
    )
    if request.workflow_definition_sha256 != sha256_bytes(canonical_json_bytes(definition)):
        raise ValueError("PRIVATE_CHAT_QUERY_DEFINITION_MISMATCH")


def validate_private_chat_public_query_workflow_receipt(
    receipt: PrivateChatQueryWorkflowReceiptV2,
    request: PrivateChatQueryWorkflowRequestV2,
    policy: PrivateChatQueryExecutionPolicyV2,
    bundle: EmbeddingRuntimeBundle,
    launch: PrivateChatQueryLaunchAssociation,
    native: PublicSolutionQueryInput,
    result: PublicSolutionQueryResult,
    *,
    origin: ChatPrivateQueryOrigin,
    workflow_id: str,
    step_run_id: str,
    query_artifact_owner_job_id: str,
    receipt_owner_job_id: str,
) -> None:
    """Supplied closure only; actual owner, current source, producer and lifecycle stay external."""
    try:
        receipt = PrivateChatQueryWorkflowReceiptV2.model_validate(
            raw_similarity_contract_value(receipt)
        )
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        record = validate_private_chat_public_query_launch(launch, request, policy, bundle, native)
        request, launch = record.workflow_request, record.launch
        native = PublicSolutionQueryInput.model_validate(raw_similarity_contract_value(native))
        result = PublicSolutionQueryResult.model_validate(raw_similarity_contract_value(result))
        validate_public_solution_query_result(native, result)
        expected = (
            TypeAdapter(WorkflowId).validate_python(workflow_id),
            TypeAdapter(StepRunId).validate_python(step_run_id),
            TypeAdapter(JobId).validate_python(query_artifact_owner_job_id),
            TypeAdapter(JobId).validate_python(receipt_owner_job_id),
        )
        execution = receipt.query_execution
        if (
            (
                receipt.workflow_id,
                receipt.step_run_id,
                receipt.query_artifact_owner_job_id,
                receipt.receipt_owner_job_id,
            )
            != expected
            or (launch.workflow_id, launch.step_run_id) != expected[:2]
            or receipt.workflow_definition_sha256 != request.workflow_definition_sha256
            or receipt.workflow_request_sha256 != request.request_sha256
            or receipt.context_request_sha256 != request.context_request.request_sha256
            or receipt.origin_sha256 != origin.origin_sha256
            or origin.actor_id != request.operator_audit.operator_id
            or origin.basis != request.context_request.query_basis
            or receipt.native_launch_job_id != native.job_id
            or receipt.launch_association_sha256 != launch.association_sha256
            or receipt.runtime_bundle != request.runtime_bundle
            or receipt.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
            or execution.query_request_id != native.query_request_id
            or execution.request_sha256 != native.request_sha256
            or execution.input_set_sha256 != native.input_set_sha256
            or execution.basis_sha256 != request.context_request.query_basis.basis_sha256
            or execution.result_sha256 != result.result_sha256
            or receipt.execution_record.sha256 != sha256_bytes(canonical_json_bytes(record))
            or execution.result_member.sha256 != sha256_bytes(canonical_json_bytes(result))
            or receipt.shard.sha256 != sha256_bytes(canonical_json_bytes(result.shard))
            or receipt.binary.sha256 != result.shard.binary.sha256
            or receipt.published_at < launch.launched_at
        ):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_PROVENANCE_INVALID") from None


def validate_private_chat_public_query_step_output(
    output: PrivateChatQueryStepOutputV2,
    receipt: PrivateChatQueryWorkflowReceiptV2,
) -> None:
    output = PrivateChatQueryStepOutputV2.model_validate(raw_similarity_contract_value(output))
    receipt = PrivateChatQueryWorkflowReceiptV2.model_validate(
        raw_similarity_contract_value(receipt)
    )
    if (
        any(
            getattr(output, field) != getattr(receipt, field)
            for field in (
                "workflow_id",
                "step_run_id",
                "step_key",
                "attempt",
                "receipt_owner_job_id",
                "execution_result_schema",
                "receipt_sha256",
            )
        )
        or output.receipt.sha256 != sha256_bytes(canonical_json_bytes(receipt))
        or output.receipt.artifact_id == receipt.execution_record.artifact_id
        or output.receipt.artifact_revision_id == receipt.execution_record.artifact_revision_id
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_OUTPUT_PROVENANCE_INVALID")


type SupportedPrivateChatQueryWorkflowDefinition = (
    PrivateChatQueryWorkflowDefinition | PrivateChatQueryWorkflowDefinitionV2
)
type SupportedPrivateChatQueryWorkflowReceipt = (
    PrivateChatQueryWorkflowReceipt | PrivateChatQueryWorkflowReceiptV2
)
type SupportedPrivateChatQueryStepOutput = PrivateChatQueryStepOutput | PrivateChatQueryStepOutputV2


def parse_supported_private_chat_query_workflow_definition(
    value: object,
) -> SupportedPrivateChatQueryWorkflowDefinition:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("definition_version") == "2.0.0":
        return PrivateChatQueryWorkflowDefinitionV2.model_validate(document)
    return PrivateChatQueryWorkflowDefinition.model_validate(document)


def parse_supported_private_chat_query_workflow_receipt(
    value: object,
) -> SupportedPrivateChatQueryWorkflowReceipt:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "private-chat-query-workflow-receipt/2.0"
    ):
        return PrivateChatQueryWorkflowReceiptV2.model_validate(document)
    return PrivateChatQueryWorkflowReceipt.model_validate(document)


def parse_supported_private_chat_query_step_output(
    value: object,
) -> SupportedPrivateChatQueryStepOutput:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "private-chat-query-step-output/2.0"
    ):
        return PrivateChatQueryStepOutputV2.model_validate(document)
    return PrivateChatQueryStepOutput.model_validate(document)
