"""Root-only fixed local preparation, never operator authorization or launch admission."""

from __future__ import annotations

import os
import pwd
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    MAX_BENCHMARK_STAGED_BYTES,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import sha256_bytes

from eom_catalog_service.embedding_benchmark_layout import benchmark_read_acl
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

_HANDOFF_ROOT = Path("/run/eom-incremental-embeddings/benchmark")
_ROOT_UID = 0
_ROOT_GID = 0
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_ACL_NAMES = frozenset(("system.posix_acl_access", "system.posix_acl_default"))


class BenchmarkHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool) -> None:
    if not condition:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedBenchmarkHandoff:
    """Local preparation metadata, not a published Artifact or evidence of execution."""

    benchmark_id: str
    benchmark_revision_id: str
    job_id: str
    execution_id: str
    invocation_sha256: str
    invocation_raw_sha256: str
    input_set_sha256: str
    input_raw_sha256: str
    output_members: tuple[str, ...]
    state: Literal["STAGED_NOT_ADMITTED"] = "STAGED_NOT_ADMITTED"


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _fixed_root(stack: ExitStack) -> int:
    parent: int | None = None
    for index, component in enumerate(_HANDOFF_ROOT.parts):
        last = index == len(_HANDOFF_ROOT.parts) - 1
        descriptor = os.open(
            component,
            (os.O_RDONLY if last else os.O_PATH) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        stack.callback(os.close, descriptor)
        value = os.fstat(descriptor)
        # Synthetic source fixtures may live under sticky /tmp; production may not.
        synthetic_tmp = _ROOT_UID != 0 and component == "tmp" and bool(value.st_mode & stat.S_ISVTX)
        _require(
            stat.S_ISDIR(value.st_mode)
            and value.st_uid in (0, _ROOT_UID)
            and (not value.st_mode & 0o022 or synthetic_tmp)
        )
        parent = descriptor
    _require(parent is not None)
    assert parent is not None
    value = os.fstat(parent)
    _require(
        value.st_uid == _ROOT_UID
        and value.st_gid == _ROOT_GID
        and stat.S_IMODE(value.st_mode) == 0o711
        and not _ACL_NAMES.intersection(os.listxattr(parent))
    )
    return parent


def _new_directory(stack: ExitStack, parent: int, name: str, gid: int) -> int:
    os.mkdir(name, mode=0o700, dir_fd=parent)
    descriptor = os.open(name, _OPEN_DIRECTORY, dir_fd=parent)
    stack.callback(os.close, descriptor)
    os.fchown(descriptor, _ROOT_UID, gid)
    os.fchmod(descriptor, 0o700)
    _require(not _ACL_NAMES.intersection(os.listxattr(descriptor)))
    _require(
        _directory_identity(os.fstat(descriptor))
        == _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
    )
    return descriptor


def _new_member(parent: int, name: str, payload: bytes, uid: int, gid: int, mode: int) -> None:
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=parent,
    )
    try:
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
        _require(not _ACL_NAMES.intersection(os.listxattr(descriptor)))
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining[: 64 * 1024])
            _require(0 < count <= len(remaining))
            remaining = remaining[count:]
        os.fsync(descriptor)
        _require(os.pread(descriptor, len(payload) + 1, 0) == payload)
        value = os.fstat(descriptor)
        _require(
            stat.S_ISREG(value.st_mode)
            and value.st_uid == uid
            and value.st_gid == gid
            and stat.S_IMODE(value.st_mode) == mode
            and value.st_nlink == 1
            and value.st_size == len(payload)
            and value == os.stat(name, dir_fd=parent, follow_symlinks=False)
        )
    finally:
        os.close(descriptor)


def prepare_benchmark_handoff(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
) -> PreparedBenchmarkHandoff:
    """Prepare once at the fixed root; any partial failure is preserved, never replayed.

    The application caller still owns source resolution, real Job identity and authorization.
    No worker process, model import, socket, DB row or NAS Artifact is created here.
    """
    if os.geteuid() != _ROOT_UID:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_ROOT_REQUIRED")
    # Serialization invokes the released JSON Schema plus Pydantic, before mkdir/chown.
    embedding_device_benchmark_bytes(request)
    invocation_raw = embedding_device_benchmark_bytes(invocation)
    input_raw = embedding_device_benchmark_bytes(inputs)
    validate_benchmark_invocation(request, invocation, inputs)
    _require(0 < len(invocation_raw) <= MAX_BENCHMARK_ENVELOPE_BYTES)
    _require(0 < len(input_raw) <= MAX_BENCHMARK_STAGED_BYTES)
    fixed = fixed_native_embedding_profile(invocation.runtime.profile)
    native, owner = pwd.getpwnam(fixed.worker_user), pwd.getpwnam("eom-workflow-runner")
    _require(
        all(
            type(value) is int and 0 < value < 2**32 - 1
            for value in (native.pw_uid, owner.pw_uid, owner.pw_gid)
        )
        and native.pw_uid != owner.pw_uid
    )
    members = benchmark_local_output_members(invocation.launch_ordinal)
    try:
        with ExitStack() as stack:
            root = _fixed_root(stack)
            execution = _new_directory(stack, root, invocation.execution_id, owner.pw_gid)
            staged = _new_directory(stack, execution, "inputs", owner.pw_gid)
            outputs = _new_directory(stack, execution, "outputs", owner.pw_gid)
            _new_member(execution, "invocation.json", invocation_raw, _ROOT_UID, _ROOT_GID, 0o600)
            _new_member(staged, "benchmark-inputs.json", input_raw, _ROOT_UID, owner.pw_gid, 0o640)
            input_fd = os.open(
                "benchmark-inputs.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=staged
            )
            try:
                acl = benchmark_read_acl(native.pw_uid, "INPUT")
                os.setxattr(input_fd, "system.posix_acl_access", acl)
                _require(os.getxattr(input_fd, "system.posix_acl_access") == acl)
                os.fsync(input_fd)
            finally:
                os.close(input_fd)
            for name in members:
                _new_member(outputs, name, b"", native.pw_uid, owner.pw_gid, 0o640)
            # Grant traversal last: incomplete preparation stays private to root.
            for descriptor in (staged, outputs, execution):
                acl = benchmark_read_acl(native.pw_uid, "DIRECTORY")
                os.setxattr(descriptor, "system.posix_acl_access", acl)
                _require(os.getxattr(descriptor, "system.posix_acl_access") == acl)
                _require("system.posix_acl_default" not in os.listxattr(descriptor))
                os.fsync(descriptor)
            os.fsync(root)
    except FileExistsError:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_ALREADY_EXISTS") from None
    except OSError:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_PREPARE_FAILED") from None
    return PreparedBenchmarkHandoff(
        benchmark_id=invocation.benchmark_id,
        benchmark_revision_id=invocation.benchmark_revision_id,
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        invocation_raw_sha256=sha256_bytes(invocation_raw),
        input_set_sha256=inputs.input_set_sha256,
        input_raw_sha256=sha256_bytes(input_raw),
        output_members=members,
    )
