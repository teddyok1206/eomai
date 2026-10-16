"""Schema/Pydantic boundary for the shared stdlib protected host capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    EmbeddingHostConfigurationSnapshot,
    parse_host_configuration_pointer,
    parse_host_configuration_snapshot_bytes,
    validate_host_configuration_pointer,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service import embedding_host_configuration_capture as capture
from eom_catalog_service.embedding_host_configuration_capture import (
    EmbeddingHostSnapshotMount as EmbeddingHostSnapshotMount,
)
from eom_catalog_service.embedding_host_configuration_capture import (
    HostConfigurationSnapshotError as HostConfigurationSnapshotError,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_host_closure import ProtectedEmbeddingHostClosure


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingHostConfiguration:
    pointer: EmbeddingHostConfigurationPointer
    snapshot: EmbeddingHostConfigurationSnapshot
    cache_path: Path
    cache_identity: tuple[int, ...]
    files: NumericalRuntimeFileSnapshots = field(repr=False, compare=False)

    @property
    def baseline_host_seed_sha256(self) -> str:
        return self.snapshot.baseline_host_seed_sha256

    @property
    def host_seed_sha256(self) -> str:
        return self.snapshot.host_seed_sha256

    @property
    def cache_byte_count(self) -> int:
        return self.snapshot.loader_cache.byte_count

    @property
    def cache_sha256(self) -> str:
        return self.snapshot.loader_cache.sha256

    def assert_unchanged(self) -> None:
        capture.assert_host_configuration_files_current(self)


def resolve_host_configuration_snapshot(
    pointer: EmbeddingHostConfigurationPointer,
) -> ResolvedEmbeddingHostConfiguration:
    """Validate the wire contract, then capture the same fixed files as root bootstrap."""
    try:
        pointer = parse_host_configuration_pointer(pointer)
        selected = capture.resolve_host_configuration_snapshot(
            capture.parse_host_configuration_snapshot_pin(pointer.model_dump(mode="json"))
        )
        snapshot = parse_host_configuration_snapshot_bytes(selected.snapshot_raw)
        validate_host_configuration_pointer(pointer, snapshot, selected.snapshot_raw)
        resolved = ResolvedEmbeddingHostConfiguration(
            pointer, snapshot, selected.cache_path, selected.cache_identity, selected.files
        )
        resolved.assert_unchanged()
        return resolved
    except HostConfigurationSnapshotError:
        raise
    except (ValueError, SchemaError, TypeError):
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_POINTER_INVALID") from None


def require_host_configuration_snapshot_mount(
    resolved: ResolvedEmbeddingHostConfiguration,
) -> EmbeddingHostSnapshotMount[ResolvedEmbeddingHostConfiguration]:
    if type(resolved) is not ResolvedEmbeddingHostConfiguration:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_POINTER_INVALID")
    return capture.require_host_configuration_snapshot_mount(resolved)


def capture_snapshot_embedding_host(
    *,
    expected_seed_sha256: str,
    files: NumericalRuntimeFileSnapshots,
    snapshot_mount: EmbeddingHostSnapshotMount[ResolvedEmbeddingHostConfiguration],
) -> ProtectedEmbeddingHostClosure:
    """Use one OS-only checker after the normal exact schema/model resolution boundary."""
    if (
        type(snapshot_mount) is not EmbeddingHostSnapshotMount
        or type(snapshot_mount.configuration) is not ResolvedEmbeddingHostConfiguration
    ):
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_MOUNT_INVALID")
    return capture.capture_snapshot_embedding_host(
        expected_seed_sha256=expected_seed_sha256, files=files, snapshot_mount=snapshot_mount
    )
