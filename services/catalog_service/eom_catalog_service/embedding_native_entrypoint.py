"""Stdlib-first fixed native library adapters; no CLI, installed capture or production main."""

from __future__ import annotations

import fcntl
import grp
import os
import platform
import pwd
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from eom_catalog_service.embedding_runtime_files import (
    fixed_native_embedding_profile,
    read_live_runtime_os_file,
)

if TYPE_CHECKING:
    from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend


class NativeEmbeddingEntrypointError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_native_embedding_identity(profile: str) -> None:
    """Current identity/isolation only; owner unit/network/filesystem admission is separate."""
    fixed = fixed_native_embedding_profile(profile)
    worker = pwd.getpwnam(fixed.worker_user)
    group = grp.getgrnam(fixed.worker_user)
    supplementary = set(os.getgroups())
    expected = {group.gr_gid}
    if fixed.supplementary_group is not None:
        lease_group = grp.getgrnam(fixed.supplementary_group).gr_gid
        if lease_group <= 0 or lease_group == group.gr_gid:
            raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_IDENTITY_INVALID")
        expected.add(lease_group)
        if lease_group not in supplementary:
            raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_IDENTITY_INVALID")
    if (
        worker.pw_uid <= 0
        or group.gr_gid <= 0
        or worker.pw_gid != group.gr_gid
        or os.getresuid() != (worker.pw_uid,) * 3
        or os.getresgid() != (group.gr_gid,) * 3
        or not supplementary <= expected
        or Path(sys.prefix) != fixed.prefix
        or Path(sys.executable) != fixed.prefix / "bin/python3.12"
        or sys.version_info[:3] != (3, 12, 13)
        or platform.python_implementation() != "CPython"
        or sys.platform != "linux"
        or platform.machine() != "x86_64"
        or sys.flags.isolated != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_user_site != 1
        or sys.dont_write_bytecode is not True
    ):
        raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_IDENTITY_INVALID")
    raw = read_live_runtime_os_file(
        Path("/proc") / str(os.getpid()) / "status", maximum=128 * 1024, owner_uid=worker.pw_uid
    )
    fields: dict[str, str] = {}
    for line in raw.decode("ascii").splitlines():
        key, separator, value = line.partition(":")
        if not separator or key in fields:
            raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_CAPABILITIES_INVALID")
        fields[key] = value.strip()
    if fields.get("NoNewPrivs") != "1" or any(
        fields.get(name) != "0000000000000000"
        for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    ):
        raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_CAPABILITIES_INVALID")


@contextmanager
def _quiet_channels() -> Iterator[tuple[int, int]]:
    owned: list[int] = []
    try:
        result = fcntl.fcntl(1, fcntl.F_DUPFD_CLOEXEC, 3)
        owned.append(result)
        vectors = fcntl.fcntl(2, fcntl.F_DUPFD_CLOEXEC, 3)
        owned.append(vectors)
        sink = os.open("/dev/null", os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        owned.append(sink)
        value = os.fstat(sink)
        if not stat.S_ISCHR(value.st_mode) or (
            os.major(value.st_rdev),
            os.minor(value.st_rdev),
        ) != (1, 3):
            raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_NULL_DEVICE_INVALID")
        os.dup2(sink, 1)
        os.dup2(sink, 2)
        sys.stdout.flush()
        sys.stderr.flush()
        yield result, vectors
    finally:
        # Never restore ordinary diagnostics to root-owned result/binary descriptors.
        failed = False
        for descriptor in reversed(owned):
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_DESCRIPTOR_CLEANUP_UNCERTAIN")


def run_native_embedding_index(
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Adapt an already admitted owner-bound scope; never choose capture/paths/flags from input."""
    try:
        with _quiet_channels() as (result, vectors):
            require_native_embedding_identity(profile)
            # Identity/quiet descriptors precede Catalog/Pydantic and all optional ML imports.
            from eom_catalog_service.embedding_native_stdio import (
                NativeEmbeddingDescriptors,
                run_native_embedding_descriptors,
            )

            run_native_embedding_descriptors(
                NativeEmbeddingDescriptors(0, result, vectors), backend_scope
            )
    except Exception:
        raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_INDEX_EXECUTION_FAILED") from None


def run_native_embedding_reference_query(
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Fixed QUERY leaf; an INDEX profile identity is not QUERY purpose/unit admission."""
    try:
        with _quiet_channels() as (result, vectors):
            require_native_embedding_identity(profile)
            from eom_catalog_service.embedding_native_stdio import (
                NativeEmbeddingDescriptors,
                run_native_reference_query_descriptors,
            )

            run_native_reference_query_descriptors(
                NativeEmbeddingDescriptors(0, result, vectors), backend_scope
            )
    except Exception:
        raise NativeEmbeddingEntrypointError("NATIVE_EMBEDDING_QUERY_EXECUTION_FAILED") from None
