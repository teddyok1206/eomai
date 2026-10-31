"""Source-plan4 provenance; numerical Job, owned input, result and row stay1."""

from typing import Annotated, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
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
    validate_embedding_encoding_metadata,
    validate_embedding_encoding_read_values,
    validate_embedding_owned_association_values,
    validate_local_embedding_launch_values,
)
from eom_workflow.local_embedding_encoding_ownership_v3 import PublicSolutionLaunchIntentBody
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_source_plan_v4 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF,
    LocalEmbeddingSourcePlanV4,
    parse_local_embedding_source_plan_v4,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

EMBEDDING_ENCODING_OWNERSHIP_V4_SCHEMA_REF = (
    "eom://schemas/workflow/embedding-encoding-ownership/4.0"
)
EMBEDDING_ENCODING_OWNERSHIP_V4_SCHEMA_SHA256 = (
    "sha256:28d2448abee1c67b7b48ea2717aa59029aa5bf2a4a31a1aff9699c8ba9780284"
)


class LocalEmbeddingLaunchIntentV4(PublicSolutionLaunchIntentBody):
    _source_plan_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF


class LocalEmbeddingLaunchAssociationV4(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/4.0"] = "embedding-encoding-ownership/4.0"
    record_type: Literal["LAUNCH_ASSOCIATION"] = "LAUNCH_ASSOCIATION"
    intent: LocalEmbeddingLaunchIntentV4
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...] = Field(min_length=1, max_length=1024)
    owned_input: ArtifactMemberPointer
    owned_input_request_sha256: Sha256
    owned_input_set_sha256: Sha256
    association_sha256: Sha256

    @model_validator(mode="after")
    def exact_owned_subset(self) -> Self:
        validate_embedding_owned_association_values(self)
        validate_embedding_encoding_metadata(self, "association_sha256")
        return self


class EmbeddingEncodingAttachedEventV4(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/4.0"] = "embedding-encoding-ownership/4.0"
    record_type: Literal["ATTACHED"] = "ATTACHED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV4
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_attachment(self) -> Self:
        if self.owned_job.job_reference.job_id == self.intent.native_launch_job_id:
            raise ValueError("encoding reservation and native launch are distinct Jobs")
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingCompletedEventV4(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/4.0"] = "embedding-encoding-ownership/4.0"
    record_type: Literal["COMPLETED"] = "COMPLETED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntentV4
    launch_association_sha256: Sha256
    receipt: EmbeddingSharedRowReceipt
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> Self:
        validate_embedding_completed_event_values(self)
        validate_embedding_encoding_metadata(self, "event_sha256")
        return self


class EmbeddingEncodingReadResultV4(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-ownership/4.0"] = "embedding-encoding-ownership/4.0"
    record_type: Literal["READ_RESULT"] = "READ_RESULT"
    owned_job: LocalEmbeddingOwnedJob
    owner_intent: LocalEmbeddingLaunchIntentV4
    status: Literal["OWNED", "BORROWED", "COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"]
    completion: EmbeddingEncodingCompletedEventV4 | None
    read_sha256: Sha256

    @model_validator(mode="after")
    def exact_state_receipt(self) -> Self:
        validate_embedding_encoding_read_values(
            self.owned_job, self.owner_intent, self.status, self.completion
        )
        validate_embedding_encoding_metadata(self, "read_sha256")
        return self


type EmbeddingEncodingOwnershipMessageV4 = Annotated[
    LocalEmbeddingLaunchAssociationV4
    | EmbeddingEncodingAttachedEventV4
    | EmbeddingEncodingCompletedEventV4
    | EmbeddingEncodingReadResultV4,
    Field(discriminator="record_type"),
]
_ADAPTER: TypeAdapter[EmbeddingEncodingOwnershipMessageV4] = TypeAdapter(
    EmbeddingEncodingOwnershipMessageV4
)


def parse_embedding_encoding_ownership_v4(value: object) -> EmbeddingEncodingOwnershipMessageV4:
    try:
        document = raw_public_solution_contract_value(value)
        validate_local_embedding_admission_message("registered-public-ownership", document)
        return _ADAPTER.validate_python(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_launch_association_v4(value: object) -> LocalEmbeddingLaunchAssociationV4:
    checked = parse_embedding_encoding_ownership_v4(value)
    if not isinstance(checked, LocalEmbeddingLaunchAssociationV4):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return checked


def validate_local_embedding_launch_association_v4(
    association: LocalEmbeddingLaunchAssociationV4,
    plan: LocalEmbeddingSourcePlanV4,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
    association = parse_local_embedding_launch_association_v4(association)
    plan = parse_local_embedding_source_plan_v4(plan)
    owned_input = parse_incremental_embedding_input(raw_public_solution_contract_value(owned_input))
    resources = LocalEmbeddingResourceProfile.model_validate(
        raw_public_solution_contract_value(resources)
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


def validate_embedding_encoding_completions_v4(
    events: tuple[EmbeddingEncodingCompletedEventV4, ...],
    association: LocalEmbeddingLaunchAssociationV4,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    if type(events) is not tuple or not 1 <= len(events) <= 1024:
        raise ValueError("registered public encoding completion batch is invalid")
    checked = []
    for raw in events:
        event = parse_embedding_encoding_ownership_v4(raw)
        if not isinstance(event, EmbeddingEncodingCompletedEventV4):
            raise ValueError("registered public encoding completion family differs")
        checked.append(event)
    association = parse_local_embedding_launch_association_v4(association)
    validate_embedding_completion_batch_values(tuple(checked), association, owned_input, result)
