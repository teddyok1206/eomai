"""Original owner/root launch metadata; parsed values are never execution or source grants."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    BenchmarkDevice,
    BenchmarkOwnerRequest,
    BenchmarkResourceEvidence,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.models import JobId
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message

BENCHMARK_LAUNCH_CONTROL_SCHEMA_REF = (
    "eom://schemas/workflow/embedding-benchmark-launch-control/1.0"
)
MAX_LAUNCH_CONTROL_BYTES = 64 * 1024
BENCHMARK_CONTROL_SECONDS = 210
type _Execution = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
type _Tick = Annotated[int, Field(ge=1, le=2**63 - 1, strict=True)]
type _Pid = Annotated[int, Field(ge=1, le=2**31 - 1, strict=True)]


class BenchmarkLaunchControlError(ValueError):
    def __init__(self) -> None:
        self.code = "BENCHMARK_LAUNCH_CONTROL_INVALID"
        super().__init__(self.code)


def _hash(value: NativeEmbeddingContract, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise BenchmarkLaunchControlError()


def _ordinal(device: str, ordinal: int) -> None:
    if BENCHMARK_DEVICE_SEQUENCE[ordinal - 1] != device:
        raise BenchmarkLaunchControlError()


class BenchmarkRequestMember(NativeEmbeddingContract):
    member_name: Literal["owner-request.json"] = "owner-request.json"
    sha256: Sha256
    byte_count: int = Field(ge=1, le=65536, strict=True)


class BenchmarkInvocationMember(NativeEmbeddingContract):
    member_name: Literal["invocation.json"] = "invocation.json"
    sha256: Sha256
    byte_count: int = Field(ge=1, le=65536, strict=True)


class BenchmarkInputMember(NativeEmbeddingContract):
    member_name: Literal["benchmark-inputs.json"] = "benchmark-inputs.json"
    sha256: Sha256
    byte_count: int = Field(ge=1, le=64 * 1024**2, strict=True)


class BenchmarkControlBackend(NativeEmbeddingContract):
    configuration_id: str = Field(pattern=r"^embeddingnativeconfig_[0-9a-f]{32}$")
    configuration_revision_id: str = Field(pattern=r"^embeddingnativeconfigrev_[0-9a-f]{32}$")
    configuration_sha256: Sha256
    configuration_raw_sha256: Sha256
    receipt_raw_sha256: Sha256


class BenchmarkLaunchAssociation(NativeEmbeddingContract):
    schema_version: Literal["embedding-benchmark-launch-control/1.0"] = (
        "embedding-benchmark-launch-control/1.0"
    )
    record_type: Literal["ASSOCIATION"] = "ASSOCIATION"
    job_id: JobId
    execution_id: _Execution
    device: BenchmarkDevice
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    invocation_sha256: Sha256
    owner_request_sha256: Sha256
    request: BenchmarkRequestMember
    invocation: BenchmarkInvocationMember
    inputs: BenchmarkInputMember
    owner_pid: _Pid
    owner_start_ticks: _Tick
    expires_ns: _Tick
    association_sha256: Sha256

    @model_validator(mode="after")
    def original_launch(self) -> BenchmarkLaunchAssociation:
        _ordinal(self.device, self.launch_ordinal)
        _hash(self, "association_sha256")
        return self


class BenchmarkLaunchPrepared(NativeEmbeddingContract):
    schema_version: Literal["embedding-benchmark-launch-control/1.0"] = (
        "embedding-benchmark-launch-control/1.0"
    )
    record_type: Literal["PREPARED"] = "PREPARED"
    association_sha256: Sha256
    job_id: JobId
    execution_id: _Execution
    invocation_sha256: Sha256
    environment_raw_sha256: Sha256
    controller_release: str = Field(pattern=r"^[0-9a-f]{40}$")
    backend: BenchmarkControlBackend
    prepared_sha256: Sha256

    @model_validator(mode="after")
    def hashed_preparation(self) -> BenchmarkLaunchPrepared:
        _hash(self, "prepared_sha256")
        return self


class BenchmarkLaunchCompleted(NativeEmbeddingContract):
    schema_version: Literal["embedding-benchmark-launch-control/1.0"] = (
        "embedding-benchmark-launch-control/1.0"
    )
    record_type: Literal["COMPLETED"] = "COMPLETED"
    association_sha256: Sha256
    prepared_sha256: Sha256
    job_id: JobId
    execution_id: _Execution
    invocation_sha256: Sha256
    device: BenchmarkDevice
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    original_outcome: Literal["SUCCEEDED", "FAILED"]
    cleanup: Literal["CONFIRMED"] = "CONFIRMED"
    started_ns: _Tick
    completed_ns: _Tick
    resources: BenchmarkResourceEvidence | None
    completion_sha256: Sha256

    @model_validator(mode="after")
    def original_machine_outcome(self) -> BenchmarkLaunchCompleted:
        _ordinal(self.device, self.launch_ordinal)
        if self.completed_ns < self.started_ns or (
            self.device == "CPU" and self.resources is not None
        ):
            raise BenchmarkLaunchControlError()
        if self.device == "CUDA" and (
            self.resources is None
            or self.resources.device != self.device
            or self.resources.invocation_sha256 != self.invocation_sha256
            or self.resources.launch_ordinal != self.launch_ordinal
            or self.resources.owner_observation_count == 0
            or self.resources.peak_whole_process_gpu_bytes is None
            or self.resources.peak_whole_device_gpu_bytes is None
        ):
            raise BenchmarkLaunchControlError()
        _hash(self, "completion_sha256")
        return self


class BenchmarkLaunchUncertain(NativeEmbeddingContract):
    schema_version: Literal["embedding-benchmark-launch-control/1.0"] = (
        "embedding-benchmark-launch-control/1.0"
    )
    record_type: Literal["UNCERTAIN"] = "UNCERTAIN"
    association_sha256: Sha256
    job_id: JobId
    execution_id: _Execution
    invocation_sha256: Sha256
    code: Literal["BENCHMARK_ROOT_EXECUTION_UNCERTAIN"] = "BENCHMARK_ROOT_EXECUTION_UNCERTAIN"
    uncertainty_sha256: Sha256

    @model_validator(mode="after")
    def explicit_uncertainty(self) -> BenchmarkLaunchUncertain:
        _hash(self, "uncertainty_sha256")
        return self


type BenchmarkLaunchControlMessage = Annotated[
    BenchmarkLaunchAssociation
    | BenchmarkLaunchPrepared
    | BenchmarkLaunchCompleted
    | BenchmarkLaunchUncertain,
    Field(discriminator="record_type"),
]
_ADAPTER: TypeAdapter[BenchmarkLaunchControlMessage] = TypeAdapter(BenchmarkLaunchControlMessage)


def parse_benchmark_launch_control(value: object) -> BenchmarkLaunchControlMessage:
    try:
        raw = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("benchmark-launch-control", raw)
        return _ADAPTER.validate_python(raw)
    except Exception:
        raise BenchmarkLaunchControlError() from None


def benchmark_launch_control_bytes(value: BenchmarkLaunchControlMessage) -> bytes:
    checked = parse_benchmark_launch_control(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_benchmark_launch_control_bytes(raw: bytes) -> BenchmarkLaunchControlMessage:
    try:
        value = parse_benchmark_launch_control(
            parse_rootlocal_evidence_document(raw, MAX_LAUNCH_CONTROL_BYTES)
        )
        if benchmark_launch_control_bytes(value) != raw:
            raise BenchmarkLaunchControlError()
        return value
    except Exception:
        raise BenchmarkLaunchControlError() from None


def validate_benchmark_launch_association(
    association: BenchmarkLaunchAssociation,
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
) -> None:
    checked = parse_benchmark_launch_control(association)
    if not isinstance(checked, BenchmarkLaunchAssociation):
        raise BenchmarkLaunchControlError()
    validate_benchmark_invocation(request, invocation, inputs)
    if (
        checked.job_id,
        checked.execution_id,
        checked.device,
        checked.launch_ordinal,
        checked.invocation_sha256,
        checked.owner_request_sha256,
    ) != (
        invocation.job_id,
        invocation.execution_id,
        invocation.device,
        invocation.launch_ordinal,
        invocation.invocation_sha256,
        request.request_sha256,
    ):
        raise BenchmarkLaunchControlError()
    for descriptor, value in (
        (checked.request, request),
        (checked.invocation, invocation),
        (checked.inputs, inputs),
    ):
        raw = embedding_device_benchmark_bytes(value)
        if descriptor.sha256 != sha256_bytes(raw) or descriptor.byte_count != len(raw):
            raise BenchmarkLaunchControlError()


def validate_benchmark_control_reply(
    association: BenchmarkLaunchAssociation,
    value: BenchmarkLaunchPrepared | BenchmarkLaunchCompleted | BenchmarkLaunchUncertain,
    *,
    prepared: BenchmarkLaunchPrepared | None = None,
) -> None:
    association = BenchmarkLaunchAssociation.model_validate(
        raw_similarity_contract_value(association)
    )
    checked = parse_benchmark_launch_control(value)
    if isinstance(checked, BenchmarkLaunchAssociation) or (
        checked.association_sha256,
        checked.job_id,
        checked.execution_id,
        checked.invocation_sha256,
    ) != (
        association.association_sha256,
        association.job_id,
        association.execution_id,
        association.invocation_sha256,
    ):
        raise BenchmarkLaunchControlError()
    if isinstance(checked, BenchmarkLaunchCompleted) and (
        prepared is None
        or checked.prepared_sha256 != prepared.prepared_sha256
        or checked.device != association.device
        or checked.launch_ordinal != association.launch_ordinal
    ):
        raise BenchmarkLaunchControlError()
    if isinstance(checked, BenchmarkLaunchCompleted):
        assert prepared is not None
        validate_benchmark_control_reply(association, prepared)
