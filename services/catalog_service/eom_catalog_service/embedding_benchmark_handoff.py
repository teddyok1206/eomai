"""Root-only fixed local preparation, never operator authorization or launch admission."""

from __future__ import annotations

import os
import pwd
import stat
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    MAX_BENCHMARK_STAGED_BYTES,
    BenchmarkOwnerRequest,
    BenchmarkRuntime,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import sha256_bytes

from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_launch_environment_bytes,
)
from eom_catalog_service.embedding_benchmark_layout import (
    BENCHMARK_HANDOFF_ROOT,
    benchmark_read_acl,
)
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkRootStagedFiles
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    fixed_native_embedding_profile,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_process_identity import native_process_start_ticks

_HANDOFF_ROOT = BENCHMARK_HANDOFF_ROOT
_ROOT_UID = 0
_ROOT_GID = 0
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_ACL_NAMES = frozenset(("system.posix_acl_access", "system.posix_acl_default"))
_CONFIG_ROOT = Path("/opt/eom/embedding-native-config")
_EVIDENCE_ROOT = Path("/opt/eom/embedding-runtime-admission")


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


@dataclass(frozen=True, slots=True)
class PreparedBenchmarkEnvironment:
    """OS-local staging only; neither a Job/source grant nor a launch/installation receipt."""

    execution_id: str
    job_id: str
    environment_raw_sha256: str
    owner_pid: int
    owner_start_ticks: int
    expires_ns: int
    state: Literal["STAGED_NOT_LAUNCHED"] = "STAGED_NOT_LAUNCHED"


PreparedCpuBenchmarkEnvironment = PreparedBenchmarkEnvironment


def _prepared_handoff(
    invocation: BenchmarkWorkerInvocation, invocation_raw_sha256: str
) -> PreparedBenchmarkHandoff:
    return PreparedBenchmarkHandoff(
        benchmark_id=invocation.benchmark_id,
        benchmark_revision_id=invocation.benchmark_revision_id,
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        invocation_raw_sha256=invocation_raw_sha256,
        input_set_sha256=invocation.input_set_sha256,
        input_raw_sha256=invocation.local_input.sha256,
        output_members=benchmark_local_output_members(invocation.launch_ordinal),
    )


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
            if invocation.device == "CUDA":
                # Operational pre-init metadata, outside the frozen numerical output namespace.
                _new_member(execution, "cuda-ready.json", b"", native.pw_uid, owner.pw_gid, 0o640)
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
    return _prepared_handoff(invocation, sha256_bytes(invocation_raw))


def benchmark_owner_start_ticks(pid: int, *, uid: int, gid: int) -> int:
    """Fresh kernel reads only; no cmdline, environment, credentials or caller role claim."""
    process = Path("/proc") / str(pid)
    first = native_process_start_ticks(
        read_live_runtime_os_file(process / "stat", maximum=64 * 1024, owner_uid=uid), pid
    )
    raw = read_live_runtime_os_file(process / "status", maximum=128 * 1024, owner_uid=uid)
    fields: dict[bytes, tuple[bytes, ...]] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(b":")
        if name in {b"Uid", b"Gid"}:
            _require(bool(separator) and name not in fields)
            fields[name] = tuple(value.split())
    _require(fields == {b"Uid": (str(uid).encode(),) * 4, b"Gid": (str(gid).encode(),) * 4})
    last = native_process_start_ticks(
        read_live_runtime_os_file(process / "stat", maximum=64 * 1024, owner_uid=uid), pid
    )
    _require(first == last)
    return first


_owner_start_ticks = benchmark_owner_start_ticks


def _validate_environment_installation(
    files: NumericalRuntimeFileSnapshots,
    runtime: BenchmarkRuntime,
    backend: NativeEmbeddingBackendPins,
) -> None:
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
        MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
        RootLocalNativeConfigurationPin,
        parse_rootlocal_native_admission_receipt_metadata,
    )
    from eom_catalog_contracts.embedding_native_runtime_config import (
        MAX_NATIVE_RUNTIME_CONFIG_BYTES,
        EmbeddingNativeRuntimeConfigV12,
        EmbeddingNativeRuntimeConfigV13,
        parse_installed_embedding_native_runtime_config_bytes,
        validate_installed_embedding_native_runtime_config_raw,
    )

    raw = files.read(
        _CONFIG_ROOT / backend.configuration_id / backend.configuration_revision_id / "config.json",
        sha256=backend.configuration_raw_sha256,
        maximum=MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    )
    config = parse_installed_embedding_native_runtime_config_bytes(raw)
    validate_installed_embedding_native_runtime_config_raw(
        config, raw, backend.configuration_raw_sha256
    )
    pin = RootLocalNativeConfigurationPin(
        configuration_id=backend.configuration_id,
        configuration_revision_id=backend.configuration_revision_id,
        configuration_sha256=backend.configuration_sha256,
        configuration_raw_sha256=backend.configuration_raw_sha256,
    )
    from eom_catalog_contracts.embedding_cuda_installation_evidence import (
        CudaAdmissionReceiptMetadata,
    )
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeAdmissionReceiptMetadata,
    )

    receipt: RootLocalNativeAdmissionReceiptMetadata | CudaAdmissionReceiptMetadata
    if runtime.profile == "CPU_INDEX_FP32":
        receipt = parse_rootlocal_native_admission_receipt_metadata(
            files.read(
                _EVIDENCE_ROOT
                / pin.configuration_id
                / pin.configuration_revision_id
                / "receipt.json",
                sha256=backend.receipt_raw_sha256,
                maximum=MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
            ),
            schema_raw=files.read(
                _EVIDENCE_ROOT / "schemas/admission-receipt-v1.schema.json",
                sha256=ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
                maximum=32 * 1024,
            ),
        )
    else:
        from eom_catalog_service.embedding_native_installation_admission import (
            read_pinned_cuda_admission_receipt,
        )

        receipt, _ = read_pinned_cuda_admission_receipt(
            files, pin, receipt_raw_sha256=backend.receipt_raw_sha256
        )
        _require(
            isinstance(config, EmbeddingNativeRuntimeConfigV12 | EmbeddingNativeRuntimeConfigV13)
        )
        assert isinstance(config, EmbeddingNativeRuntimeConfigV12 | EmbeddingNativeRuntimeConfigV13)
        _require(receipt.cuda_host_extension == config.cuda_host_extension)
    _require(
        config.profile == runtime.profile
        and config.configuration_id == pin.configuration_id
        and config.configuration_revision_id == pin.configuration_revision_id
        and config.config_sha256 == pin.configuration_sha256
        and config.bundle == runtime.bundle
        and config.installed_proof == runtime.installed_proof
        and config.runtime_sha256 == runtime.numerical_runtime.runtime_sha256
        and receipt.configuration == pin
        and receipt.bundle == config.bundle
        and receipt.installed_proof == config.installed_proof
        and receipt.runtime_sha256 == config.runtime_sha256
    )
    files.assert_unchanged()


def capture_benchmark_runtime_installation(
    runtime: BenchmarkRuntime,
    *,
    backend: NativeEmbeddingBackendPins,
) -> NumericalRuntimeFileSnapshots:
    """Read-only protected configuration/receipt closure, never compute admission.

    The owner can preflight the exact selection before reserving an execution.
    Root preparation and the native installation adapter still independently
    verify their actual runtime, whole-prefix and sandbox boundaries.
    """
    runtime = BenchmarkRuntime.model_validate(runtime)
    backend.__post_init__()
    files = NumericalRuntimeFileSnapshots(_ROOT_UID)
    _validate_environment_installation(files, runtime, backend)
    return files


def prepare_benchmark_environment(
    prepared: PreparedBenchmarkHandoff,
    invocation: BenchmarkWorkerInvocation,
    *,
    backend: NativeEmbeddingBackendPins,
    owner_pid: int,
    expires_ns: int,
) -> PreparedBenchmarkEnvironment:
    """Exclusive root-only environment creation; caller still owns real Job/launch admission."""
    if os.geteuid() != _ROOT_UID:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_ROOT_REQUIRED")
    raw = embedding_device_benchmark_bytes(invocation)
    _require(
        type(prepared) is PreparedBenchmarkHandoff
        and prepared == _prepared_handoff(invocation, sha256_bytes(raw))
        and invocation.runtime.profile
        == {"CPU": "CPU_INDEX_FP32", "CUDA": "CUDA_INDEX_FP32"}[invocation.device]
        and type(backend) is NativeEmbeddingBackendPins
        and type(owner_pid) is int
        and 0 < owner_pid <= 2**31 - 1
        and type(expires_ns) is int
        and time.monotonic_ns() < expires_ns <= time.monotonic_ns() + 180 * 10**9
    )
    backend.__post_init__()
    owner = pwd.getpwnam("eom-workflow-runner")
    _require(
        type(owner.pw_uid) is int
        and 0 < owner.pw_uid < 2**32 - 1
        and type(owner.pw_gid) is int
        and 0 < owner.pw_gid < 2**32 - 1
    )
    start_ticks = _owner_start_ticks(owner_pid, uid=owner.pw_uid, gid=owner.pw_gid)
    installation = NumericalRuntimeFileSnapshots(_ROOT_UID)
    _validate_environment_installation(installation, invocation.runtime, backend)
    payload = benchmark_launch_environment_bytes(
        BenchmarkLaunchPins(
            prepared.execution_id, prepared.invocation_raw_sha256, owner_pid, expires_ns, backend
        )
    )
    try:
        with ExitStack() as stack:
            root = _fixed_root(stack)
            execution = os.open(prepared.execution_id, _OPEN_DIRECTORY, dir_fd=root)
            stack.callback(os.close, execution)
            descriptor = os.open(
                "invocation.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=execution
            )
            stack.callback(os.close, descriptor)
            with BenchmarkRootStagedFiles(
                descriptor,
                profile=invocation.runtime.profile,
                execution_id=prepared.execution_id,
                invocation_raw_sha256=prepared.invocation_raw_sha256,
            ) as local:
                _require(local.read_invocation() == invocation)
                location = _HANDOFF_ROOT / prepared.execution_id
                _require(
                    _directory_identity(os.fstat(execution))
                    == _directory_identity(location.lstat())
                )
                installation.assert_unchanged()
                _require(
                    _owner_start_ticks(owner_pid, uid=owner.pw_uid, gid=owner.pw_gid) == start_ticks
                )
                _require(time.monotonic_ns() < expires_ns)
                _new_member(execution, "launch.env", payload, _ROOT_UID, _ROOT_GID, 0o600)
                os.fsync(execution)
                local.assert_current()
                _require(
                    _directory_identity(os.fstat(execution))
                    == _directory_identity(location.lstat())
                )
                installation.assert_unchanged()
                _require(
                    _owner_start_ticks(owner_pid, uid=owner.pw_uid, gid=owner.pw_gid) == start_ticks
                )
                _require(time.monotonic_ns() < expires_ns)
    except FileExistsError:
        raise BenchmarkHandoffError("BENCHMARK_ENVIRONMENT_ALREADY_EXISTS") from None
    except OSError:
        raise BenchmarkHandoffError("BENCHMARK_ENVIRONMENT_PREPARE_FAILED") from None
    return PreparedBenchmarkEnvironment(
        execution_id=prepared.execution_id,
        job_id=prepared.job_id,
        environment_raw_sha256=sha256_bytes(payload),
        owner_pid=owner_pid,
        owner_start_ticks=start_ticks,
        expires_ns=expires_ns,
    )


def capture_prepared_benchmark_environment(
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
) -> NumericalRuntimeFileSnapshots:
    """Read exact root launch/config/receipt epochs; no source, input text or unit effects.

    Current owner/deadline and actual service admission are the calling driver's
    responsibility. Keeping this read usable after expiry permits honest late cleanup.
    """
    if os.geteuid() != _ROOT_UID:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_ROOT_REQUIRED")
    invocation_raw = embedding_device_benchmark_bytes(invocation)
    _require(type(environment) is PreparedBenchmarkEnvironment)
    pins = BenchmarkLaunchPins(
        invocation.execution_id,
        sha256_bytes(invocation_raw),
        environment.owner_pid,
        environment.expires_ns,
        backend,
    )
    environment_raw = benchmark_launch_environment_bytes(pins)
    _require(
        environment.execution_id == invocation.execution_id
        and environment.job_id == invocation.job_id
        and environment.state == "STAGED_NOT_LAUNCHED"
        and environment.environment_raw_sha256 == sha256_bytes(environment_raw)
    )
    files = NumericalRuntimeFileSnapshots(_ROOT_UID)
    execution = _HANDOFF_ROOT / invocation.execution_id
    for name, payload in (("invocation.json", invocation_raw), ("launch.env", environment_raw)):
        path = execution / name
        _require(
            files.read(path, sha256=sha256_bytes(payload), maximum=MAX_BENCHMARK_ENVELOPE_BYTES)
            == payload
        )
        metadata = path.lstat()
        _require(
            stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_gid == _ROOT_GID
            and not _ACL_NAMES.intersection(os.listxattr(path))
        )
    _validate_environment_installation(files, invocation.runtime, backend)
    files.assert_unchanged()
    return files


def prepare_cpu_benchmark_environment(
    prepared: PreparedBenchmarkHandoff,
    invocation: BenchmarkWorkerInvocation,
    *,
    backend: NativeEmbeddingBackendPins,
    owner_pid: int,
    expires_ns: int,
) -> PreparedCpuBenchmarkEnvironment:
    """Compatibility entry retains the original CPU-only boundary, without another writer."""
    if os.geteuid() != _ROOT_UID:
        raise BenchmarkHandoffError("BENCHMARK_HANDOFF_ROOT_REQUIRED")
    _require(invocation.device == "CPU" and invocation.runtime.profile == "CPU_INDEX_FP32")
    return prepare_benchmark_environment(
        prepared, invocation, backend=backend, owner_pid=owner_pid, expires_ns=expires_ns
    )
