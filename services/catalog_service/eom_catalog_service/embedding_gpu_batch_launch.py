"""Fixed non-secret native launch pins, never source permission or a GPU grant."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins

GPU_BATCH_TEMPLATE = "eom-embedding-native-gpu-batch@.service"
GPU_BATCH_SOCKET_TEMPLATE = "eom-embedding-native-gpu-batch@.socket"
GPU_BATCH_RUNTIME_ROOT = Path("/run/eom-native-embedding-gpu-batch")
_FIELDS = (
    "EOM_GPU_BATCH_ALLOCATION_RAW_SHA256",
    "EOM_GPU_BATCH_ROOT_PID",
    "EOM_GPU_BATCH_RESOURCE_PROFILE_SHA256",
    "EOM_GPU_BATCH_TIMEOUT_SECONDS",
    "EOM_GPU_BATCH_VECTOR_MAX_BYTES",
    "EOM_GPU_BATCH_TOTAL_OUTPUT_MAX_BYTES",
    "EOM_EMBEDDING_CONFIGURATION_ID",
    "EOM_EMBEDDING_CONFIGURATION_REVISION_ID",
    "EOM_EMBEDDING_CONFIGURATION_SHA256",
    "EOM_EMBEDDING_CONFIGURATION_RAW_SHA256",
    "EOM_EMBEDDING_RECEIPT_RAW_SHA256",
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_LAUNCH_INVALID")


def native_embedding_gpu_batch_unit(attempt_hex: str) -> str:
    _require(
        type(attempt_hex) is str
        and re.fullmatch(r"[0-9a-f]{32}", attempt_hex, re.ASCII) is not None
    )
    return GPU_BATCH_TEMPLATE.replace("@.service", f"@{attempt_hex}.service")


@dataclass(frozen=True, slots=True)
class NativeEmbeddingGpuBatchLaunchPins:
    attempt_hex: str
    allocation_raw_sha256: str
    root_pid: int
    resource_profile_sha256: str
    timeout_seconds: int
    vector_max_bytes: int
    total_output_max_bytes: int
    backend: NativeEmbeddingBackendPins

    def __post_init__(self) -> None:
        native_embedding_gpu_batch_unit(self.attempt_hex)
        for digest in (self.allocation_raw_sha256, self.resource_profile_sha256):
            _require(
                type(digest) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest, re.ASCII) is not None
            )
        for value, minimum, maximum in (
            (self.root_pid, 1, 2147483647),
            (self.timeout_seconds, 1, 180),
            (self.vector_max_bytes, 4, 16 * 1024**2),
            (self.total_output_max_bytes, 5, 64 * 1024**2),
        ):
            _require(type(value) is int and minimum <= value <= maximum)
        _require(self.total_output_max_bytes > self.vector_max_bytes)
        _require(type(self.backend) is NativeEmbeddingBackendPins)
        self.backend.__post_init__()


def parse_native_embedding_gpu_batch_launch(
    arguments: tuple[str, ...],
) -> NativeEmbeddingGpuBatchLaunchPins:
    _require(
        type(arguments) is tuple
        and len(arguments) == 12
        and all(type(value) is str for value in arguments)
    )
    attempt, raw, pid, profile, timeout, vectors, output, *backend = arguments
    for value in (pid, timeout, vectors, output):
        _require(re.fullmatch(r"[1-9][0-9]{0,9}", value, re.ASCII) is not None)
    return NativeEmbeddingGpuBatchLaunchPins(
        attempt,
        raw,
        int(pid),
        profile,
        int(timeout),
        int(vectors),
        int(output),
        NativeEmbeddingBackendPins(*backend),
    )


def native_embedding_gpu_batch_launch_arguments(
    pins: NativeEmbeddingGpuBatchLaunchPins,
) -> tuple[str, ...]:
    _require(type(pins) is NativeEmbeddingGpuBatchLaunchPins)
    pins.__post_init__()
    return (
        pins.attempt_hex,
        pins.allocation_raw_sha256,
        str(pins.root_pid),
        pins.resource_profile_sha256,
        str(pins.timeout_seconds),
        str(pins.vector_max_bytes),
        str(pins.total_output_max_bytes),
        pins.backend.configuration_id,
        pins.backend.configuration_revision_id,
        pins.backend.configuration_sha256,
        pins.backend.configuration_raw_sha256,
        pins.backend.receipt_raw_sha256,
    )


def native_embedding_gpu_batch_environment(pins: NativeEmbeddingGpuBatchLaunchPins) -> bytes:
    arguments = native_embedding_gpu_batch_launch_arguments(pins)
    return "".join(
        f"{name}={value}\n" for name, value in zip(_FIELDS, arguments[1:], strict=True)
    ).encode("ascii")


def parse_native_embedding_gpu_batch_environment(
    raw: bytes, *, attempt_hex: str
) -> NativeEmbeddingGpuBatchLaunchPins:
    _require(type(raw) is bytes and 0 < len(raw) <= 4096)
    try:
        lines = raw.decode("ascii").split("\n")
        _require(len(lines) == len(_FIELDS) + 1 and lines[-1] == "")
        values = []
        for field, line in zip(_FIELDS, lines[:-1], strict=True):
            name, separator, value = line.partition("=")
            _require(name == field and separator == "=")
            values.append(value)
        pins = parse_native_embedding_gpu_batch_launch((attempt_hex, *values))
        _require(native_embedding_gpu_batch_environment(pins) == raw)
        return pins
    except (ValueError, UnicodeError):
        raise ValueError("EMBEDDING_GPU_BATCH_LAUNCH_INVALID") from None
