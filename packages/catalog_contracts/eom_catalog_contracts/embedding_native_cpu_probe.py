"""Bounded CPU installation observations, never installation or compute admission."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProofPointer,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalRuntimeDescriptor,
    LegacyEmbeddingPayloadPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

CPU_PROBE_SCHEMA = "embedding-native-cpu-probe"
MAX_CPU_PROBE_BYTES = 64 * 1024
type ExecutionId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)]
type Denial = Literal["DENIED", "ABSENT_IN_SANDBOX"]


class _ProbeEnvelope(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire_values(cls, value: object) -> object:
        return similarity_contract_document(value, CPU_PROBE_SCHEMA, MAX_CPU_PROBE_BYTES)


class NativeCpuProbeInput(_ProbeEnvelope):
    schema_version: Literal["embedding-native-cpu-probe-input/1.0"]
    execution_id: ExecutionId
    profile: Literal["CPU_INDEX_FP32"]
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    payload: LegacyEmbeddingPayloadPointer

    @model_validator(mode="after")
    def cpu_only(self) -> NativeCpuProbeInput:
        if self.installed_proof.profile != "CPU_INDEX_FP32":
            raise ValueError("native CPU probe cannot accept another runtime profile")
        return self


class NativeCpuProbeDenials(FrozenModel):
    """Closed operation names; absence does not claim a DAC enforcement success."""

    nas: Denial
    repository: Denial
    legacy_repository: Denial
    api_configuration: Denial
    root_auth: Denial
    worker_homes: Denial
    image_models: Denial
    api_runtime: Denial
    owner_workspace: Denial
    legacy_handoff: Denial
    probe_workspace: Denial
    gpu: Denial
    postgres: Denial
    docker: Denial
    systemd: Denial
    dbus: Denial
    prefix_write: Literal["DENIED"]
    model_write: Literal["DENIED"]


class NativeCpuProbeResult(_ProbeEnvelope):
    schema_version: Literal["embedding-native-cpu-probe-result/1.0"]
    evidence_state: Literal["OBSERVED_NOT_ADMITTED"]
    recipe: Literal["NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"]
    execution_id: ExecutionId
    input_raw_sha256: Sha256
    pid: int = Field(ge=1, le=2147483647, strict=True)
    worker_uid: int = Field(ge=1, le=4294967294, strict=True)
    worker_gid: int = Field(ge=1, le=4294967294, strict=True)
    supplementary_gids: tuple[int, ...] = Field(max_length=0)
    checked_model_members: int = Field(ge=2, le=32, strict=True)
    payload_file_set_sha256: Sha256
    denials: NativeCpuProbeDenials
    numerical_runtime: EmbeddingNumericalRuntimeDescriptor

    @model_validator(mode="after")
    def cpu_runtime(self) -> NativeCpuProbeResult:
        runtime = self.numerical_runtime
        if (
            runtime.device.kind != "CPU"
            or runtime.torch_build_cuda_version is not None
            or runtime.recipe.batch_size != 4
            or runtime.recipe.threads != 4
        ):
            raise ValueError("native probe observed a different fixed CPU recipe")
        return self


def _canonical_document(raw: bytes) -> object:
    # Equality with canonical bytes rejects duplicates, whitespace, floats and nonfinite values;
    # the shared envelope validation bounds nested values before schema/model construction.
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CPU_PROBE_BYTES:
        raise ValueError("NATIVE_CPU_PROBE_METADATA_INVALID")
    try:
        document: object = json.loads(raw)
        if canonical_json_bytes(document) != raw:
            raise ValueError("noncanonical probe metadata")
        return document
    except (ValueError, TypeError, RecursionError):
        raise ValueError("NATIVE_CPU_PROBE_METADATA_INVALID") from None


def parse_native_cpu_probe_input(raw: bytes) -> NativeCpuProbeInput:
    return NativeCpuProbeInput.model_validate(_canonical_document(raw))


def parse_native_cpu_probe_result(raw: bytes) -> NativeCpuProbeResult:
    return NativeCpuProbeResult.model_validate(_canonical_document(raw))


def validate_native_cpu_probe_association(
    request: NativeCpuProbeInput, request_raw: bytes, result: NativeCpuProbeResult
) -> None:
    """Reference closure only; successful parse cannot prove a real process or its termination."""
    request = NativeCpuProbeInput.model_validate(request)
    result = NativeCpuProbeResult.model_validate(result)
    if (
        parse_native_cpu_probe_input(request_raw) != request
        or result.execution_id != request.execution_id
        or result.input_raw_sha256 != sha256_bytes(request_raw)
        or result.payload_file_set_sha256 != request.payload.file_set_sha256
    ):
        raise ValueError("NATIVE_CPU_PROBE_ASSOCIATION_INVALID")
