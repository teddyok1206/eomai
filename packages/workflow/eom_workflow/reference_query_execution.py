"""Pointer-only QUERY intent/publication closure; source and native authority stay with owners."""

from __future__ import annotations

from typing import Final, Literal, Self, TypeAlias

from eom_catalog_contracts.embedding_reference_query import (
    EmbeddingReferenceQueryResult,
    ReferenceQueryExecutionPointer,
    ReferenceQuerySpaces,
    parse_embedding_reference_query_result,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    REFERENCE_QUERY_INPUT_V11_REF,
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_INPUT_REF,
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityRequest
from eom_catalog_contracts.similarity_context import SimilarityContextRequest
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityContextRequestV2,
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context_request,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingResourceProfile,
    validate_query_runtime_bundle,
)
from eom_workflow.local_embedding_request import LocalEmbeddingOperatorAudit
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    ReferenceQueryContractError,
    validate_reference_query_message,
    validate_reference_query_public_message,
    validate_reference_query_request_v2,
    validate_reference_query_request_v11,
)

REFERENCE_QUERY_POLICY_REF: Final = "eom://schemas/workflow/reference-query-execution-policy/1.0"
REFERENCE_QUERY_RECEIPT_REF: Final = "eom://schemas/workflow/reference-query-workflow-receipt/1.0"
PUBLIC_REFERENCE_QUERY_RECEIPT_REF: Final = (
    "eom://schemas/workflow/reference-query-workflow-receipt/2.0"
)
REFERENCE_QUERY_REQUEST_VERSIONS: Final = (
    "reference-query-workflow-request/1.0",
    "reference-query-workflow-request/1.1",
    "reference-query-workflow-request/2.0",
    "reference-query-workflow-request/3.0",
)
_BINARY_REF = "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"


type SupportedReferenceQueryContext = (
    SupportedSimilarityContextRequest | PublicSolutionSimilarityRequest
)


def parse_supported_reference_query_context(value: object) -> SupportedReferenceQueryContext:
    """Closed additive context dispatch; old Catalog parsers stay legacy-only."""
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("schema_version") == (
        "system-rag-similarity-request/3.0"
    ):
        return PublicSolutionSimilarityRequest.model_validate(document)
    return parse_supported_similarity_context_request(document)


def _hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("reference QUERY canonical hash differs")


def _member(
    value: ArtifactMemberPointer, path: str, schema: str, media: str = "application/json"
) -> None:
    if value.member_path != path or value.schema_ref != schema or value.media_type != media:
        raise ValueError("reference QUERY member closure differs")


def _validate_reference_query_context_controls(
    context: SupportedSimilarityContextRequest | PublicSolutionSimilarityRequest,
    resources: LocalEmbeddingResourceProfile,
    policy: ArtifactMemberPointer,
) -> None:
    _member(policy, "policy.json", REFERENCE_QUERY_POLICY_REF)
    indexes = tuple(view.index for view in context.views if view.index is not None)
    if (
        not indexes
        or any(index.spaces.query.runtime.device != resources.device for index in indexes)
        or len({view.recipe.recipe_sha256 for view in context.views}) != 1
    ):
        raise ValueError("reference QUERY context lacks a single pinned runtime/recipe")


class _ReferenceQueryRequestFields(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    request_name: Literal["REFERENCE_QUERY_WORKFLOW_REQUEST"] = "REFERENCE_QUERY_WORKFLOW_REQUEST"
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_definition_key: Literal["local-embedding-reference-query"] = (
        "local-embedding-reference-query"
    )
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    workflow_definition_sha256: Sha256
    operator_audit: LocalEmbeddingOperatorAudit
    context_request: SimilarityContextRequest
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        _validate_reference_query_context_controls(
            self.context_request, self.resource_profile, self.native_execution_policy
        )
        _hash(self, "request_sha256")
        return self


class ReferenceQueryWorkflowRequest(_ReferenceQueryRequestFields):
    schema_version: Literal["reference-query-workflow-request/1.0"] = (
        "reference-query-workflow-request/1.0"
    )

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("request", value)
        return raw_similarity_contract_value(value)


class ReferenceQueryWorkflowRequestV11(_ReferenceQueryRequestFields):
    schema_version: Literal["reference-query-workflow-request/1.1"] = (
        "reference-query-workflow-request/1.1"
    )

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_request_v11(value)
        return raw_similarity_contract_value(value)


class ReferenceQueryWorkflowRequestV2(FrozenModel):
    """Independent mixed metadata frame; never a subtype of a released request1."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-workflow-request/2.0"]
    request_name: Literal["REFERENCE_QUERY_WORKFLOW_REQUEST"]
    purpose: Literal["REFERENCE_QUERY"]
    workflow_definition_key: Literal["local-embedding-reference-query"]
    workflow_definition_version: Literal["1.0.0"]
    workflow_definition_sha256: Sha256
    operator_audit: LocalEmbeddingOperatorAudit
    context_request: SimilarityContextRequestV2
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_request_v2(value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_request(self) -> ReferenceQueryWorkflowRequestV2:
        _validate_reference_query_context_controls(
            self.context_request, self.resource_profile, self.native_execution_policy
        )
        _hash(self, "request_sha256")
        return self


class ReferenceQueryWorkflowRequestV3(FrozenModel):
    """Public solution request; distinct from released accepted-analysis frames."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-workflow-request/3.0"] = (
        "reference-query-workflow-request/3.0"
    )
    request_name: Literal["REFERENCE_QUERY_WORKFLOW_REQUEST"] = "REFERENCE_QUERY_WORKFLOW_REQUEST"
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_definition_key: Literal["local-embedding-reference-query"] = (
        "local-embedding-reference-query"
    )
    workflow_definition_version: Literal["2.0.0"] = "2.0.0"
    workflow_definition_sha256: Sha256
    operator_audit: LocalEmbeddingOperatorAudit
    context_request: PublicSolutionSimilarityRequest
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_public_message("request", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        _validate_reference_query_context_controls(
            self.context_request, self.resource_profile, self.native_execution_policy
        )
        _hash(self, "request_sha256")
        return self


# Keep a runtime union: the fixed Runner dispatch uses isinstance as well as typing.
# PEP695's TypeAliasType cannot serve that runtime boundary.
LegacyReferenceQueryWorkflowRequest: TypeAlias = (  # noqa: UP040 -- used by runtime isinstance
    ReferenceQueryWorkflowRequest
    | ReferenceQueryWorkflowRequestV11
    | ReferenceQueryWorkflowRequestV2
)
SupportedReferenceQueryWorkflowRequest: TypeAlias = (  # noqa: UP040 -- used by runtime isinstance
    LegacyReferenceQueryWorkflowRequest | ReferenceQueryWorkflowRequestV3
)
type SupportedReferenceQueryWorkflowIntent = SupportedReferenceQueryWorkflowRequest


class ReferenceQueryExecutionPolicy(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-execution-policy/1.0"] = (
        "reference-query-execution-policy/1.0"
    )
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    continuation_mode: Literal["OPERATOR_REQUEST_ONLY"] = "OPERATOR_REQUEST_ONLY"
    workflow_definition_sha256: Sha256
    spaces: ReferenceQuerySpaces
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile
    gpu_busy: Literal["WAIT"] = "WAIT"
    created_at: UtcDatetime
    policy_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("policy", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_policy(self) -> ReferenceQueryExecutionPolicy:
        if self.spaces.query.runtime.device != self.resource_profile.device:
            raise ValueError("reference QUERY policy device differs")
        _hash(self, "policy_sha256")
        return self


class ReferenceQueryLaunchAssociation(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-launch-association/1.0"] = (
        "reference-query-launch-association/1.0"
    )
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_reference_query"] = "encode_reference_query"
    attempt: int = Field(ge=1, le=1, strict=True)
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256
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

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("launch", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_launch(self) -> ReferenceQueryLaunchAssociation:
        _hash(self, "association_sha256")
        return self


class ReferenceQueryWorkflowReceipt(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-workflow-receipt/1.0"] = (
        "reference-query-workflow-receipt/1.0"
    )
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_id: WorkflowId
    workflow_definition_sha256: Sha256
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256
    step_run_id: StepRunId
    step_key: Literal["encode_reference_query"] = "encode_reference_query"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    query_artifact_owner_job_id: JobId
    native_launch_job_id: JobId
    launch_association_sha256: Sha256
    execution_result_schema: Literal["embedding-reference-query-result@1.0"] = (
        "embedding-reference-query-result@1.0"
    )
    query_input: ArtifactMemberPointer
    query_execution: ReferenceQueryExecutionPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile_sha256: Sha256
    published_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("receipt", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_receipt(self) -> ReferenceQueryWorkflowReceipt:
        _validate_receipt_members(self, REFERENCE_QUERY_INPUT_V11_REF)
        return self


class ReferenceQueryWorkflowReceiptV2(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-workflow-receipt/2.0"] = (
        "reference-query-workflow-receipt/2.0"
    )
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_id: WorkflowId
    workflow_definition_sha256: Sha256
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256
    step_run_id: StepRunId
    step_key: Literal["encode_reference_query"] = "encode_reference_query"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    query_artifact_owner_job_id: JobId
    native_launch_job_id: JobId
    launch_association_sha256: Sha256
    execution_result_schema: Literal["embedding-reference-query-result@2.0"] = (
        "embedding-reference-query-result@2.0"
    )
    query_input: ArtifactMemberPointer
    query_execution: PublicSolutionQueryExecutionPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile_sha256: Sha256
    published_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_public_message("receipt", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_receipt(self) -> Self:
        _validate_receipt_members(self, PUBLIC_SOLUTION_QUERY_INPUT_REF)
        return self


type SupportedReferenceQueryWorkflowReceipt = (
    ReferenceQueryWorkflowReceipt | ReferenceQueryWorkflowReceiptV2
)
type SupportedReferenceQueryNativeInput = EmbeddingReferenceQueryInputV11 | PublicSolutionQueryInput
type SupportedReferenceQueryNativeResult = EmbeddingReferenceQueryResult | PublicSolutionQueryResult


def _validate_receipt_members(
    receipt: SupportedReferenceQueryWorkflowReceipt, input_ref: str
) -> None:
    _member(receipt.query_input, "input.json", input_ref)
    _member(receipt.shard, "shard.json", SHARD_SCHEMA_REF)
    _member(receipt.binary, "vectors.f32", _BINARY_REF, "application/octet-stream")
    members = (
        receipt.query_input,
        receipt.query_execution.result_member,
        receipt.shard,
        receipt.binary,
    )
    if (
        receipt.query_execution.job_id != receipt.native_launch_job_id
        or len({(member.artifact_id, member.artifact_revision_id) for member in members}) != 1
    ):
        raise ValueError("reference QUERY file set or logical native Job differs")
    _hash(receipt, "receipt_sha256")


class ReferenceQueryStepOutput(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-step-output/1.0"] = "reference-query-step-output/1.0"
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_reference_query"] = "encode_reference_query"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["embedding-reference-query-result@1.0"] = (
        "embedding-reference-query-result@1.0"
    )
    receipt_schema: Literal["eom://schemas/workflow/reference-query-workflow-receipt/1.0"] = (
        REFERENCE_QUERY_RECEIPT_REF
    )
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("step-output", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_carrier(self) -> ReferenceQueryStepOutput:
        _member(self.receipt, "receipt.json", REFERENCE_QUERY_RECEIPT_REF)
        _hash(self, "output_sha256")
        return self


class ReferenceQueryStepOutputV2(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["reference-query-step-output/2.0"] = "reference-query-step-output/2.0"
    purpose: Literal["REFERENCE_QUERY"] = "REFERENCE_QUERY"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_reference_query"] = "encode_reference_query"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["embedding-reference-query-result@2.0"] = (
        "embedding-reference-query-result@2.0"
    )
    receipt_schema: Literal["eom://schemas/workflow/reference-query-workflow-receipt/2.0"] = (
        PUBLIC_REFERENCE_QUERY_RECEIPT_REF
    )
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_public_message("step-output", value)
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_carrier(self) -> Self:
        _member(self.receipt, "receipt.json", PUBLIC_REFERENCE_QUERY_RECEIPT_REF)
        _hash(self, "output_sha256")
        return self


SupportedReferenceQueryStepOutput: TypeAlias = (  # noqa: UP040 -- runtime outcome dispatch
    ReferenceQueryStepOutput | ReferenceQueryStepOutputV2
)


def parse_reference_query_workflow_request(value: object) -> ReferenceQueryWorkflowRequest:
    validate_reference_query_message("request", value)
    try:
        return ReferenceQueryWorkflowRequest.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_reference_query_workflow_request_v11(value: object) -> ReferenceQueryWorkflowRequestV11:
    validate_reference_query_request_v11(value)
    try:
        return ReferenceQueryWorkflowRequestV11.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_supported_reference_query_workflow_request(
    value: object,
) -> SupportedReferenceQueryWorkflowRequest:
    """Select exactly one literal parser; never relabel a historical request."""
    try:
        document = raw_similarity_contract_value(value)
    except (ValueError, TypeError):
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "reference-query-workflow-request/1.0":
                return parse_reference_query_workflow_request(document)
            case "reference-query-workflow-request/1.1":
                return parse_reference_query_workflow_request_v11(document)
            case "reference-query-workflow-request/2.0":
                return parse_reference_query_workflow_request_v2(document)
            case "reference-query-workflow-request/3.0":
                return parse_reference_query_workflow_request_v3(document)
    raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID")


def parse_reference_query_workflow_request_v2(value: object) -> ReferenceQueryWorkflowRequestV2:
    validate_reference_query_request_v2(value)
    try:
        return ReferenceQueryWorkflowRequestV2.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_reference_query_workflow_request_v3(value: object) -> ReferenceQueryWorkflowRequestV3:
    validate_reference_query_public_message("request", value)
    try:
        return ReferenceQueryWorkflowRequestV3.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_supported_reference_query_workflow_intent(
    value: object,
) -> SupportedReferenceQueryWorkflowIntent:
    """Retained pure provenance entry; the actual owner separately admits execution."""
    return parse_supported_reference_query_workflow_request(value)


def reference_query_result_schema(request: SupportedReferenceQueryWorkflowRequest) -> str:
    """The literal request family fixes its output, never the caller's chosen schema."""
    if isinstance(request, ReferenceQueryWorkflowRequestV3):
        return "embedding-reference-query-result@2.0"
    if isinstance(request, LegacyReferenceQueryWorkflowRequest):
        return "embedding-reference-query-result@1.0"
    raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID")


def parse_reference_query_execution_policy(value: object) -> ReferenceQueryExecutionPolicy:
    validate_reference_query_message("policy", value)
    try:
        return ReferenceQueryExecutionPolicy.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_reference_query_launch_association(value: object) -> ReferenceQueryLaunchAssociation:
    validate_reference_query_message("launch", value)
    try:
        return ReferenceQueryLaunchAssociation.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_reference_query_workflow_receipt(value: object) -> ReferenceQueryWorkflowReceipt:
    validate_reference_query_message("receipt", value)
    try:
        return ReferenceQueryWorkflowReceipt.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_reference_query_step_output(value: object) -> ReferenceQueryStepOutput:
    validate_reference_query_message("step-output", value)
    try:
        return ReferenceQueryStepOutput.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def parse_supported_reference_query_workflow_receipt(
    value: object,
) -> SupportedReferenceQueryWorkflowReceipt:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "reference-query-workflow-receipt/2.0"
    ):
        validate_reference_query_public_message("receipt", document)
        try:
            return ReferenceQueryWorkflowReceiptV2.model_validate(document)
        except ValidationError:
            raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None
    return parse_reference_query_workflow_receipt(document)


def parse_supported_reference_query_step_output(value: object) -> SupportedReferenceQueryStepOutput:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "reference-query-step-output/2.0"
    ):
        validate_reference_query_public_message("step-output", document)
        try:
            return ReferenceQueryStepOutputV2.model_validate(document)
        except ValidationError:
            raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None
    return parse_reference_query_step_output(document)


def parse_reference_query_native_input(
    request: SupportedReferenceQueryWorkflowIntent, native_input: object
) -> SupportedReferenceQueryNativeInput:
    try:
        document = raw_similarity_contract_value(native_input)
        if isinstance(request, ReferenceQueryWorkflowRequestV3):
            if (
                not isinstance(document, dict)
                or document.get("schema_version") != "embedding-reference-query-input/2.0"
            ):
                raise ValueError("public QUERY native input family differs")
            return PublicSolutionQueryInput.model_validate(document)
        return parse_embedding_reference_query_input_v11(document)
    except (JsonSchemaError, ValueError, TypeError):
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


def validate_reference_query_policy_bundle(
    policy: ReferenceQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
) -> tuple[ReferenceQueryExecutionPolicy, EmbeddingRuntimeBundle]:
    """Shared pure control closure for startup and actual requests; never authority."""
    policy = parse_reference_query_execution_policy(policy)
    try:
        bundle = validate_query_runtime_bundle(
            policy.spaces, policy.runtime_bundle, policy.resource_profile, bundle
        )
    except ValueError:
        raise ValueError("reference QUERY control/bundle closure differs") from None
    return policy, bundle


def validate_reference_query_native_result(
    native_input: SupportedReferenceQueryNativeInput, native_result: object
) -> SupportedReferenceQueryNativeResult:
    """Literal numerical family closure shared by CPU, finite batch and publication."""
    document = raw_similarity_contract_value(native_result)
    if isinstance(native_input, PublicSolutionQueryInput):
        result = PublicSolutionQueryResult.model_validate(document)
        validate_public_solution_query_result(native_input, result)
        return result
    result_v1 = parse_embedding_reference_query_result(document)
    validate_reference_query_result_v11(native_input, result_v1)
    return result_v1


def validate_reference_query_request_references(
    request: SupportedReferenceQueryWorkflowIntent,
    policy: ReferenceQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
) -> None:
    """Pure supplied-pointer closure; installed files and current source rights are not checked."""
    request = parse_supported_reference_query_workflow_intent(request)
    policy, bundle = validate_reference_query_policy_bundle(policy, bundle)
    if (
        request.native_execution_policy_sha256 != policy.policy_sha256
        or request.native_execution_policy.sha256
        != sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json")))
        or request.workflow_definition_sha256 != policy.workflow_definition_sha256
        or request.runtime_bundle != policy.runtime_bundle
        or request.resource_profile != policy.resource_profile
        or any(
            view.index is not None and view.index.spaces != policy.spaces
            for view in request.context_request.views
        )
    ):
        raise ValueError("reference QUERY control/bundle closure differs")


def validate_reference_query_launch_association(
    launch: ReferenceQueryLaunchAssociation,
    request: SupportedReferenceQueryWorkflowIntent,
    policy: ReferenceQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
    native_input: SupportedReferenceQueryNativeInput,
) -> None:
    launch = parse_reference_query_launch_association(launch)
    request = parse_supported_reference_query_workflow_intent(request)
    policy = parse_reference_query_execution_policy(policy)
    native_input = parse_reference_query_native_input(request, native_input)
    validate_reference_query_request_references(request, policy, bundle)
    indexed_views = {
        view.view: view.index for view in request.context_request.views if view.index is not None
    }
    if (
        launch.workflow_request_sha256 != request.request_sha256
        or launch.context_request_sha256 != request.context_request.request_sha256
        or native_input.context_request_sha256 != launch.context_request_sha256
        or launch.native_launch_job_id != native_input.job_id
        or launch.query_request_id != native_input.query_request_id
        or launch.query_request_sha256 != native_input.request_sha256
        or launch.query_input_set_sha256 != native_input.input_set_sha256
        or launch.recipe_sha256 != native_input.recipe.recipe_sha256
        or any(view.recipe != native_input.recipe for view in request.context_request.views)
        or any(
            row.view not in indexed_views
            or row.encoding.storage_partition != indexed_views[row.view].storage_partition
            for row in native_input.rows
        )
        or native_input.spaces != policy.spaces
        or native_input.batch_size != request.resource_profile.batch_size
        or native_input.threads != request.resource_profile.threads
        or launch.runtime_bundle != request.runtime_bundle
        or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
        or launch.launched_at < policy.created_at
    ):
        raise ValueError("reference QUERY launch differs from exact controller/native input")


def validate_reference_query_workflow_receipt(
    receipt: SupportedReferenceQueryWorkflowReceipt,
    request: SupportedReferenceQueryWorkflowIntent,
    policy: ReferenceQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
    launch: ReferenceQueryLaunchAssociation,
    native_input: SupportedReferenceQueryNativeInput,
    native_result: SupportedReferenceQueryNativeResult,
    *,
    workflow_id: str,
    step_run_id: str,
    query_artifact_owner_job_id: str,
    receipt_owner_job_id: str,
) -> None:
    """Exact historical values; supplied owner IDs are expectations, never authority grants."""
    receipt = parse_supported_reference_query_workflow_receipt(receipt)
    request = parse_supported_reference_query_workflow_intent(request)
    launch = parse_reference_query_launch_association(launch)
    native_input = parse_reference_query_native_input(request, native_input)
    validate_reference_query_launch_association(launch, request, policy, bundle, native_input)
    if isinstance(native_input, PublicSolutionQueryInput):
        if not isinstance(receipt, ReferenceQueryWorkflowReceiptV2):
            raise ValueError("public reference QUERY requires its exact receipt family")
        native_result = PublicSolutionQueryResult.model_validate(native_result)
        validate_public_solution_query_result(native_input, native_result)
    else:
        if not isinstance(receipt, ReferenceQueryWorkflowReceipt):
            raise ValueError("historical reference QUERY requires its exact receipt family")
        native_result = parse_embedding_reference_query_result(native_result)
        validate_reference_query_result_v11(native_input, native_result)
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
        or receipt.native_launch_job_id != native_input.job_id
        or receipt.launch_association_sha256 != launch.association_sha256
        or receipt.runtime_bundle != request.runtime_bundle
        or receipt.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
        or execution.query_request_id != native_input.query_request_id
        or execution.request_sha256 != native_input.request_sha256
        or execution.input_set_sha256 != native_input.input_set_sha256
        or execution.result_sha256 != native_result.result_sha256
        or receipt.query_input.sha256
        != sha256_bytes(canonical_json_bytes(native_input.model_dump(mode="json")))
        or execution.result_member.sha256
        != sha256_bytes(canonical_json_bytes(native_result.model_dump(mode="json")))
        or receipt.shard.sha256
        != sha256_bytes(canonical_json_bytes(native_result.shard.model_dump(mode="json")))
        or receipt.binary.sha256 != native_result.shard.binary.sha256
        or receipt.published_at < launch.launched_at
    ):
        raise ValueError("reference QUERY receipt differs from exact publication/input provenance")


def validate_reference_query_step_output(
    output: SupportedReferenceQueryStepOutput, receipt: SupportedReferenceQueryWorkflowReceipt
) -> None:
    output = parse_supported_reference_query_step_output(output)
    receipt = parse_supported_reference_query_workflow_receipt(receipt)
    fields = (
        "workflow_id",
        "step_run_id",
        "step_key",
        "attempt",
        "receipt_owner_job_id",
        "execution_result_schema",
        "receipt_sha256",
    )
    if any(
        getattr(output, field) != getattr(receipt, field) for field in fields
    ) or output.receipt.sha256 != sha256_bytes(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ):
        raise ValueError("reference QUERY carrier differs from exact receipt")
