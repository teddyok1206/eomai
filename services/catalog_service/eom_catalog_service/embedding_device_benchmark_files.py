"""Fixed local benchmark materialization; no prepare, launch, authority or publication."""

from __future__ import annotations

import fcntl
import hashlib
import os
import pwd
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Protocol

from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_ENVELOPE_BYTES,
    MAX_BENCHMARK_OUTPUT_BYTES,
    MAX_BENCHMARK_STAGED_BYTES,
    BenchmarkInvocationTimings,
    BenchmarkLocalBinary,
    BenchmarkLocalJson,
    BenchmarkResourceEvidence,
    BenchmarkSampleKey,
    BenchmarkStagedInputs,
    BenchmarkTokenWitness,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import EmbeddingRuntimeProfile
from eom_identifiers import sha256_bytes

from eom_catalog_service.embedding_benchmark_layout import benchmark_read_acl
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady

_HANDOFF_ROOT = Path("/run/eom-incremental-embeddings/benchmark")
_ROOT_UID = 0
_ROOT_GID = 0
_CHUNK = 64 * 1024
type BenchmarkLocalEvidence = (
    BenchmarkTokenWitness
    | BenchmarkInvocationTimings
    | BenchmarkResourceEvidence
    | BenchmarkWorkerResult
)


class BenchmarkFilesError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool) -> None:
    if not condition:
        raise BenchmarkFilesError("BENCHMARK_FILES_IDENTITY_INVALID")


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (*_identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _acl(descriptor: int, uid: int, *, directory: bool, group: int) -> None:
    _require(group == (5 if directory else 4))
    expected = benchmark_read_acl(uid, "DIRECTORY" if directory else "INPUT")
    # Small closed xattr, not a model path/allowlist. Reject other named/default grants.
    _require(os.getxattr(descriptor, "system.posix_acl_access") == expected)
    _require("system.posix_acl_default" not in os.listxattr(descriptor))


def _no_acl(descriptor: int) -> None:
    _require(
        not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(descriptor)
        )
    )


class _Digest(Protocol):
    def update(self, data: bytes | memoryview) -> None: ...

    def hexdigest(self) -> str: ...


@dataclass
class _Member:
    name: str
    descriptor: int
    epoch: tuple[int, ...]
    state: Literal["EMPTY", "WRITING", "SEALED", "POISONED"] = "EMPTY"
    byte_count: int = 0
    digest: _Digest | None = None


class BenchmarkWorkerLocalFiles:
    """One captured file set, not a grant; production uses only fixed accounts/root.

    Caller retains its original invocation FD. This context owns a close-on-exec duplicate
    and all FDs it opens. No file creation, truncation, delete or path override is provided.
    """

    def __init__(
        self,
        invocation_fd: int,
        *,
        profile: EmbeddingRuntimeProfile,
        execution_id: str,
        invocation_raw_sha256: str,
    ) -> None:
        fixed = fixed_native_embedding_profile(profile)
        _require(type(invocation_fd) is int and invocation_fd >= 0)
        _require(
            type(execution_id) is str and re.fullmatch(r"[0-9a-f]{32}", execution_id) is not None
        )
        _require(
            type(invocation_raw_sha256) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", invocation_raw_sha256) is not None
        )
        native, owner = pwd.getpwnam(fixed.worker_user), pwd.getpwnam("eom-workflow-runner")
        _require(
            all(
                type(value) is int and 0 < value < 2**32
                for value in (native.pw_uid, owner.pw_uid, owner.pw_gid)
            )
        )
        _require(native.pw_uid != owner.pw_uid)
        self._profile, self._execution_id, self._raw_pin = (
            profile,
            execution_id,
            invocation_raw_sha256,
        )
        self._native_uid, self._owner_gid = native.pw_uid, owner.pw_gid
        self._borrowed = invocation_fd
        self._input = -1
        self._directories: list[tuple[int, int | None, str, tuple[int, ...]]] = []
        self._narrow_directories: set[int] = set()
        self._members: dict[str, _Member] = {}
        self._input_member = -1
        self._input_epoch: tuple[int, ...] | None = None
        self._invocation_epoch: tuple[int, ...] | None = None
        self._invocation: BenchmarkWorkerInvocation | None = None
        self._staged: BenchmarkStagedInputs | None = None
        self._output_directory = -1
        self._execution_directory = -1
        self._inputs_directory = -1
        self._budget = 0
        self._ready_state: Literal["EMPTY", "WRITING", "SEALED", "POISONED"] = "EMPTY"
        self._ready_epoch: tuple[int, ...] | None = None
        self._closed = False

    @property
    def profile(self) -> EmbeddingRuntimeProfile:
        return self._profile

    @property
    def execution_id(self) -> str:
        return self._execution_id

    @property
    def raw_pin(self) -> str:
        return self._raw_pin

    @property
    def native_uid(self) -> int:
        return self._native_uid

    @property
    def owner_gid(self) -> int:
        return self._owner_gid

    def __enter__(self) -> BenchmarkWorkerLocalFiles:
        try:
            _require(not self._closed and self._input == -1)
            self._execution_directory = self._open_directory(
                _HANDOFF_ROOT / self.execution_id, narrow=True
            )
            self._input = fcntl.fcntl(self._borrowed, fcntl.F_DUPFD_CLOEXEC, 3)
            initial = os.fstat(self._input)
            _require(
                stat.S_ISREG(initial.st_mode)
                and initial.st_uid == _ROOT_UID
                and initial.st_gid == _ROOT_GID
                and stat.S_IMODE(initial.st_mode) == 0o600
                and initial.st_nlink == 1
                and 0 < initial.st_size <= MAX_BENCHMARK_ENVELOPE_BYTES
                and self._flags(self._input) == os.O_RDONLY
                and os.lseek(self._input, 0, os.SEEK_CUR) == 0
                and _epoch(initial)
                == _epoch(
                    os.stat(
                        "invocation.json", dir_fd=self._execution_directory, follow_symlinks=False
                    )
                )
            )
            _no_acl(self._input)
            self._invocation_epoch = _epoch(initial)
            self.assert_current()
            return self
        except Exception:
            self.close()
            raise BenchmarkFilesError("BENCHMARK_FILES_CAPTURE_INVALID") from None

    def _open_directory(self, path: Path, *, narrow: bool) -> int:
        parent: int | None = None
        for index, component in enumerate(path.parts):
            # Traversal needs search permission, not permission to list every execution.
            access = os.O_RDONLY if index == len(path.parts) - 1 else os.O_PATH
            descriptor = os.open(
                component,
                access | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            initial = os.fstat(descriptor)
            self._directories.append((descriptor, parent, component, _directory_identity(initial)))
            # Only synthetic non-root source fixtures traverse sticky /tmp. Fixed production
            # root/UID0 has no writable-ancestor exception and always lives below /run.
            synthetic_tmp = (
                _ROOT_UID != 0
                and component == "tmp"
                and parent is not None
                and bool(initial.st_mode & stat.S_ISVTX)
            )
            _require(
                stat.S_ISDIR(initial.st_mode)
                and initial.st_uid in (0, _ROOT_UID)
                and (not initial.st_mode & 0o022 or synthetic_tmp)
            )
            parent = descriptor
        assert parent is not None
        if narrow:
            value = os.fstat(parent)
            _require(
                value.st_uid == _ROOT_UID
                and value.st_gid == self.owner_gid
                and stat.S_IMODE(value.st_mode) == 0o750
            )
            _acl(parent, self.native_uid, directory=True, group=5)
            self._narrow_directories.add(parent)
        return parent

    @staticmethod
    def _flags(descriptor: int) -> int:
        return fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND)

    def _read(self, descriptor: int, initial: tuple[int, ...], maximum: int) -> bytes:
        size = initial[6]
        _require(0 < size <= maximum)
        chunks: list[bytes] = []
        count = 0
        while count <= size:
            chunk = os.pread(descriptor, min(_CHUNK, size + 1 - count), count)
            if not chunk:
                break
            count += len(chunk)
            _require(count <= size)
            chunks.append(chunk)
        _require(count == size and _epoch(os.fstat(descriptor)) == initial)
        return b"".join(chunks)

    def read_invocation(self) -> BenchmarkWorkerInvocation:
        self.assert_current()
        if self._invocation is not None:
            return self._invocation
        assert self._invocation_epoch is not None
        raw = self._read(self._input, self._invocation_epoch, MAX_BENCHMARK_ENVELOPE_BYTES)
        _require(sha256_bytes(raw) == self.raw_pin)
        invocation = parse_embedding_device_benchmark_bytes(raw)
        _require(isinstance(invocation, BenchmarkWorkerInvocation))
        assert isinstance(invocation, BenchmarkWorkerInvocation)
        _require(
            raw == embedding_device_benchmark_bytes(invocation)
            and invocation.execution_id == self.execution_id
            and invocation.runtime.profile == self.profile
        )
        self._invocation = invocation
        self._inputs_directory = self._open_directory(
            _HANDOFF_ROOT / self.execution_id / "inputs", narrow=True
        )
        self._output_directory = self._open_directory(
            _HANDOFF_ROOT / self.execution_id / "outputs", narrow=True
        )
        expected = set(benchmark_local_output_members(invocation.launch_ordinal))
        observed: set[str] = set()
        with os.scandir(self._output_directory) as entries:
            for entry in entries:
                _require(entry.name in expected and len(observed) < len(expected))
                observed.add(entry.name)
        _require(observed == expected)
        inodes = {(self._invocation_epoch[0], self._invocation_epoch[1])}
        for name in benchmark_local_output_members(invocation.launch_ordinal):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._output_directory,
            )
            initial = os.fstat(descriptor)
            self._members[name] = _Member(
                name, descriptor, _epoch(initial), digest=hashlib.sha256()
            )
            _require(
                stat.S_ISREG(initial.st_mode)
                and initial.st_uid == self.native_uid
                and initial.st_gid == self.owner_gid
                and stat.S_IMODE(initial.st_mode) == 0o640
                and initial.st_nlink == 1
                and initial.st_size == 0
                and self._flags(descriptor) == os.O_WRONLY
                and os.lseek(descriptor, 0, os.SEEK_CUR) == 0
                and (initial.st_dev, initial.st_ino) not in inodes
            )
            _no_acl(descriptor)
            inodes.add((initial.st_dev, initial.st_ino))
        self.assert_current()
        return invocation

    def read_inputs(self, invocation: BenchmarkWorkerInvocation) -> BenchmarkStagedInputs:
        _require(self.read_invocation() == BenchmarkWorkerInvocation.model_validate(invocation))
        if self._staged is not None:
            self.assert_current()
            return self._staged
        descriptor = os.open(
            "benchmark-inputs.json",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=self._inputs_directory,
        )
        self._input_member = descriptor
        initial = os.fstat(descriptor)
        _require(
            stat.S_ISREG(initial.st_mode)
            and initial.st_uid == _ROOT_UID
            and initial.st_gid == self.owner_gid
            and stat.S_IMODE(initial.st_mode) == 0o640
            and initial.st_nlink == 1
            and initial.st_size == invocation.local_input.byte_count
            and 0 < initial.st_size <= MAX_BENCHMARK_STAGED_BYTES
            and self._flags(descriptor) == os.O_RDONLY
        )
        _acl(descriptor, self.native_uid, directory=False, group=4)
        self._input_epoch = _epoch(initial)
        raw = self._read(descriptor, self._input_epoch, MAX_BENCHMARK_STAGED_BYTES)
        _require(sha256_bytes(raw) == invocation.local_input.sha256)
        inputs = parse_embedding_device_benchmark_bytes(
            raw, maximum_bytes=MAX_BENCHMARK_STAGED_BYTES
        )
        _require(isinstance(inputs, BenchmarkStagedInputs))
        assert isinstance(inputs, BenchmarkStagedInputs)
        _require(
            raw == embedding_device_benchmark_bytes(inputs)
            and inputs.benchmark_id == invocation.benchmark_id
            and inputs.benchmark_revision_id == invocation.benchmark_revision_id
            and inputs.input_set_sha256 == invocation.input_set_sha256
            and inputs.public_fixture_sha256 == invocation.recipe.public_fixture_sha256
        )
        inodes = {(member.epoch[0], member.epoch[1]) for member in self._members.values()}
        _require((initial.st_dev, initial.st_ino) not in inodes)
        self._staged = inputs
        self.assert_current()
        return inputs

    def assert_current(self) -> None:
        _require(not self._closed and self._input >= 0)
        _require(self._ready_state in {"EMPTY", "SEALED"})
        if self._ready_epoch is not None:
            _require(
                _epoch(
                    os.stat(
                        "cuda-ready.json", dir_fd=self._execution_directory, follow_symlinks=False
                    )
                )
                == self._ready_epoch
            )
        for descriptor, parent, name, initial in self._directories:
            _require(
                not os.get_inheritable(descriptor)
                and _directory_identity(os.fstat(descriptor)) == initial
                and _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                == initial
            )
            if descriptor in self._narrow_directories:
                _acl(descriptor, self.native_uid, directory=True, group=5)
        if self._invocation_epoch is not None:
            _require(
                not os.get_inheritable(self._input)
                and _epoch(os.fstat(self._input)) == self._invocation_epoch
                and self._flags(self._input) == os.O_RDONLY
            )
            _require(
                _epoch(
                    os.stat(
                        "invocation.json", dir_fd=self._execution_directory, follow_symlinks=False
                    )
                )
                == self._invocation_epoch
            )
        if self._input_epoch is not None:
            _require(
                not os.get_inheritable(self._input_member)
                and _epoch(os.fstat(self._input_member)) == self._input_epoch
            )
            _require(
                _epoch(
                    os.stat(
                        "benchmark-inputs.json",
                        dir_fd=self._inputs_directory,
                        follow_symlinks=False,
                    )
                )
                == self._input_epoch
            )
        for member in self._members.values():
            _require(member.state != "POISONED")
            _require(
                _epoch(os.stat(member.name, dir_fd=self._output_directory, follow_symlinks=False))
                == member.epoch
            )
            if member.descriptor >= 0:
                _require(
                    not os.get_inheritable(member.descriptor)
                    and _epoch(os.fstat(member.descriptor)) == member.epoch
                    and self._flags(member.descriptor) == os.O_WRONLY
                    and os.lseek(member.descriptor, 0, os.SEEK_CUR) == member.byte_count
                )
                _no_acl(member.descriptor)

    def write_cuda_ready(self, ready: BenchmarkCudaReady) -> None:
        """Seal one precreated operational member; never alter numerical output/budget."""
        _require(self.profile == "CUDA_INDEX_FP32" and self._ready_state == "EMPTY")
        from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
            BenchmarkCudaReady,
            benchmark_cuda_ready_bytes,
        )

        _require(type(ready) is BenchmarkCudaReady)
        raw = benchmark_cuda_ready_bytes(ready)
        invocation = self.read_invocation()
        _require(
            ready.execution_id == self.execution_id
            and ready.job_id == invocation.job_id
            and ready.invocation_raw_sha256 == self.raw_pin
            and ready.pid == os.getpid()
            and os.getresuid() == (self.native_uid,) * 3
            and ready.worker_uid == self.native_uid
            and os.getresgid() == (ready.worker_gid,) * 3
            and tuple(sorted(set(os.getgroups()) - {ready.worker_gid})) == ready.supplementary_gids
        )
        descriptor = -1
        self._ready_state = "WRITING"
        try:
            descriptor = os.open(
                "cuda-ready.json",
                os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._execution_directory,
            )
            before = os.fstat(descriptor)
            _require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == self.native_uid
                and before.st_gid == self.owner_gid
                and stat.S_IMODE(before.st_mode) == 0o640
                and before.st_nlink == 1
                and before.st_size == 0
                and self._flags(descriptor) == os.O_RDWR
                and os.lseek(descriptor, 0, os.SEEK_CUR) == 0
                and not os.get_inheritable(descriptor)
            )
            _no_acl(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            remaining = memoryview(raw)
            while remaining:
                count = os.write(descriptor, remaining)
                _require(type(count) is int and 0 < count <= len(remaining))
                remaining = remaining[count:]
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            _require(_identity(after) == _identity(before) and after.st_size == len(raw))
            _require(os.pread(descriptor, len(raw) + 1, 0) == raw)
            _require(
                _epoch(
                    os.stat(
                        "cuda-ready.json", dir_fd=self._execution_directory, follow_symlinks=False
                    )
                )
                == _epoch(after)
            )
            self._ready_epoch, self._ready_state = _epoch(after), "SEALED"
            self.assert_current()
        except Exception:
            self._ready_state = "POISONED"
            raise BenchmarkFilesError("BENCHMARK_CUDA_READY_WRITE_UNCERTAIN") from None
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    self._ready_state = "POISONED"
                    raise BenchmarkFilesError("BENCHMARK_CUDA_READY_CLOSE_UNCERTAIN") from None

    def _write(self, name: str, payload: bytes) -> _Member:
        self.assert_current()
        _require(type(payload) is bytes and 0 < len(payload) <= MAX_BENCHMARK_OUTPUT_BYTES)
        _require(name in self._members)
        member = self._members[name]
        _require(member.state in ("EMPTY", "WRITING") and member.descriptor >= 0)
        _require(self._budget + len(payload) <= MAX_BENCHMARK_OUTPUT_BYTES)
        self._budget += len(payload)  # Keep conservative reservation on uncertain partial writes.
        member.state = "WRITING"
        try:
            remaining = memoryview(payload)
            while remaining:
                self.assert_current()
                count = os.write(member.descriptor, remaining[:_CHUNK])
                _require(type(count) is int and 0 < count <= min(_CHUNK, len(remaining)))
                assert member.digest is not None
                member.digest.update(remaining[:count])
                member.byte_count += count
                after = os.fstat(member.descriptor)
                _require(
                    _identity(after) == member.epoch[:6] and after.st_size == member.byte_count
                )
                _require(os.lseek(member.descriptor, 0, os.SEEK_CUR) == member.byte_count)
                member.epoch = _epoch(after)
                remaining = remaining[count:]
            self.assert_current()
            return member
        except Exception:
            member.state = "POISONED"
            raise BenchmarkFilesError("BENCHMARK_FILES_WRITE_UNCERTAIN") from None

    def _seal(self, member: _Member) -> tuple[str, int]:
        self.assert_current()
        _require(member.state == "WRITING" and member.descriptor >= 0)
        try:
            os.fsync(member.descriptor)
            self.assert_current()
            descriptor, member.descriptor = member.descriptor, -1
            os.close(descriptor)
            member.state = "SEALED"
            self.assert_current()
            assert member.digest is not None
            return "sha256:" + member.digest.hexdigest(), member.byte_count
        except Exception:
            member.state = "POISONED"
            raise BenchmarkFilesError("BENCHMARK_FILES_SEAL_UNCERTAIN") from None

    def write_vectors(self, key: BenchmarkSampleKey, payload: bytes) -> BenchmarkLocalBinary | None:
        key = BenchmarkSampleKey.model_validate(key)
        name = (
            "cold-documents.f32"
            if key.phase == "COLD_DOCUMENT"
            else f"query-{key.query_ordinal}-{key.repetition}.f32"
            if key.phase == "QUERY"
            else "supplementary-documents.f32"
        )
        _require(len(payload) % 4096 == 0)
        member = self._write(name, payload)
        if name == "supplementary-documents.f32":
            return None
        sha, count = self._seal(member)
        return BenchmarkLocalBinary.model_validate(
            {"member_name": name, "sha256": sha, "byte_count": count}
        )

    def seal_supplementary(self) -> BenchmarkLocalBinary:
        _require("supplementary-documents.f32" in self._members)
        member = self._members["supplementary-documents.f32"]
        sha, count = self._seal(member)
        return BenchmarkLocalBinary(
            member_name="supplementary-documents.f32", sha256=sha, byte_count=count
        )

    def write_evidence(self, message: BenchmarkLocalEvidence) -> BenchmarkLocalJson:
        if isinstance(message, BenchmarkTokenWitness):
            name, definition = "token-witness.json", "tokenWitness"
        elif isinstance(message, BenchmarkInvocationTimings):
            name, definition = "timings.json", "invocationTimings"
        elif isinstance(message, BenchmarkResourceEvidence):
            name, definition = "resources.json", "resources"
        elif isinstance(message, BenchmarkWorkerResult):
            name, definition = "worker-result.json", "workerResult"
        else:
            raise BenchmarkFilesError("BENCHMARK_FILES_EVIDENCE_INVALID")
        raw = embedding_device_benchmark_bytes(message)
        sha, count = self._seal(self._write(name, raw))
        return BenchmarkLocalJson.model_validate(
            {
                "member_name": name,
                "sha256": sha,
                "byte_count": count,
                "schema_ref": f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/{definition}",
            }
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failed = False
        descriptors = [
            member.descriptor for member in self._members.values() if member.descriptor >= 0
        ]
        for member in self._members.values():
            member.descriptor = -1
        descriptors.extend(value for value in (self._input_member, self._input) if value >= 0)
        descriptors.extend(descriptor for descriptor, *_rest in reversed(self._directories))
        self._input_member = self._input = -1
        self._directories.clear()
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise BenchmarkFilesError("BENCHMARK_FILES_CLOSE_UNCERTAIN")

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()
