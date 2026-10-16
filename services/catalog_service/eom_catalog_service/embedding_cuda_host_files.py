"""Schema boundary over the same stdlib CUDA file owner used before candidate imports."""

from __future__ import annotations

from dataclasses import dataclass, field

from eom_catalog_contracts.embedding_cuda_host_extension import (
    CudaHostExtensionPointer,
    CudaHostExtensionSnapshot,
    parse_cuda_host_extension_bytes,
    validate_cuda_host_extension_pointer,
)
from eom_catalog_contracts.embedding_host_configuration import (
    parse_host_configuration_snapshot_bytes,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service import embedding_cuda_host_capture as capture


@dataclass(frozen=True, slots=True)
class ResolvedCudaHostExtension:
    pointer: CudaHostExtensionPointer
    snapshot: CudaHostExtensionSnapshot
    captured: capture.CapturedCudaHostExtension = field(repr=False, compare=False)

    def assert_unchanged(self) -> None:
        self.captured.assert_unchanged()


def resolve_cuda_host_extension(pointer: CudaHostExtensionPointer) -> ResolvedCudaHostExtension:
    """Read fixed root-local files once; no alternate path, source or execution authority."""
    try:
        pointer = CudaHostExtensionPointer.model_validate(pointer)
        selected = capture.resolve_cuda_host_extension(
            capture.parse_cuda_host_extension_pin(pointer.model_dump(mode="json"))
        )
        snapshot = parse_cuda_host_extension_bytes(selected.snapshot_raw)
        base_raw = selected.base_configuration.snapshot_raw
        base = parse_host_configuration_snapshot_bytes(base_raw)
        validate_cuda_host_extension_pointer(
            pointer, snapshot, selected.snapshot_raw, base, base_raw
        )
        result = ResolvedCudaHostExtension(pointer, snapshot, selected)
        result.assert_unchanged()
        return result
    except capture.CudaHostExtensionError:
        raise
    except (ValueError, TypeError, SchemaError):
        raise capture.CudaHostExtensionError("CUDA_HOST_EXTENSION_POINTER_INVALID") from None
