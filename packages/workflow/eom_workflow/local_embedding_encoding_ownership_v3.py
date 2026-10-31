"""Public source-plan3 ownership metadata; actual computational Job/input stay1."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self

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
    EmbeddingSharedRowReceipt,
    LocalEmbeddingOwnedJob,
    validate_embedding_completed_event_values,
    validate_embedding_completion_batch_values,
    validate_embedding_encoding_member,
    validate_embedding_encoding_metadata,
    validate_embedding_encoding_read_values,
    validate_embedding_owned_association_values,
    validate_local_embedding_launch_values,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_source_plan_v3 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
)
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

EMBEDDING_ENCODING_OWNERSHIP_V3_SCHEMA_REF = (
    "eom://schemas/workflow/embedding-encoding-ownership/3.0"
)
EMBEDDING_ENCODING_OWNERSHIP_V3_SCHEMA_SHA256 = (
    "sha256:d30a5355499c7576249ca46c147411b52ac11407f2115003f87b20fcaa4db465"
)


class PublicSolutionLaunchIntentBody(NativeEmbeddingContract):
    """Shared value fields; concrete families retain their exact plan schema."""

    _source_plan_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF
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
    def exact_intent(self) -> Self:
        validate_embedding_encoding_member(
            self.source_plan, "source-plan.json", self._source_plan_schema_ref
        )
        validate_embedding_encoding_metadata(self, "intent_sha256")
        return self


class LocalEmbeddingLaunchIntentV3(PublicSolutionLaunchIntentBody):
    """Frozen source-plan3 intent, not interchangeable with intent4."""


class LocalEmbeddingLaunchAssociationV3(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/3.0"] = "embedding-encoding-ownership/3.0"
    record_type: Literal["LAUNCH_ASSOCIATION"] = "LAUNCH_ASSOCIATION"
    intent: LocalEmbeddingLaunchIntentV3
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...] = Field(min_length=1, max_length=1024)
    owned_input: ArtifactMemberPointer
    owned_input_request_sha256: Sha256
    owned_input_set_sha256: Sha256
    association_sha256: Sha256

    @model_validator(mode="after")
    def exact_owned_subset(self) -> LocalEmbeddingLaunchAssociationV3:
        validate_embedding_owned_association_values(self)
        validate_embedding_encoding_metadata(self, "association_sha256")
        return self


class EmbeddingEncodingAttachedEventV3(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/3.0"] = "embedding-encoding-ownership/3.0"
    record_type: Literal["ATTACHED"] = "ATTACHED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV3
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_attachment(self) -> EmbeddingEncodingAttachedEventV3:
        if self.owned_job.job_reference.job_id == self.intent.native_launch_job_id:
            raise ValueError("encoding reservation and native launch are distinct Jobs")
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingCompletedEventV3(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/3.0"] = "embedding-encoding-ownership/3.0"
    record_type: Literal["COMPLETED"] = "COMPLETED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV3
    launch_association_sha256: Sha256
    receipt: EmbeddingSharedRowReceipt
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> EmbeddingEncodingCompletedEventV3:
        validate_embedding_completed_event_values(self)
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingReadResultV3(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/3.0"] = "embedding-encoding-ownership/3.0"
    record_type: Literal["READ_RESULT"] = "READ_RESULT"
    owned_job: LocalEmbeddingOwnedJob
    owner_intent: LocalEmbeddingLaunchIntentV3
    status: Literal["OWNED", "BORROWED", "COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"]
    completion: EmbeddingEncodingCompletedEventV3 | None
    read_sha256: Sha256

    @model_validator(mode="after")
    def exact_state_receipt(self) -> EmbeddingEncodingReadResultV3:
        validate_embedding_encoding_read_values(
            self.owned_job, self.owner_intent, self.status, self.completion
        )
        validate_embedding_encoding_metadata(self, "read_sha256")
        return self


type EmbeddingEncodingOwnershipMessageV3 = Annotated[
    LocalEmbeddingLaunchAssociationV3
    | EmbeddingEncodingAttachedEventV3
    | EmbeddingEncodingCompletedEventV3
    | EmbeddingEncodingReadResultV3,
    Field(discriminator="record_type"),
]
_ADAPTER: TypeAdapter[EmbeddingEncodingOwnershipMessageV3] = TypeAdapter(
    EmbeddingEncodingOwnershipMessageV3
)


def parse_embedding_encoding_ownership_v3(value: object) -> EmbeddingEncodingOwnershipMessageV3:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("public-ownership", document)
        return _ADAPTER.validate_python(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_launch_association_v3(value: object) -> LocalEmbeddingLaunchAssociationV3:
    checked = parse_embedding_encoding_ownership_v3(value)
    if not isinstance(checked, LocalEmbeddingLaunchAssociationV3):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return checked


def validate_local_embedding_launch_association_v3(
    association: LocalEmbeddingLaunchAssociationV3,
    plan: LocalEmbeddingSourcePlanV3,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
    association = parse_local_embedding_launch_association_v3(association)
    plan = parse_local_embedding_source_plan_v3(plan)
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


def validate_embedding_encoding_completions_v3(
    events: tuple[EmbeddingEncodingCompletedEventV3, ...],
    association: LocalEmbeddingLaunchAssociationV3,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    if type(events) is not tuple or not 1 <= len(events) <= 1024:
        raise ValueError("public-solution encoding completion batch is invalid")
    checked = []
    for raw in events:
        event = parse_embedding_encoding_ownership_v3(raw)
        if not isinstance(event, EmbeddingEncodingCompletedEventV3):
            raise ValueError("public-solution encoding completion event family differs")
        checked.append(event)
    association = parse_local_embedding_launch_association_v3(association)
    validate_embedding_completion_batch_values(tuple(checked), association, owned_input, result)
