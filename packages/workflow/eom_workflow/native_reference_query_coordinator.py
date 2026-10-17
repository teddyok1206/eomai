"""Bounded QUERY continuation values; never a permission or inference grant."""

from __future__ import annotations

from typing import Literal, Self

from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import REFERENCE_QUERY_INPUT_V11_REF
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.models import JobId
from eom_workflow.native_embedding_coordinator import NativeArtifactProducerIdentity
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowReceipt,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_reference_query_workflow_receipt,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_step_output,
)
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_native_reference_query_checkpoint,
    validate_native_reference_query_checkpoint_v11,
)

type NativeQueryPhase = Literal["ALLOCATION", "EXECUTED", "PUBLISHED", "COMPLETED"]
NATIVE_QUERY_PHASES: tuple[NativeQueryPhase, ...] = (
    "ALLOCATION",
    "EXECUTED",
    "PUBLISHED",
    "COMPLETED",
)


class NativeQueryAllocation(NativeEmbeddingContract):
    query_producer: NativeArtifactProducerIdentity
    receipt_producer: NativeArtifactProducerIdentity
    created_at: UtcDatetime
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def distinct_producers(self) -> NativeQueryAllocation:
        if any(
            getattr(self.query_producer, field) == getattr(self.receipt_producer, field)
            for field in ("job_id", "artifact_id", "artifact_revision_id")
        ):
            raise ValueError("QUERY publication identities repeat")
        return self


class NativeQueryUnitCompletion(NativeEmbeddingContract):
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    started_monotonic: int = Field(strict=True, ge=1, le=2**63 - 1)
    exited_monotonic: int = Field(strict=True, ge=1, le=2**63 - 1)

    @model_validator(mode="after")
    def ordered(self) -> NativeQueryUnitCompletion:
        if self.exited_monotonic < self.started_monotonic:
            raise ValueError("QUERY unit completion precedes start")
        return self


class NativeQueryExecutedObservation(NativeEmbeddingContract):
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    prepare: NativeQueryUnitCompletion
    query: NativeQueryUnitCompletion
    cpu_environment_sha256: Sha256
    owner_environment_sha256: Sha256
    result_sha256: Sha256
    completed_observed_at: UtcDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.prepare.invocation_id == self.query.invocation_id
            or self.query.started_monotonic < self.prepare.exited_monotonic
        ):
            raise ValueError("QUERY unit invocations or dependency order differ")
        return self


class NativeQueryExecuted(NativeQueryExecutedObservation):
    prepare_template_sha256: Literal[
        "sha256:4194d01ea9cffbc5468aac5f5f174303952e1008f8a8621ad1adea07ef76905f"
    ]
    query_template_sha256: Literal[
        "sha256:1bd18e257988df4b3e39eb486e208b999ae7e9e897905ca07f513fc5f3e7893b"
    ]


class NativeQueryExecutedV11(NativeQueryExecutedObservation):
    prepare_template_sha256: Literal[
        "sha256:bbd6ca87732f9a8f0c19e1a6892bdf8d41ed08b1f1473d50918dfde0e7890ec7"
    ]
    query_template_sha256: Literal[
        "sha256:2335f5100b7678a202f67c334d2a8c196d04a77b2f2fa73d591a31a3a82533e8"
    ]


type SupportedNativeQueryExecuted = NativeQueryExecuted | NativeQueryExecutedV11
type NativeQueryCheckpointVersion = Literal[
    "native-reference-query-coordinator/1.0", "native-reference-query-coordinator/1.1"
]


class NativeQueryPublished(NativeEmbeddingContract):
    query_owner_job_id: JobId
    input: ArtifactMemberPointer
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: Sha256
    published_observed_at: UtcDatetime

    @model_validator(mode="after")
    def exact_file_set(self) -> NativeQueryPublished:
        expected = (
            (self.input, "input.json", REFERENCE_QUERY_INPUT_V11_REF, "application/json"),
            (self.result, "result.json", REFERENCE_QUERY_RESULT_REF, "application/json"),
            (self.shard, "shard.json", SHARD_SCHEMA_REF, "application/json"),
            (
                self.binary,
                "vectors.f32",
                "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                "application/octet-stream",
            ),
        )
        if len({(p.artifact_id, p.artifact_revision_id) for p, *_ in expected}) != 1 or any(
            (p.member_path, p.schema_ref, p.media_type) != (name, schema, media)
            for p, name, schema, media in expected
        ):
            raise ValueError("QUERY checkpoint file set differs")
        return self


class NativeQueryCompleted(NativeEmbeddingContract):
    output: ReferenceQueryStepOutput


type NativeQueryPayload = (
    NativeQueryAllocation | NativeQueryExecuted | NativeQueryPublished | NativeQueryCompleted
)
type NativeQueryPayloadV11 = (
    NativeQueryAllocation | NativeQueryExecutedV11 | NativeQueryPublished | NativeQueryCompleted
)
type SupportedNativeQueryPayload = NativeQueryPayload | NativeQueryExecutedV11
_PAYLOADS = {
    "ALLOCATION": NativeQueryAllocation,
    "EXECUTED": NativeQueryExecuted,
    "PUBLISHED": NativeQueryPublished,
    "COMPLETED": NativeQueryCompleted,
}
_PAYLOADS_V11 = {**_PAYLOADS, "EXECUTED": NativeQueryExecutedV11}


class NativeReferenceQueryCheckpoint(NativeEmbeddingContract):
    schema_version: Literal["native-reference-query-coordinator/1.0"] = (
        "native-reference-query-coordinator/1.0"
    )
    record_type: NativeQueryPhase
    native_launch_job_id: JobId
    association_sha256: Sha256
    payload: NativeQueryPayload
    checkpoint_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_native_reference_query_checkpoint(value)
        return value

    @model_validator(mode="after")
    def exact_stage(self) -> NativeReferenceQueryCheckpoint:
        _validate_checkpoint_stage(self)
        return self


class NativeReferenceQueryCheckpointV11(NativeEmbeddingContract):
    schema_version: Literal["native-reference-query-coordinator/1.1"] = (
        "native-reference-query-coordinator/1.1"
    )
    record_type: NativeQueryPhase
    native_launch_job_id: JobId
    association_sha256: Sha256
    payload: NativeQueryPayloadV11
    checkpoint_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_native_reference_query_checkpoint_v11(value)
        return value

    @model_validator(mode="after")
    def exact_stage(self) -> NativeReferenceQueryCheckpointV11:
        _validate_checkpoint_stage(self)
        return self


type SupportedNativeReferenceQueryCheckpoint = (
    NativeReferenceQueryCheckpoint | NativeReferenceQueryCheckpointV11
)


def _validate_checkpoint_stage(value: SupportedNativeReferenceQueryCheckpoint) -> None:
    payloads = _PAYLOADS_V11 if isinstance(value, NativeReferenceQueryCheckpointV11) else _PAYLOADS
    if (
        type(value.payload) is not payloads[value.record_type]
        or value.checkpoint_sha256
        != content_sha256(value.model_dump(mode="json", exclude={"checkpoint_sha256"}))
        or (
            isinstance(value.payload, NativeQueryAllocation)
            and value.native_launch_job_id
            in {value.payload.query_producer.job_id, value.payload.receipt_producer.job_id}
        )
    ):
        raise ValueError("QUERY checkpoint stage, hash or identity differs")


def parse_native_reference_query_checkpoint(value: object) -> NativeReferenceQueryCheckpoint:
    validate_native_reference_query_checkpoint(value)
    return NativeReferenceQueryCheckpoint.model_validate(value)


def parse_supported_native_reference_query_checkpoint(
    value: object,
) -> SupportedNativeReferenceQueryCheckpoint:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("QUERY checkpoint must be an object")
    if document.get("schema_version") == "native-reference-query-coordinator/1.0":
        return parse_native_reference_query_checkpoint(document)
    if document.get("schema_version") == "native-reference-query-coordinator/1.1":
        return NativeReferenceQueryCheckpointV11.model_validate(document)
    raise ValueError("QUERY checkpoint version is unsupported")


def native_reference_query_checkpoint(
    launch: ReferenceQueryLaunchAssociation, phase: NativeQueryPhase, payload: NativeQueryPayload
) -> NativeReferenceQueryCheckpoint:
    launch = parse_reference_query_launch_association(launch)
    if phase not in _PAYLOADS or type(payload) is not _PAYLOADS[phase]:
        raise ValueError("QUERY checkpoint payload purpose differs")
    payload = _PAYLOADS[phase].model_validate(payload)
    body = {
        "schema_version": "native-reference-query-coordinator/1.0",
        "record_type": phase,
        "native_launch_job_id": launch.native_launch_job_id,
        "association_sha256": launch.association_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    return parse_native_reference_query_checkpoint(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def native_reference_query_continuation_checkpoint(
    launch: ReferenceQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: SupportedNativeQueryPayload,
    *,
    previous: tuple[SupportedNativeReferenceQueryCheckpoint, ...],
    initial_version: NativeQueryCheckpointVersion,
) -> SupportedNativeReferenceQueryCheckpoint:
    """Pin once at allocation; never reinterpret existing records under the current release."""
    checked = tuple(parse_supported_native_reference_query_checkpoint(row) for row in previous)
    version = checked[0].schema_version if checked else initial_version
    if any(row.schema_version != version for row in checked):
        raise ValueError("QUERY checkpoint families are mixed")
    launch = parse_reference_query_launch_association(launch)
    if any(
        row.native_launch_job_id != launch.native_launch_job_id
        or row.association_sha256 != launch.association_sha256
        for row in checked
    ):
        raise ValueError("QUERY checkpoint belongs to another launch")
    if version not in {
        "native-reference-query-coordinator/1.0",
        "native-reference-query-coordinator/1.1",
    }:
        raise ValueError("QUERY checkpoint version is unsupported")
    payloads = _PAYLOADS_V11 if version == "native-reference-query-coordinator/1.1" else _PAYLOADS
    if phase not in payloads or type(payload) is not payloads[phase]:
        raise ValueError("QUERY checkpoint payload/runtime family differs")
    payload = payloads[phase].model_validate(payload)
    body = {
        "schema_version": version,
        "record_type": phase,
        "native_launch_job_id": launch.native_launch_job_id,
        "association_sha256": launch.association_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    return parse_supported_native_reference_query_checkpoint(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def reference_query_checkpoint_receipt(
    request: SupportedReferenceQueryWorkflowRequest,
    launch: ReferenceQueryLaunchAssociation,
    allocation: NativeQueryAllocation,
    executed: SupportedNativeQueryExecuted,
    published: NativeQueryPublished,
) -> ReferenceQueryWorkflowReceipt:
    """Reconstruct immutable small metadata, not validation of an actual publication."""
    body = {
        "schema_version": "reference-query-workflow-receipt/1.0",
        "purpose": "REFERENCE_QUERY",
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "step_key": launch.step_key,
        "attempt": launch.attempt,
        "workflow_definition_sha256": request.workflow_definition_sha256,
        "workflow_request_sha256": request.request_sha256,
        "context_request_sha256": request.context_request.request_sha256,
        "receipt_owner_job_id": allocation.receipt_producer.job_id,
        "query_artifact_owner_job_id": published.query_owner_job_id,
        "native_launch_job_id": launch.native_launch_job_id,
        "launch_association_sha256": launch.association_sha256,
        "execution_result_schema": "embedding-reference-query-result@1.0",
        "query_input": published.input.model_dump(mode="json"),
        "query_execution": {
            "job_id": launch.native_launch_job_id,
            "query_request_id": launch.query_request_id,
            "request_sha256": launch.query_request_sha256,
            "input_set_sha256": launch.query_input_set_sha256,
            "result_member": published.result.model_dump(mode="json"),
            "result_sha256": executed.result_sha256,
        },
        "shard": published.shard.model_dump(mode="json"),
        "binary": published.binary.model_dump(mode="json"),
        "runtime_bundle": request.runtime_bundle.model_dump(mode="json"),
        "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
        "published_at": published.published_observed_at.isoformat().replace("+00:00", "Z"),
    }
    return parse_reference_query_workflow_receipt(body | {"receipt_sha256": content_sha256(body)})


def validate_native_reference_query_history(
    records: tuple[SupportedNativeReferenceQueryCheckpoint, ...],
    launch: ReferenceQueryLaunchAssociation,
    request: SupportedReferenceQueryWorkflowRequest,
) -> None:
    launch = parse_reference_query_launch_association(launch)
    request = parse_supported_reference_query_workflow_request(request)
    if (
        len(records) > 4
        or tuple(r.record_type for r in records) != NATIVE_QUERY_PHASES[: len(records)]
    ):
        raise ValueError("QUERY checkpoint history is not a contiguous prefix")
    checked = tuple(parse_supported_native_reference_query_checkpoint(row) for row in records)
    if checked and any(row.schema_version != checked[0].schema_version for row in checked):
        raise ValueError("QUERY checkpoint families are mixed")
    if (
        launch.workflow_request_sha256 != request.request_sha256
        or launch.context_request_sha256 != request.context_request.request_sha256
        or launch.runtime_bundle != request.runtime_bundle
        or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
    ) or any(
        row.native_launch_job_id != launch.native_launch_job_id
        or row.association_sha256 != launch.association_sha256
        for row in checked
    ):
        raise ValueError("QUERY checkpoint belongs to another launch")
    if not checked:
        return
    allocation = checked[0].payload
    assert isinstance(allocation, NativeQueryAllocation)
    if allocation.created_at < launch.launched_at:
        raise ValueError("QUERY allocation precedes original launch")
    if len(checked) < 2:
        return
    executed = checked[1].payload
    assert isinstance(executed, (NativeQueryExecuted, NativeQueryExecutedV11))
    if executed.completed_observed_at < allocation.created_at:
        raise ValueError("QUERY execution observation precedes allocation")
    if len(checked) < 3:
        return
    published = checked[2].payload
    assert isinstance(published, NativeQueryPublished)
    if (
        published.query_owner_job_id != allocation.query_producer.job_id
        or published.input.artifact_id != allocation.query_producer.artifact_id
        or published.input.artifact_revision_id != allocation.query_producer.artifact_revision_id
        or published.published_observed_at < executed.completed_observed_at
    ):
        raise ValueError("QUERY publication differs from allocation or execution order")
    receipt = reference_query_checkpoint_receipt(request, launch, allocation, executed, published)
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, NativeQueryCompleted)
        output = completed.output
        if (
            output.receipt.artifact_id != allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.receipt_producer.artifact_revision_id
            or output.receipt.sha256
            != sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))
        ):
            raise ValueError("QUERY completion differs from receipt allocation")
        validate_reference_query_step_output(output, receipt)
