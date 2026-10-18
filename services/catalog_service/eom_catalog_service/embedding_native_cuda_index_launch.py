"""Fixed INDEX unit/entry and canonical non-secret launch values; no dispatch or admission."""

from __future__ import annotations

import re
from pathlib import Path

from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_cuda_index_entry import (
    NativeCudaIndexLaunchPins,
    parse_native_cuda_index_launch_pins,
)

CUDA_INDEX_TEMPLATE = "eom-embedding-native-cuda-index@.service"
CUDA_INDEX_TEMPLATE_SHA256 = (
    "sha256:6a7d5ad3e921d89cd30482ae4e00a5797a0d6a2d16e3b0f61adbf25c316a0bf1"
)
CUDA_INDEX_ENTRY = Path("/usr/local/libexec/eom-embedding-native-cuda-index/entry.py")
CUDA_INDEX_ENTRY_SHA256 = "sha256:0fb389628c322ea9b0cc01ad05c422f44ee637dc3d7883c95344eed425548a8a"
CUDA_INDEX_RUNTIME_ROOT = Path("/run/eom-native-embedding-cuda-index")
_FIELDS = (
    "EOM_CUDA_INDEX_JOB_ID",
    "EOM_CUDA_INDEX_ASSOCIATION_SHA256",
    "EOM_CUDA_INDEX_INPUT_RAW_SHA256",
    "EOM_CUDA_INDEX_EXPIRES_NS",
    "EOM_EMBEDDING_CONFIGURATION_ID",
    "EOM_EMBEDDING_CONFIGURATION_REVISION_ID",
    "EOM_EMBEDDING_CONFIGURATION_SHA256",
    "EOM_EMBEDDING_CONFIGURATION_RAW_SHA256",
    "EOM_EMBEDDING_RECEIPT_RAW_SHA256",
)
_BACKEND_FIELDS = _FIELDS[-5:]


def native_cuda_index_backend_environment_bytes(pins: NativeEmbeddingBackendPins) -> bytes:
    """Fixed deployment pins only; this is not a per-execution launch environment."""
    if type(pins) is not NativeEmbeddingBackendPins:
        raise ValueError("NATIVE_CUDA_INDEX_BACKEND_ENVIRONMENT_INVALID")
    checked = NativeEmbeddingBackendPins(
        pins.configuration_id,
        pins.configuration_revision_id,
        pins.configuration_sha256,
        pins.configuration_raw_sha256,
        pins.receipt_raw_sha256,
    )
    values = (
        checked.configuration_id,
        checked.configuration_revision_id,
        checked.configuration_sha256,
        checked.configuration_raw_sha256,
        checked.receipt_raw_sha256,
    )
    return "".join(
        f"{key}={value}\n" for key, value in zip(_BACKEND_FIELDS, values, strict=True)
    ).encode("ascii")


def native_cuda_index_unit(execution_id: str) -> str:
    if (
        type(execution_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", execution_id, re.ASCII) is None
    ):
        raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_INVALID")
    return CUDA_INDEX_TEMPLATE.replace("@.service", f"@{execution_id}.service")


def native_cuda_index_launch_arguments(pins: NativeCudaIndexLaunchPins) -> tuple[str, ...]:
    """The same closed leaf parser owns validation; none of these fields is authority."""
    if type(pins) is not NativeCudaIndexLaunchPins or type(pins.expires_ns) is not int:
        raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_INVALID")
    arguments = (
        "INDEX",
        pins.execution_id,
        pins.job_id,
        pins.association_sha256,
        pins.input_raw_sha256,
        str(pins.expires_ns),
        pins.configuration_id,
        pins.configuration_revision_id,
        pins.configuration_sha256,
        pins.configuration_raw_sha256,
        pins.receipt_raw_sha256,
    )
    if parse_native_cuda_index_launch_pins(arguments) != pins:
        raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_INVALID")
    return arguments


def native_cuda_index_launch_environment_bytes(pins: NativeCudaIndexLaunchPins) -> bytes:
    """Root writes this once only after original association/launch admission."""
    arguments = native_cuda_index_launch_arguments(pins)
    return "".join(
        f"{key}={value}\n" for key, value in zip(_FIELDS, arguments[2:], strict=True)
    ).encode("ascii")


def parse_native_cuda_index_launch_environment(
    raw: bytes, *, execution_id: str
) -> NativeCudaIndexLaunchPins:
    """Strict inverse for root file readback, not arbitrary systemd EnvironmentFile parsing."""
    if type(raw) is not bytes or not 0 < len(raw) <= 4096:
        raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID")
    native_cuda_index_unit(execution_id)
    try:
        lines = raw.decode("ascii").split("\n")
        if len(lines) != len(_FIELDS) + 1 or lines[-1] != "":
            raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID")
        values = []
        for expected, line in zip(_FIELDS, lines[:-1], strict=True):
            key, separator, value = line.partition("=")
            if key != expected or separator != "=":
                raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID")
            values.append(value)
        pins = parse_native_cuda_index_launch_pins(("INDEX", execution_id, *values))
        if native_cuda_index_launch_environment_bytes(pins) != raw:
            raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID")
        return pins
    except (UnicodeError, ValueError):
        raise ValueError("NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID") from None
