"""Fixed continuation values; not authority, runtime state, text or numerical payloads."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
    validate_embedding_registration_result,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_workflow.local_embedding_encoding_job import LocalEmbeddingLaunchIntent
from eom_workflow.local_embedding_workflow_receipt import LocalEmbeddingStepOutput
from eom_workflow.models import ArtifactId, JobId, RevisionId
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_native_embedding_coordinator_message,
)

type NativeCoordinatorPhase = Literal["ALLOCATION", "INDEX_PREPARED", "REGISTERED", "COMPLETED"]
NATIVE_COORDINATOR_PHASES: tuple[NativeCoordinatorPhase, ...] = (
    "ALLOCATION",
    "INDEX_PREPARED",
    "REGISTERED",
    "COMPLETED",
)


class NativeArtifactProducerIdentity(NativeEmbeddingContract):
    job_id: JobId
    artifact_id: ArtifactId
    artifact_revision_id: RevisionId


class NativeCoordinatorAllocation(NativeEmbeddingContract):
    index_producer: NativeArtifactProducerIdentity
    receipt_producer: NativeArtifactProducerIdentity
    created_at: UtcDatetime
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def distinct_producers(self) -> NativeCoordinatorAllocation:
        for field in ("job_id", "artifact_id", "artifact_revision_id"):
            if getattr(self.index_producer, field) == getattr(self.receipt_producer, field):
                raise ValueError("native coordinator repeats a publication identity")
        return self


class NativeCoordinatorIndexPrepared(NativeEmbeddingContract):
    registration_command: RegisterEmbeddingIndexCommand
    index_created_at: UtcDatetime


class NativeCoordinatorRegistered(NativeEmbeddingContract):
    registration_result: EmbeddingIndexRegistrationResult
    registration_observed_at: UtcDatetime


class NativeCoordinatorCompleted(NativeEmbeddingContract):
    output: LocalEmbeddingStepOutput


_PAYLOAD_TYPES = {
    "ALLOCATION": NativeCoordinatorAllocation,
    "INDEX_PREPARED": NativeCoordinatorIndexPrepared,
    "REGISTERED": NativeCoordinatorRegistered,
    "COMPLETED": NativeCoordinatorCompleted,
}


class NativeEmbeddingCoordinatorCheckpoint(NativeEmbeddingContract):
    schema_version: Literal["native-embedding-coordinator/1.0"] = "native-embedding-coordinator/1.0"
    record_type: NativeCoordinatorPhase
    native_launch_job_id: JobId
    intent_sha256: Sha256
    payload: (
        NativeCoordinatorAllocation
        | NativeCoordinatorIndexPrepared
        | NativeCoordinatorRegistered
        | NativeCoordinatorCompleted
    )
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def exact_stage(self) -> NativeEmbeddingCoordinatorCheckpoint:
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
            raise ValueError("native coordinator stage or identity differs")
        return self


def parse_native_embedding_coordinator_checkpoint(
    value: object,
) -> NativeEmbeddingCoordinatorCheckpoint:
    validate_native_embedding_coordinator_message(value)
    return NativeEmbeddingCoordinatorCheckpoint.model_validate(value)


def native_coordinator_checkpoint(
    intent: LocalEmbeddingLaunchIntent,
    phase: NativeCoordinatorPhase,
    payload: NativeCoordinatorAllocation
    | NativeCoordinatorIndexPrepared
    | NativeCoordinatorRegistered
    | NativeCoordinatorCompleted,
) -> NativeEmbeddingCoordinatorCheckpoint:
    body = {
        "schema_version": "native-embedding-coordinator/1.0",
        "record_type": phase,
        "native_launch_job_id": intent.native_launch_job_id,
        "intent_sha256": intent.intent_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    return parse_native_embedding_coordinator_checkpoint(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def validate_native_coordinator_history(
    records: tuple[NativeEmbeddingCoordinatorCheckpoint, ...], intent: LocalEmbeddingLaunchIntent
) -> None:
    """Pure contiguous prefix/producer/registration closure; never actual commit or permission."""
    if (
        tuple(row.record_type for row in records) != NATIVE_COORDINATOR_PHASES[: len(records)]
        or len(records) > 4
    ):
        raise ValueError("native coordinator history is skipped, duplicated or unordered")
    checked = tuple(parse_native_embedding_coordinator_checkpoint(row) for row in records)
    if any(
        row.native_launch_job_id != intent.native_launch_job_id
        or row.intent_sha256 != intent.intent_sha256
        for row in checked
    ):
        raise ValueError("native coordinator belongs to another original intent")
    if not checked:
        return
    allocation = checked[0].payload
    assert isinstance(allocation, NativeCoordinatorAllocation)
    if len(checked) >= 2:
        prepared = checked[1].payload
        assert isinstance(prepared, NativeCoordinatorIndexPrepared)
        command = prepared.registration_command
        if (
            command.index_manifest.artifact_id != allocation.index_producer.artifact_id
            or command.index_manifest.artifact_revision_id
            != allocation.index_producer.artifact_revision_id
            or prepared.index_created_at < allocation.created_at
        ):
            raise ValueError("native index preparation differs from original allocation")
    if len(checked) >= 3:
        prepared = checked[1].payload
        assert isinstance(prepared, NativeCoordinatorIndexPrepared)
        command = prepared.registration_command
        registered = checked[2].payload
        assert isinstance(registered, NativeCoordinatorRegistered)
        validate_embedding_registration_result(command, registered.registration_result)
        if not (
            prepared.index_created_at
            <= registered.registration_result.registered_at
            <= registered.registration_observed_at
        ):
            raise ValueError("native registration observation precedes its actual input")
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, NativeCoordinatorCompleted)
        output = completed.output
        if (
            output.workflow_id != intent.workflow_id
            or output.step_run_id != intent.step_run_id
            or output.receipt_owner_job_id != allocation.receipt_producer.job_id
            or output.receipt.artifact_id != allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.receipt_producer.artifact_revision_id
        ):
            raise ValueError("native completion differs from its actual allocated producer")
