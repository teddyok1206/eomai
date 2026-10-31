"""Continuation4 reuses fixed stages and original producer identities, not claims."""

from types import MappingProxyType
from typing import Literal, Self

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
    validate_public_solution_registration_result_v4,
)
from eom_identifiers import content_sha256
from pydantic import model_validator

from eom_workflow.local_embedding_encoding_ownership_v4 import LocalEmbeddingLaunchIntentV4
from eom_workflow.local_embedding_workflow_receipt_v4 import LocalEmbeddingStepOutputV4
from eom_workflow.models import JobId
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorAllocation,
    NativeCoordinatorPhase,
    validate_native_coordinator_completion_producer,
    validate_native_coordinator_history_identity,
    validate_native_coordinator_index_allocation,
    validate_native_coordinator_registration_times,
)
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message


class NativeCoordinatorIndexPreparedV4(NativeEmbeddingContract):
    registration_command: RegisterPublicSolutionIndexCommandV4
    index_created_at: UtcDatetime


class NativeCoordinatorRegisteredV4(NativeEmbeddingContract):
    registration_result: PublicSolutionIndexRegistrationResultV4
    registration_observed_at: UtcDatetime


class NativeCoordinatorCompletedV4(NativeEmbeddingContract):
    output: LocalEmbeddingStepOutputV4


_PAYLOAD_TYPES = MappingProxyType(
    {
        "ALLOCATION": NativeCoordinatorAllocation,
        "INDEX_PREPARED": NativeCoordinatorIndexPreparedV4,
        "REGISTERED": NativeCoordinatorRegisteredV4,
        "COMPLETED": NativeCoordinatorCompletedV4,
    }
)
type NativeCoordinatorPayloadV4 = (
    NativeCoordinatorAllocation
    | NativeCoordinatorIndexPreparedV4
    | NativeCoordinatorRegisteredV4
    | NativeCoordinatorCompletedV4
)


class NativeEmbeddingCoordinatorCheckpointV4(NativeEmbeddingContract):
    schema_version: Literal["native-embedding-coordinator/4.0"] = "native-embedding-coordinator/4.0"
    record_type: NativeCoordinatorPhase
    native_launch_job_id: JobId
    intent_sha256: Sha256
    payload: NativeCoordinatorPayloadV4
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def exact_stage(self) -> Self:
        if (
            type(self.payload) is not _PAYLOAD_TYPES[self.record_type]
            or self.checkpoint_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))
            or (
                isinstance(self.payload, NativeCoordinatorAllocation)
                and self.native_launch_job_id
                in {self.payload.index_producer.job_id, self.payload.receipt_producer.job_id}
            )
        ):
            raise ValueError("registered public coordinator phase or identity differs")
        return self


def parse_native_embedding_coordinator_checkpoint_v4(
    value: object,
) -> NativeEmbeddingCoordinatorCheckpointV4:
    document = raw_public_solution_contract_value(value)
    validate_local_embedding_admission_message("registered-public-coordinator", document)
    return NativeEmbeddingCoordinatorCheckpointV4.model_validate(document)


def native_coordinator_checkpoint_v4(
    intent: LocalEmbeddingLaunchIntentV4,
    phase: NativeCoordinatorPhase,
    payload: NativeCoordinatorPayloadV4,
) -> NativeEmbeddingCoordinatorCheckpointV4:
    intent = LocalEmbeddingLaunchIntentV4.model_validate(raw_public_solution_contract_value(intent))
    body = {
        "schema_version": "native-embedding-coordinator/4.0",
        "record_type": phase,
        "native_launch_job_id": intent.native_launch_job_id,
        "intent_sha256": intent.intent_sha256,
        "payload": raw_public_solution_contract_value(payload),
    }
    return parse_native_embedding_coordinator_checkpoint_v4(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def validate_native_coordinator_history_v4(
    records: tuple[NativeEmbeddingCoordinatorCheckpointV4, ...],
    intent: LocalEmbeddingLaunchIntentV4,
) -> None:
    """Exact immutable continuation, not permission/current-head/runtime admission."""
    intent = LocalEmbeddingLaunchIntentV4.model_validate(raw_public_solution_contract_value(intent))
    if type(records) is not tuple or len(records) > 4:
        raise ValueError("registered public coordinator history is not a bounded tuple")
    checked = tuple(parse_native_embedding_coordinator_checkpoint_v4(row) for row in records)
    validate_native_coordinator_history_identity(
        tuple((row.record_type, row.native_launch_job_id, row.intent_sha256) for row in checked),
        native_launch_job_id=intent.native_launch_job_id,
        intent_sha256=intent.intent_sha256,
    )
    if not checked:
        return
    allocation = checked[0].payload
    assert isinstance(allocation, NativeCoordinatorAllocation)
    if len(checked) >= 2:
        prepared = checked[1].payload
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
        command = prepared.registration_command
        validate_native_coordinator_index_allocation(
            allocation,
            index_artifact_id=command.index_manifest.artifact_id,
            index_artifact_revision_id=command.index_manifest.artifact_revision_id,
            index_created_at=prepared.index_created_at,
        )
    if len(checked) >= 3:
        prepared, registered = checked[1].payload, checked[2].payload
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
        assert isinstance(registered, NativeCoordinatorRegisteredV4)
        validate_public_solution_registration_result_v4(
            prepared.registration_command, registered.registration_result
        )
        validate_native_coordinator_registration_times(
            index_created_at=prepared.index_created_at,
            registered_at=registered.registration_result.registered_at,
            registration_observed_at=registered.registration_observed_at,
        )
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, NativeCoordinatorCompletedV4)
        validate_native_coordinator_completion_producer(
            allocation,
            completed.output,
            workflow_id=intent.workflow_id,
            step_run_id=intent.step_run_id,
        )
