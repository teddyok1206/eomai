"""Canonical tiny checkpoint values; no actual source/producer authority."""

from datetime import timedelta

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
)
from eom_orchestrator.native_embedding_coordinator import native_embedding_index_registration_key
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
    NativeCoordinatorCompleted,
    NativeCoordinatorIndexPrepared,
    NativeCoordinatorRegistered,
    native_coordinator_checkpoint,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture


def coordinator_records(intent=None):
    fixture = receipt_fixture()
    intent = intent or fixture.native.association.intent
    pointer = fixture.receipt.registration_command.index_manifest
    allocation = NativeCoordinatorAllocation(
        index_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "c" * 32,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
        ),
        receipt_producer=NativeArtifactProducerIdentity(
            job_id=fixture.receipt.receipt_owner_job_id,
            artifact_id=fixture.output.receipt.artifact_id,
            artifact_revision_id=fixture.output.receipt.artifact_revision_id,
        ),
        created_at=NOW,
        source_commit="a" * 40,
    )
    body = fixture.receipt.registration_command.model_dump(mode="json")
    body["operation_key"] = native_embedding_index_registration_key(
        intent, body["index_id"], body["index_revision_id"]
    )
    command = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
    body = fixture.receipt.registration_result.model_dump(mode="json")
    body.update(operation_key=command.operation_key, request_sha256=command.request_sha256)
    result = EmbeddingIndexRegistrationResult.model_validate(seal(body, "result_sha256"))
    payloads = (
        ("ALLOCATION", allocation),
        (
            "INDEX_PREPARED",
            NativeCoordinatorIndexPrepared(registration_command=command, index_created_at=NOW),
        ),
        (
            "REGISTERED",
            NativeCoordinatorRegistered(
                registration_result=result, registration_observed_at=NOW + timedelta(seconds=1)
            ),
        ),
        ("COMPLETED", NativeCoordinatorCompleted(output=fixture.output)),
    )
    return tuple(
        native_coordinator_checkpoint(intent, phase, payload) for phase, payload in payloads
    )
