"""Mixed source-plan2 ownership metadata; actual computational Job/input stay1."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_incremental_embedding_input,
)
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    EmbeddingEncodingReadResult,
    EmbeddingSharedRowReceipt,
    LocalEmbeddingLaunchIntent,
    LocalEmbeddingOwnedJob,
    parse_embedding_encoding_job_message,
    prepare_embedding_completion_context,
    validate_embedding_completed_event_values,
    validate_embedding_completion_event_context,
    validate_embedding_encoding_member,
    validate_embedding_encoding_metadata,
    validate_embedding_encoding_read_values,
    validate_embedding_owned_association_values,
    validate_local_embedding_launch_values,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_REF = (
    "eom://schemas/workflow/embedding-encoding-ownership/2.0"
)
EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_SHA256 = (
    "sha256:9bd1fe4ce7b097681ae8195ec1b3f7a365400ca6f917c47eb2ea3218116c1db1"
)


class LocalEmbeddingLaunchIntentV2(NativeEmbeddingContract):
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    native_launch_job_id: JobId
    workflow_request_sha256: Sha256
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    resource_profile_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    runner_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    lease_generation: int = Field(ge=1, le=2147483647, strict=True)
    intent_sha256: Sha256

    @model_validator(mode="after")
    def exact_intent(self) -> LocalEmbeddingLaunchIntentV2:
        validate_embedding_encoding_member(
            self.source_plan, "source-plan.json", LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF
        )
        validate_embedding_encoding_metadata(self, "intent_sha256")
        return self


class LocalEmbeddingLaunchAssociationV2(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/2.0"] = "embedding-encoding-ownership/2.0"
    record_type: Literal["LAUNCH_ASSOCIATION"] = "LAUNCH_ASSOCIATION"
    intent: LocalEmbeddingLaunchIntentV2
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...] = Field(min_length=1, max_length=1024)
    owned_input: ArtifactMemberPointer
    owned_input_request_sha256: Sha256
    owned_input_set_sha256: Sha256
    association_sha256: Sha256

    @model_validator(mode="after")
    def exact_owned_subset(self) -> LocalEmbeddingLaunchAssociationV2:
        validate_embedding_owned_association_values(self)
        validate_embedding_encoding_metadata(self, "association_sha256")
        return self


class EmbeddingEncodingAttachedEventV2(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/2.0"] = "embedding-encoding-ownership/2.0"
    record_type: Literal["ATTACHED"] = "ATTACHED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV2
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_attachment(self) -> EmbeddingEncodingAttachedEventV2:
        if self.owned_job.job_reference.job_id == self.intent.native_launch_job_id:
            raise ValueError("encoding reservation and native launch are distinct Jobs")
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingCompletedEventV2(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/2.0"] = "embedding-encoding-ownership/2.0"
    record_type: Literal["COMPLETED"] = "COMPLETED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV2
    launch_association_sha256: Sha256
    receipt: EmbeddingSharedRowReceipt
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> EmbeddingEncodingCompletedEventV2:
        validate_embedding_completed_event_values(self)
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingReadResultV2(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/2.0"] = "embedding-encoding-ownership/2.0"
    record_type: Literal["READ_RESULT"] = "READ_RESULT"
    owned_job: LocalEmbeddingOwnedJob
    owner_intent: LocalEmbeddingLaunchIntentV2
    status: Literal["OWNED", "BORROWED", "COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"]
    completion: EmbeddingEncodingCompletedEventV2 | None
    read_sha256: Sha256

    @model_validator(mode="after")
    def exact_state_receipt(self) -> EmbeddingEncodingReadResultV2:
        validate_embedding_encoding_read_values(
            self.owned_job, self.owner_intent, self.status, self.completion
        )
        validate_embedding_encoding_metadata(self, "read_sha256")
        return self


type EmbeddingEncodingOwnershipMessageV2 = Annotated[
    LocalEmbeddingLaunchAssociationV2
    | EmbeddingEncodingAttachedEventV2
    | EmbeddingEncodingCompletedEventV2
    | EmbeddingEncodingReadResultV2,
    Field(discriminator="record_type"),
]
_ADAPTER: TypeAdapter[EmbeddingEncodingOwnershipMessageV2] = TypeAdapter(
    EmbeddingEncodingOwnershipMessageV2
)


def parse_embedding_encoding_ownership_v2(value: object) -> EmbeddingEncodingOwnershipMessageV2:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("mixed-ownership", document)
        return _ADAPTER.validate_python(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_launch_association_v2(value: object) -> LocalEmbeddingLaunchAssociationV2:
    checked = parse_embedding_encoding_ownership_v2(value)
    if not isinstance(checked, LocalEmbeddingLaunchAssociationV2):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return checked


def parse_supported_embedding_encoding_read(
    value: object,
) -> EmbeddingEncodingReadResult | EmbeddingEncodingReadResultV2:
    """Preserve the ORIGINAL owner family; never retag historical completion1 as2."""
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        if document.get("schema_version") == "embedding-encoding-job/1.0":
            result = parse_embedding_encoding_job_message(document)
            if isinstance(result, EmbeddingEncodingReadResult):
                return result
        elif document.get("schema_version") == "embedding-encoding-ownership/2.0":
            successor = parse_embedding_encoding_ownership_v2(document)
            if isinstance(successor, EmbeddingEncodingReadResultV2):
                return successor
    raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def validate_supported_embedding_encoding_read(
    value: object,
    *,
    expected_request: EmbeddingEncodingJobRequest,
    expected_reference: EmbeddingEncodingJobReference,
) -> EmbeddingEncodingReadResult | EmbeddingEncodingReadResultV2:
    """Exact canonical encoding/Job allocation only, not source/lease authority."""
    result = parse_supported_embedding_encoding_read(value)
    request = parse_embedding_encoding_job_message(raw_similarity_contract_value(expected_request))
    reference = EmbeddingEncodingJobReference.model_validate(
        raw_similarity_contract_value(expected_reference)
    )
    if (
        not isinstance(request, EmbeddingEncodingJobRequest)
        or result.owned_job.request != request
        or result.owned_job.job_reference != reference
    ):
        raise ValueError("encoding read differs from exact original computational Job")
    return result


def validate_local_embedding_launch_association_v2(
    association: LocalEmbeddingLaunchAssociationV2,
    plan: LocalEmbeddingSourcePlanV2,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
    association = parse_local_embedding_launch_association_v2(association)
    plan = parse_local_embedding_source_plan_v2(plan)
    owned_input = parse_incremental_embedding_input(raw_similarity_contract_value(owned_input))
    resources = LocalEmbeddingResourceProfile.model_validate(
        raw_similarity_contract_value(resources)
    )
    validate_local_embedding_launch_values(
        association,
        plan_sha256=plan.plan_sha256,
        plan_raw_sha256=sha256_bytes(canonical_json_bytes(plan.model_dump(mode="json"))),
        planned_encodings=tuple(demand.encoding for demand in plan.demands),
        space=plan.space,
        owned_input=owned_input,
        resources=resources,
        workflow_request_sha256=workflow_request_sha256,
    )


def validate_embedding_encoding_completions_v2(
    events: tuple[EmbeddingEncodingCompletedEventV2, ...],
    association: LocalEmbeddingLaunchAssociationV2,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    if type(events) is not tuple or not 1 <= len(events) <= 1024:
        raise ValueError("mixed encoding completion batch is invalid")
    checked = []
    for raw in events:
        event = parse_embedding_encoding_ownership_v2(raw)
        if not isinstance(event, EmbeddingEncodingCompletedEventV2):
            raise ValueError("mixed encoding completion event family differs")
        checked.append(event)
    association = parse_local_embedding_launch_association_v2(association)
    context = prepare_embedding_completion_context(association, owned_input, result)
    keys = tuple(event.owned_job.request.encoding.encoding_sha256 for event in checked)
    if keys != tuple(sorted(set(keys))) or keys != tuple(context.by_encoding):
        raise ValueError("mixed encoding completion batch does not cover exact original owned set")
    for event in checked:
        assert isinstance(event, EmbeddingEncodingCompletedEventV2)
        validate_embedding_completion_event_context(event, context)


type SupportedLocalEmbeddingLaunchIntent = LocalEmbeddingLaunchIntent | LocalEmbeddingLaunchIntentV2


def local_embedding_launch_protocol(request: SupportedLocalEmbeddingRequest) -> tuple[str, str]:
    """Actual native metadata Job protocol; not the numerical execution channel."""
    checked = parse_supported_local_embedding_request(request)
    if isinstance(checked, LocalEmbeddingWorkflowRequestV2):
        return "embedding-encoding-ownership/2.0", EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_SHA256
    return "embedding-encoding-job/1.0", next(
        entry[3] for entry in LOCAL_EMBEDDING_SCHEMA_RESOURCES if entry[0] == "encoding-job"
    )


def parse_local_embedding_launch_intent_for_request(
    value: object, request: SupportedLocalEmbeddingRequest
) -> SupportedLocalEmbeddingLaunchIntent:
    """Explicit owner-selected request family; never infer a new grant from a pointer."""
    checked = parse_supported_local_embedding_request(request)
    document = raw_similarity_contract_value(value)
    if isinstance(checked, LocalEmbeddingWorkflowRequestV2):
        return LocalEmbeddingLaunchIntentV2.model_validate(document)
    return LocalEmbeddingLaunchIntent.model_validate(document)
