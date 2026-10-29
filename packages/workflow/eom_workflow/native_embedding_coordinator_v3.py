"""Public continuation3 values; no source grant or computational Job retagging."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding_registry import (
    PublicSolutionIndexRegistrationResult,
    RegisterPublicSolutionIndexCommand,
    validate_public_solution_registration_result,
)
from eom_identifiers import content_sha256
from pydantic import model_validator

from eom_workflow.local_embedding_encoding_ownership_v3 import LocalEmbeddingLaunchIntentV3
from eom_workflow.local_embedding_workflow_receipt_v3 import LocalEmbeddingStepOutputV3
from eom_workflow.models import JobId
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorAllocation,
    NativeCoordinatorPhase,
    validate_native_coordinator_completion_producer,
    validate_native_coordinator_history_identity,
    validate_native_coordinator_index_allocation,
    validate_native_coordinator_registration_times,
)
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)


class NativeCoordinatorIndexPreparedV3(NativeEmbeddingContract):
    registration_command: RegisterPublicSolutionIndexCommand
    index_created_at: UtcDatetime


class NativeCoordinatorRegisteredV3(NativeEmbeddingContract):
    registration_result: PublicSolutionIndexRegistrationResult
    registration_observed_at: UtcDatetime


class NativeCoordinatorCompletedV3(NativeEmbeddingContract):
    output: LocalEmbeddingStepOutputV3


_PAYLOAD_TYPES = {
    "ALLOCATION": NativeCoordinatorAllocation,
    "INDEX_PREPARED": NativeCoordinatorIndexPreparedV3,
    "REGISTERED": NativeCoordinatorRegisteredV3,
    "COMPLETED": NativeCoordinatorCompletedV3,
}


class NativeEmbeddingCoordinatorCheckpointV3(NativeEmbeddingContract):
    schema_version: Literal["native-embedding-coordinator/3.0"] = "native-embedding-coordinator/3.0"
    record_type: NativeCoordinatorPhase
    native_launch_job_id: JobId
    intent_sha256: Sha256
    payload: (
        NativeCoordinatorAllocation
        | NativeCoordinatorIndexPreparedV3
        | NativeCoordinatorRegisteredV3
        | NativeCoordinatorCompletedV3
    )
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def exact_stage(self) -> NativeEmbeddingCoordinatorCheckpointV3:
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
            raise ValueError("public-solution native coordinator stage or identity differs")
        return self


def parse_native_embedding_coordinator_checkpoint_v3(
    value: object,
) -> NativeEmbeddingCoordinatorCheckpointV3:
    document = raw_similarity_contract_value(value)
    validate_local_embedding_admission_message("public-coordinator", document)
    return NativeEmbeddingCoordinatorCheckpointV3.model_validate(document)


def native_coordinator_checkpoint_v3(
    intent: LocalEmbeddingLaunchIntentV3,
    phase: NativeCoordinatorPhase,
    payload: NativeCoordinatorAllocation
    | NativeCoordinatorIndexPreparedV3
    | NativeCoordinatorRegisteredV3
    | NativeCoordinatorCompletedV3,
) -> NativeEmbeddingCoordinatorCheckpointV3:
    intent = LocalEmbeddingLaunchIntentV3.model_validate(raw_similarity_contract_value(intent))
    body = {
        "schema_version": "native-embedding-coordinator/3.0",
        "record_type": phase,
        "native_launch_job_id": intent.native_launch_job_id,
        "intent_sha256": intent.intent_sha256,
        "payload": raw_similarity_contract_value(payload),
    }
    return parse_native_embedding_coordinator_checkpoint_v3(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def validate_native_coordinator_history_v3(
    records: tuple[NativeEmbeddingCoordinatorCheckpointV3, ...],
    intent: LocalEmbeddingLaunchIntentV3,
) -> None:
    """Contiguous original metadata3 history; no current permission or physical proof."""
    intent = LocalEmbeddingLaunchIntentV3.model_validate(raw_similarity_contract_value(intent))
    validate_native_coordinator_history_identity(
        tuple((row.record_type, row.native_launch_job_id, row.intent_sha256) for row in records),
        native_launch_job_id=intent.native_launch_job_id,
        intent_sha256=intent.intent_sha256,
    )
    checked = tuple(parse_native_embedding_coordinator_checkpoint_v3(row) for row in records)
    if not checked:
        return
    allocation = checked[0].payload
    assert isinstance(allocation, NativeCoordinatorAllocation)
    if len(checked) >= 2:
        prepared = checked[1].payload
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV3)
        command = prepared.registration_command
        validate_native_coordinator_index_allocation(
            allocation,
            index_artifact_id=command.index_manifest.artifact_id,
            index_artifact_revision_id=command.index_manifest.artifact_revision_id,
            index_created_at=prepared.index_created_at,
        )
    if len(checked) >= 3:
        prepared = checked[1].payload
        registered = checked[2].payload
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV3)
        assert isinstance(registered, NativeCoordinatorRegisteredV3)
        validate_public_solution_registration_result(
            prepared.registration_command, registered.registration_result
        )
        validate_native_coordinator_registration_times(
            index_created_at=prepared.index_created_at,
            registered_at=registered.registration_result.registered_at,
            registration_observed_at=registered.registration_observed_at,
        )
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, NativeCoordinatorCompletedV3)
        validate_native_coordinator_completion_producer(
            allocation,
            completed.output,
            workflow_id=intent.workflow_id,
            step_run_id=intent.step_run_id,
        )
