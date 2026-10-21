"""Composition of captured CPU tools and six FD-held CUDA libraries, not device admission."""

from __future__ import annotations

import os
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from types import MappingProxyType

from eom_catalog_service import embedding_runtime_host_closure as base_host
from eom_catalog_service.embedding_cuda_host_capture import CapturedCudaHostExtension
from eom_catalog_service.embedding_host_configuration_capture import EmbeddingHostSnapshotMount
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    require_runtime_proof,
)


def _require(condition: bool, code: str) -> None:
    require_runtime_proof(condition, "CUDA_HOST_" + code)


class ProtectedCudaEmbeddingHostClosure:
    """One actual captured namespace; metadata and this object confer no GPU/model permission."""

    def __init__(
        self,
        base: base_host.ProtectedEmbeddingHostClosure,
        snapshot_mount: EmbeddingHostSnapshotMount[CapturedCudaHostExtension],
        stack: ExitStack,
        descriptors: tuple[tuple[Path, int, tuple[int, ...]], ...],
        metadata: tuple[base_host.EmbeddingElfMetadata, ...],
    ) -> None:
        self._base, self._mount, self._stack = base, snapshot_mount, stack
        self._descriptors = MappingProxyType({path: (fd, epoch) for path, fd, epoch in descriptors})
        self._versions = MappingProxyType({item.soname: item.definitions for item in metadata})
        self.seed_sha256 = snapshot_mount.configuration.host_seed_sha256
        self._closed = False

    def __enter__(self) -> ProtectedCudaEmbeddingHostClosure:
        self.assert_current()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self.assert_current()
            finally:
                self._closed = True
                try:
                    self._stack.close()
                finally:
                    self._base.close()

    def assert_current(self) -> None:
        _require(not self._closed, "CLOSED")
        self._mount.assert_unchanged()
        self._base.assert_current()
        try:
            for path, (descriptor, epoch) in self._descriptors.items():
                _require(
                    base_host._identity(os.fstat(descriptor))
                    == base_host._identity(path.lstat())
                    == epoch,
                    "FD_CHANGED",
                )
                base_host._no_capability(descriptor)
        except OSError:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CUDA_HOST_FD_UNAVAILABLE") from None

    def open_zstd(self) -> subprocess.Popen[bytes]:
        self.assert_current()
        return self._base.open_zstd()

    def inspect_elf(self, descriptor: int, *, deadline: float) -> bytes:
        self.assert_current()
        raw = self._base.inspect_elf(descriptor, deadline=deadline)
        self.assert_current()
        return raw

    def fixed_loader_path(self) -> Path:
        self.assert_current()
        return self._base.fixed_loader_path()

    def fixed_soname_versions(self, name: str) -> frozenset[str]:
        self.assert_current()
        _require(type(name) is str, "SONAME_INVALID")
        versions = self._versions.get(name)
        return self._base.fixed_soname_versions(name) if versions is None else versions

    def assert_absent_search_route(self, route: str) -> None:
        self.assert_current()
        self._base.assert_absent_search_route(route)

    def assert_mapped_file(self, path: Path, *, device: int, inode: int) -> None:
        self.assert_current()
        _require(
            type(device) is int and type(inode) is int and device >= 0 and inode > 0,
            "MAPPED_FILE_INVALID",
        )
        entry = self._descriptors.get(path)
        if entry is None:
            self._base.assert_mapped_file(path, device=device, inode=inode)
            return
        descriptor, epoch = entry
        _require(
            epoch[:2] == (device, inode) and os.pread(descriptor, 4, 0) == b"\x7fELF",
            "MAPPED_FILE_UNAVAILABLE",
        )


def capture_cuda_embedding_host(
    *,
    expected_seed_sha256: str,
    files: NumericalRuntimeFileSnapshots,
    snapshot_mount: EmbeddingHostSnapshotMount[CapturedCudaHostExtension],
) -> ProtectedCudaEmbeddingHostClosure:
    """No candidate code/ELF loading; inspect held library FDs with captured fixed readelf."""
    _require(
        type(snapshot_mount) is EmbeddingHostSnapshotMount
        and type(snapshot_mount.configuration) is CapturedCudaHostExtension
        and type(files) is NumericalRuntimeFileSnapshots,
        "CAPTURE_INVALID",
    )
    snapshot_mount.assert_unchanged()
    captured = snapshot_mount.configuration
    _require(
        type(expected_seed_sha256) is str
        and expected_seed_sha256 == captured.host_seed_sha256
        and files.owner_uid == captured.files.owner_uid,
        "SEED_INVALID",
    )
    base = base_host._capture_embedding_host(
        expected_seed_sha256=expected_seed_sha256,
        files=files,
        fixed_files=base_host.reviewed_embedding_host_files(
            baseline_host_seed_sha256=captured.baseline_host_seed_sha256,
            cache_byte_count=captured.cache_byte_count,
            cache_sha256=captured.cache_sha256,
        ),
        assert_mount_current=snapshot_mount.assert_unchanged,
    )
    stack = ExitStack()
    try:
        descriptors = []
        objects: dict[str, base_host.EmbeddingElfMetadata] = {}
        for library in captured.libraries:
            path = captured.cache_path.parent / library.member_name
            descriptor, sha = stack.enter_context(captured.files.open_verified_member(path))
            _require(sha == library.sha256, "LIBRARY_HASH_INVALID")
            metadata = base_host.parse_embedding_elf_metadata(
                path, base.inspect_elf(descriptor, deadline=time.monotonic() + 10.0)
            )
            _require(
                metadata.soname == library.member_name
                and metadata.object_kind == "DYN"
                and metadata.interpreter is None
                and not metadata.rpath
                and not metadata.runpath,
                "LIBRARY_ROUTE_INVALID",
            )
            objects[library.member_name] = metadata
            descriptors.append((path, descriptor, base_host._identity(os.fstat(descriptor))))
        for metadata in objects.values():
            requirements = dict(metadata.requirements)
            for name in metadata.needed:
                versions = (
                    objects[name].definitions
                    if name in objects
                    else base.fixed_soname_versions(name)
                )
                _require(requirements.get(name, frozenset()) <= versions, "VERSION_UNAVAILABLE")
        result = ProtectedCudaEmbeddingHostClosure(
            base, snapshot_mount, stack, tuple(descriptors), tuple(objects.values())
        )
        result.assert_current()
        return result
    except BaseException:
        try:
            stack.close()
        finally:
            base.close()
        raise
