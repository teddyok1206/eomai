"""Closed root/native allocation metadata, never actor authority or a lease observation."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cuda_probe import NativeCudaProbeResourceDescriptors
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

EMBEDDING_GPU_CONTROL_SCHEMA = "embedding-gpu-allocation-control"
MAX_EMBEDDING_GPU_CONTROL_BYTES = 32 * 1024
MAX_EMBEDDING_GPU_FENCES = 256
type AllocationAttemptId = Annotated[
    str, Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$", strict=True)
]
type WorkerPid = Annotated[int, Field(ge=1, le=2147483647, strict=True)]
type WorkerIdentity = Annotated[int, Field(ge=1, le=4294967294, strict=True)]
type ProcessBirth = Annotated[int, Field(ge=1, le=18446744073709551615, strict=True)]


class EmbeddingGpuControlError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_GPU_CONTROL_INVALID")


class _ControlMessage(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-gpu-allocation-control/1.0"]
    allocation_attempt_id: AllocationAttemptId
    message_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, EMBEDDING_GPU_CONTROL_SCHEMA, MAX_EMBEDDING_GPU_CONTROL_BYTES
        )

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.message_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"message_sha256"})
        ):
            raise EmbeddingGpuControlError()
        return self


class EmbeddingGpuAllocationRequest(_ControlMessage):
    message_type: Literal["ALLOCATION_REQUEST"]
    parent_request_sha256: Sha256
    child_set_sha256: Sha256
    routing_policy_sha256: Sha256
    purpose: Literal["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"]
    configuration: RootLocalNativeConfigurationPin
    receipt_raw_sha256: Sha256
    expires_monotonic_ns: int = Field(ge=1, le=9223372036854775807, strict=True)


class EmbeddingGpuAllocationReady(_ControlMessage):
    """Only a worker claim; root separately observes actual retained FD/unit identity."""

    message_type: Literal["ALLOCATION_READY"]
    allocation_request_sha256: Sha256
    evidence_state: Literal["RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED"]
    pid: WorkerPid
    start_time_ticks: ProcessBirth
    worker_uid: WorkerIdentity
    worker_gid: WorkerIdentity
    supplementary_gids: tuple[WorkerIdentity, ...] = Field(min_length=1, max_length=1)
    resource_fds: NativeCudaProbeResourceDescriptors
    expected_device_capture: CudaRuntimeDeviceCapture
    fdstore_name: Literal["eom-gpu0-lease"]

    @model_validator(mode="after")
    def lease_group(self) -> Self:
        if self.worker_gid in self.supplementary_gids:
            raise EmbeddingGpuControlError()
        return self


class EmbeddingGpuAllocationBusy(_ControlMessage):
    """Acquire-time BUSY claim, not independently proven numerical nonexecution."""

    message_type: Literal["ALLOCATION_BUSY"]
    allocation_request_sha256: Sha256
    evidence_state: Literal["ALLOCATION_UNAVAILABLE_NOT_EXECUTED"]
    pid: WorkerPid
    start_time_ticks: ProcessBirth
    worker_uid: WorkerIdentity
    worker_gid: WorkerIdentity


class EmbeddingGpuComputeGrant(_ControlMessage):
    message_type: Literal["COMPUTE_GRANT"]
    allocation_request_sha256: Sha256
    ready_message_sha256: Sha256
    routing_decision_sha256: Sha256
    batch_input_raw_sha256: Sha256
    batch_request_sha256: Sha256
    batch_input_byte_count: int = Field(ge=1, le=64 * 1024**2, strict=True)


class EmbeddingGpuCheckChild(_ControlMessage):
    message_type: Literal["CHECK_CHILD"]
    allocation_request_sha256: Sha256
    grant_message_sha256: Sha256
    batch_request_sha256: Sha256
    child_request_sha256: Sha256
    sequence: int = Field(ge=1, le=MAX_EMBEDDING_GPU_FENCES, strict=True)


class EmbeddingGpuFenceAck(_ControlMessage):
    message_type: Literal["FENCE_ACK"]
    allocation_request_sha256: Sha256
    grant_message_sha256: Sha256
    batch_request_sha256: Sha256
    child_request_sha256: Sha256
    sequence: int = Field(ge=1, le=MAX_EMBEDDING_GPU_FENCES, strict=True)
    check_message_sha256: Sha256


class EmbeddingGpuResultReady(_ControlMessage):
    """Local output claim, never original-unit success, safe retirement or publication."""

    message_type: Literal["RESULT_READY"]
    allocation_request_sha256: Sha256
    grant_message_sha256: Sha256
    batch_request_sha256: Sha256
    result_raw_sha256: Sha256
    result_sha256: Sha256
    vectors_sha256: Sha256
    result_byte_count: int = Field(ge=1, le=64 * 1024**2, strict=True)
    vectors_byte_count: int = Field(ge=4, le=16 * 1024**2, strict=True)


class EmbeddingGpuResultAck(_ControlMessage):
    """Root verified local output, not publication or proven GPU retirement."""

    message_type: Literal["RESULT_ACK"]
    allocation_request_sha256: Sha256
    grant_message_sha256: Sha256
    batch_request_sha256: Sha256
    result_message_sha256: Sha256


type EmbeddingGpuControlMessage = Annotated[
    EmbeddingGpuAllocationRequest
    | EmbeddingGpuAllocationReady
    | EmbeddingGpuAllocationBusy
    | EmbeddingGpuComputeGrant
    | EmbeddingGpuCheckChild
    | EmbeddingGpuFenceAck
    | EmbeddingGpuResultReady
    | EmbeddingGpuResultAck,
    Field(discriminator="message_type"),
]


def parse_embedding_gpu_control(value: object) -> EmbeddingGpuControlMessage:
    try:
        return TypeAdapter(EmbeddingGpuControlMessage).validate_python(
            raw_similarity_contract_value(value)
        )
    except Exception:
        raise EmbeddingGpuControlError() from None


def embedding_gpu_control_bytes(value: EmbeddingGpuControlMessage) -> bytes:
    return canonical_json_bytes(parse_embedding_gpu_control(value).model_dump(mode="json"))


def parse_embedding_gpu_control_bytes(raw: bytes) -> EmbeddingGpuControlMessage:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EMBEDDING_GPU_CONTROL_BYTES:
            raise EmbeddingGpuControlError()
        value = parse_embedding_gpu_control(json.loads(raw))
        if embedding_gpu_control_bytes(value) != raw:
            raise EmbeddingGpuControlError()
        return value
    except Exception:
        raise EmbeddingGpuControlError() from None


def validate_embedding_gpu_allocation_link(
    request: EmbeddingGpuAllocationRequest,
    reply: EmbeddingGpuAllocationReady | EmbeddingGpuAllocationBusy,
) -> None:
    if type(reply) not in (EmbeddingGpuAllocationReady, EmbeddingGpuAllocationBusy):
        raise EmbeddingGpuControlError()
    request = EmbeddingGpuAllocationRequest.model_validate(raw_similarity_contract_value(request))
    reply = type(reply).model_validate(raw_similarity_contract_value(reply))
    if (
        reply.allocation_attempt_id != request.allocation_attempt_id
        or reply.allocation_request_sha256 != request.message_sha256
    ):
        raise EmbeddingGpuControlError()


def validate_embedding_gpu_grant(
    request: EmbeddingGpuAllocationRequest,
    ready: EmbeddingGpuAllocationReady,
    grant: EmbeddingGpuComputeGrant,
) -> None:
    if type(ready) is not EmbeddingGpuAllocationReady:
        raise EmbeddingGpuControlError()
    validate_embedding_gpu_allocation_link(request, ready)
    grant = EmbeddingGpuComputeGrant.model_validate(raw_similarity_contract_value(grant))
    if (
        grant.allocation_attempt_id != request.allocation_attempt_id
        or grant.allocation_request_sha256 != request.message_sha256
        or grant.ready_message_sha256 != ready.message_sha256
    ):
        raise EmbeddingGpuControlError()


def validate_embedding_gpu_batch_grant(
    request: EmbeddingGpuAllocationRequest,
    grant: EmbeddingGpuComputeGrant,
    batch: EmbeddingWorkBatchInput,
    *,
    input_raw_sha256: str,
    input_byte_count: int,
) -> None:
    """Actual bounded FD read supplies raw SHA/count; no source authority is inferred."""
    request = EmbeddingGpuAllocationRequest.model_validate(raw_similarity_contract_value(request))
    grant = EmbeddingGpuComputeGrant.model_validate(raw_similarity_contract_value(grant))
    batch = parse_embedding_work_batch_input(batch)
    if (
        grant.allocation_attempt_id != request.allocation_attempt_id
        or grant.allocation_request_sha256 != request.message_sha256
        or batch.purpose
        != {"INDEX": "DOCUMENT", "REFERENCE_QUERY": "REFERENCE_QUERY"}.get(request.purpose)
        or type(input_byte_count) is not int
        or grant.batch_input_raw_sha256 != input_raw_sha256
        or grant.batch_input_byte_count != input_byte_count
        or grant.batch_request_sha256 != batch.request_sha256
        or grant.routing_decision_sha256 != batch.routing_decision_sha256
        or any(child.space.runtime.device != "CUDA" for child in batch.children)
    ):
        raise EmbeddingGpuControlError()


def validate_embedding_gpu_fence_ack(
    grant: EmbeddingGpuComputeGrant,
    check: EmbeddingGpuCheckChild,
    ack: EmbeddingGpuFenceAck,
) -> None:
    grant = EmbeddingGpuComputeGrant.model_validate(raw_similarity_contract_value(grant))
    check = EmbeddingGpuCheckChild.model_validate(raw_similarity_contract_value(check))
    ack = EmbeddingGpuFenceAck.model_validate(raw_similarity_contract_value(ack))
    for value in (check, ack):
        if (
            value.allocation_attempt_id != grant.allocation_attempt_id
            or value.allocation_request_sha256 != grant.allocation_request_sha256
            or value.grant_message_sha256 != grant.message_sha256
            or value.batch_request_sha256 != grant.batch_request_sha256
        ):
            raise EmbeddingGpuControlError()
    if (
        ack.check_message_sha256 != check.message_sha256
        or ack.child_request_sha256 != check.child_request_sha256
        or ack.sequence != check.sequence
    ):
        raise EmbeddingGpuControlError()


def validate_embedding_gpu_result_ack(
    grant: EmbeddingGpuComputeGrant,
    result: EmbeddingGpuResultReady,
    ack: EmbeddingGpuResultAck,
) -> None:
    grant = EmbeddingGpuComputeGrant.model_validate(raw_similarity_contract_value(grant))
    result = EmbeddingGpuResultReady.model_validate(raw_similarity_contract_value(result))
    ack = EmbeddingGpuResultAck.model_validate(raw_similarity_contract_value(ack))
    for value in (result, ack):
        if (
            value.allocation_attempt_id != grant.allocation_attempt_id
            or value.allocation_request_sha256 != grant.allocation_request_sha256
            or value.grant_message_sha256 != grant.message_sha256
            or value.batch_request_sha256 != grant.batch_request_sha256
        ):
            raise EmbeddingGpuControlError()
    if ack.result_message_sha256 != result.message_sha256:
        raise EmbeddingGpuControlError()
