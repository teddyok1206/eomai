"""Root CUDA INDEX observations only; no source grant, dispatch, ACK or retirement effect."""

from __future__ import annotations

import fcntl
import grp
import os
import pwd
import re
import signal
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cuda_index_ready import (
    MAX_NATIVE_CUDA_INDEX_READY_BYTES,
    NativeCudaIndexReady,
    parse_native_cuda_index_ready,
    validate_native_cuda_index_ready,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
    RootLocalStatEpoch,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
    observe_native_cuda_index_ready_resources,
    observe_native_cuda_index_retained_resources,
)
from eom_catalog_service.embedding_native_cuda_index_entry import NativeCudaIndexLaunchPins
from eom_catalog_service.embedding_native_cuda_index_launch import (
    CUDA_INDEX_ENTRY,
    CUDA_INDEX_ENTRY_SHA256,
    CUDA_INDEX_RUNTIME_ROOT,
    CUDA_INDEX_TEMPLATE,
    CUDA_INDEX_TEMPLATE_SHA256,
    native_cuda_index_launch_arguments,
    native_cuda_index_launch_environment_bytes,
    native_cuda_index_unit,
    parse_native_cuda_index_launch_environment,
)
from eom_catalog_service.embedding_native_installation_admission import (
    ProtectedCudaInstallationFiles,
    read_pinned_cuda_admission_receipt,
)
from eom_catalog_service.embedding_native_probe_observation import (
    NativeExecutableMapping,
    parse_native_executable_mappings,
    validate_native_cuda_executable_mappings,
)
from eom_catalog_service.embedding_runtime_files import (
    CUDA_LOADER_EMPTY_DIRECTORY,
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_native_cuda_process_status,
)
from eom_catalog_service.gpu_unit_policy_observation import observe_native_cuda_index_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

_PREFIX = Path("/opt/eom/conda/envs/eom-embedding-cuda")
_MAX_WORKER_FDS = 4096


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_INDEX_OBSERVATION_" + suffix)


def _epoch(value: os.stat_result) -> RootLocalStatEpoch:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _member(path: Path, *, mode: int, gid: int) -> RootLocalStatEpoch:
    value = path.lstat()
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == 0
        and value.st_gid == gid
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == mode
        and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(path)
        ),
        "HANDOFF_PROTECTION_CHANGED",
    )
    return _epoch(value)


def _accounts() -> tuple[int, int, int, int, int]:
    worker, worker_group = pwd.getpwnam("eom-embedding-cuda"), grp.getgrnam("eom-embedding-cuda")
    owner, owner_group = pwd.getpwnam("eom-workflow-runner"), grp.getgrnam("eom-workflow-runner")
    lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
    values = worker.pw_uid, worker_group.gr_gid, lease_gid, owner.pw_uid, owner_group.gr_gid
    _require(
        min(values) > 0
        and worker.pw_gid == worker_group.gr_gid
        and owner.pw_gid == owner_group.gr_gid
        and worker.pw_uid != owner.pw_uid
        and worker_group.gr_gid != lease_gid
        and set(os.getgrouplist(worker.pw_name, worker.pw_gid)) == {worker_group.gr_gid, lease_gid},
        "ACCOUNT_INVALID",
    )
    return values


@dataclass(frozen=True, slots=True)
class NativeCudaIndexObservationPins:
    launch: NativeCudaIndexLaunchPins
    request: IncrementalEmbeddingInput
    owner_pid: int
    owner_start_ticks: int

    def __post_init__(self) -> None:
        native_cuda_index_launch_arguments(self.launch)
        request = parse_incremental_embedding_input(raw_similarity_contract_value(self.request))
        _require(
            type(self.owner_pid) is int
            and 0 < self.owner_pid <= 2147483647
            and type(self.owner_start_ticks) is int
            and 0 < self.owner_start_ticks < 2**64
            and request.job_id == self.launch.job_id
            and request.space.runtime.device == "CUDA"
            and request.batch_size == request.threads == 4
            and sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
            == self.launch.input_raw_sha256,
            "BASIS_INVALID",
        )
        object.__setattr__(self, "request", request)


@dataclass(frozen=True, slots=True)
class NativeCudaIndexReadySnapshot:
    readiness: NativeCudaIndexReady
    raw_sha256: str
    epoch: RootLocalStatEpoch
    files: NumericalRuntimeFileSnapshots

    def assert_current(self) -> None:
        self.files.assert_unchanged()


@dataclass(frozen=True, slots=True)
class CapturedNativeCudaIndexLaunchFiles:
    """Owned installation/file closure; no live-owner/deadline requirement during cleanup."""

    basis: NativeCudaIndexObservationPins
    configuration: RootLocalNativeConfigurationPin
    device: CudaRuntimeDeviceCapture
    worker_uid: int
    worker_gid: int
    lease_gid: int
    owner_uid: int
    owner_gid: int
    files: NumericalRuntimeFileSnapshots
    installation: ProtectedCudaInstallationFiles
    inventory: PrefixRuntimeInventory
    host: ProtectedCudaEmbeddingHostClosure
    input_epoch: RootLocalStatEpoch
    ready_identity: tuple[int, ...]
    output_identities: tuple[tuple[int, ...], tuple[int, ...]]

    @property
    def execution(self) -> Path:
        return CUDA_INDEX_RUNTIME_ROOT / self.basis.launch.execution_id

    def assert_current(self) -> None:
        _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
        _require(
            _accounts()
            == (self.worker_uid, self.worker_gid, self.lease_gid, self.owner_uid, self.owner_gid),
            "ACCOUNT_CHANGED",
        )
        self.files.assert_unchanged()
        self.installation.assert_current()
        _require(
            _member(self.execution / "input.json", mode=0o600, gid=self.owner_gid)
            == self.input_epoch,
            "INPUT_CHANGED",
        )
        _require(
            _member(self.execution / "ready.json", mode=0o640, gid=self.owner_gid)[:6]
            == self.ready_identity,
            "READY_CHANGED",
        )
        for name, identity in zip(
            ("result.json", "vectors.f32"), self.output_identities, strict=True
        ):
            _require(
                _member(self.execution / name, mode=0o640, gid=self.owner_gid)[:6] == identity,
                "OUTPUT_IDENTITY_CHANGED",
            )

    def read_ready_snapshot(self) -> NativeCudaIndexReadySnapshot:
        return _read_ready_snapshot(self)

    def close(self) -> None:
        self.installation.close()

    def __enter__(self) -> CapturedNativeCudaIndexLaunchFiles:
        try:
            self.assert_current()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def capture_native_cuda_index_launch_files(
    basis: NativeCudaIndexObservationPins,
) -> CapturedNativeCudaIndexLaunchFiles:
    """Capture this original root handoff and complete installed file closure, never a grant."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(basis) is NativeCudaIndexObservationPins, "BASIS_INVALID")
    basis = NativeCudaIndexObservationPins(
        basis.launch, basis.request, basis.owner_pid, basis.owner_start_ticks
    )
    launch = basis.launch
    worker_uid, worker_gid, lease_gid, owner_uid, owner_gid = _accounts()
    configuration = RootLocalNativeConfigurationPin(
        configuration_id=launch.configuration_id,
        configuration_revision_id=launch.configuration_revision_id,
        configuration_sha256=launch.configuration_sha256,
        configuration_raw_sha256=launch.configuration_raw_sha256,
    )
    files = NumericalRuntimeFileSnapshots(0)
    installation = ProtectedCudaInstallationFiles(
        configuration, expected_receipt_raw_sha256=launch.receipt_raw_sha256
    )
    try:
        _require(
            installation.configuration_sha256 == configuration.configuration_sha256,
            "CONFIGURATION_CHANGED",
        )
        inventory, host = installation.inventory, installation.host
        _require(inventory.prefix == _PREFIX, "PREFIX_CHANGED")
        files.read(
            Path("/etc/systemd/system") / CUDA_INDEX_TEMPLATE,
            sha256=CUDA_INDEX_TEMPLATE_SHA256,
            maximum=65536,
        )
        files.read(CUDA_INDEX_ENTRY, sha256=CUDA_INDEX_ENTRY_SHA256, maximum=128 * 1024)
        files.observe_empty_directory(CUDA_LOADER_EMPTY_DIRECTORY)
        execution = CUDA_INDEX_RUNTIME_ROOT / launch.execution_id
        for path in (CUDA_INDEX_RUNTIME_ROOT, execution):
            value = path.lstat()
            _require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid == 0
                and value.st_gid == owner_gid
                and stat.S_IMODE(value.st_mode) == 0o750
                and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                    os.listxattr(path)
                ),
                "HANDOFF_PROTECTION_CHANGED",
            )
        expected_input = canonical_json_bytes(basis.request.model_dump(mode="json"))
        files.verify(
            execution / "input.json",
            sha256=launch.input_raw_sha256,
            size=len(expected_input),
            maximum=MAX_EMBEDDING_INPUT_BYTES,
        )
        environment = native_cuda_index_launch_environment_bytes(launch)
        _require(
            files.read(execution / "launch.env", sha256=sha256_bytes(environment), maximum=4096)
            == environment,
            "ENVIRONMENT_CHANGED",
        )
        _require(
            parse_native_cuda_index_launch_environment(
                environment, execution_id=launch.execution_id
            )
            == launch,
            "ENVIRONMENT_CHANGED",
        )
        _member(execution / "launch.env", mode=0o600, gid=owner_gid)
        input_epoch = _member(execution / "input.json", mode=0o600, gid=owner_gid)
        ready = _member(execution / "ready.json", mode=0o640, gid=owner_gid)
        outputs = tuple(
            _member(execution / name, mode=0o640, gid=owner_gid)[:6]
            for name in ("result.json", "vectors.f32")
        )
        _require(
            len({input_epoch[:2], ready[:2], *(value[:2] for value in outputs)}) == 4,
            "HANDOFF_ALIAS",
        )
        receipt, _ = read_pinned_cuda_admission_receipt(
            files, configuration, receipt_raw_sha256=launch.receipt_raw_sha256
        )
        _require(
            receipt.runtime_sha256 == basis.request.space.runtime.execution_runtime_sha256,
            "RUNTIME_CHANGED",
        )
        captured = CapturedNativeCudaIndexLaunchFiles(
            basis,
            configuration,
            receipt.device_capture,
            worker_uid,
            worker_gid,
            lease_gid,
            owner_uid,
            owner_gid,
            files,
            installation,
            inventory,
            host,
            input_epoch,
            ready[:6],
            (outputs[0], outputs[1]),
        )
        captured.assert_current()
        return captured
    except BaseException:
        installation.close()
        raise


def _read_ready_snapshot(
    captured: CapturedNativeCudaIndexLaunchFiles,
) -> NativeCudaIndexReadySnapshot:
    captured.assert_current()
    path = captured.execution / "ready.json"
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        initial = _epoch(os.fstat(descriptor))
        _require(
            initial == _member(path, mode=0o640, gid=captured.owner_gid)
            and initial[:6] == captured.ready_identity
            and 0 <= initial[6] <= MAX_NATIVE_CUDA_INDEX_READY_BYTES,
            "READY_INVALID",
        )
        # Never let an empty-file reader's shared lock defeat the one first writer's
        # nonblocking exclusive lock. A nonempty partial write still requires LOCK_SH.
        _require(initial[6] > 0, "NOT_READY")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("NATIVE_CUDA_INDEX_OBSERVATION_NOT_READY") from None
        before = _epoch(os.fstat(descriptor))
        _require(
            before == _member(path, mode=0o640, gid=captured.owner_gid)
            and before[:6] == captured.ready_identity
            and 0 <= before[6] <= MAX_NATIVE_CUDA_INDEX_READY_BYTES,
            "READY_INVALID",
        )
        _require(before[6] > 0, "NOT_READY")
        files = NumericalRuntimeFileSnapshots(0)
        member = files.observe_protected_member_bytes(
            path, maximum=MAX_NATIVE_CUDA_INDEX_READY_BYTES
        )
        _require(before == _epoch(os.fstat(descriptor)) == _epoch(path.lstat()), "READY_CHANGED")
        readiness = parse_native_cuda_index_ready(member.raw)
        launch = captured.basis.launch
        validate_native_cuda_index_ready(
            captured.basis.request,
            readiness,
            execution_id=launch.execution_id,
            native_launch_job_id=launch.job_id,
            launch_association_sha256=launch.association_sha256,
            input_raw_sha256=launch.input_raw_sha256,
            configuration=captured.configuration,
            receipt_raw_sha256=launch.receipt_raw_sha256,
            expected_device=captured.device,
        )
        _require(
            (readiness.worker_uid, readiness.worker_gid, readiness.supplementary_gids)
            == (captured.worker_uid, captured.worker_gid, (captured.lease_gid,)),
            "ACCOUNT_CHANGED",
        )
        files.assert_unchanged()
        captured.assert_current()
        return NativeCudaIndexReadySnapshot(readiness, member.sha256, before, files)
    finally:
        os.close(descriptor)


def _owner_current(captured: CapturedNativeCudaIndexLaunchFiles) -> None:
    basis = captured.basis
    process = Path("/proc") / str(basis.owner_pid)

    def born() -> int:
        return native_process_start_ticks(
            read_live_runtime_os_file(
                process / "stat", maximum=65536, owner_uid=captured.owner_uid
            ),
            basis.owner_pid,
        )

    first = born()
    raw = read_live_runtime_os_file(
        process / "status", maximum=128 * 1024, owner_uid=captured.owner_uid
    )
    fields: dict[bytes, tuple[bytes, ...]] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(b":")
        if name in {b"Uid", b"Gid"}:
            _require(bool(separator) and name not in fields, "OWNER_CHANGED")
            fields[name] = tuple(value.split())
    _require(
        fields
        == {
            b"Uid": (str(captured.owner_uid).encode(),) * 4,
            b"Gid": (str(captured.owner_gid).encode(),) * 4,
        }
        and first == born() == basis.owner_start_ticks,
        "OWNER_CHANGED",
    )


def _descriptor_info(pid: int, descriptor: int, uid: int) -> tuple[int, int, int]:
    raw = read_live_runtime_os_file(
        Path("/proc") / str(pid) / "fdinfo" / str(descriptor), maximum=16384, owner_uid=uid
    )
    fields: dict[str, str] = {}
    for line in raw.decode("ascii").splitlines():
        key, separator, value = line.partition(":")
        _require(
            bool(separator) and key in {"pos", "flags", "mnt_id", "ino"} and key not in fields,
            "DESCRIPTOR_CHANGED",
        )
        fields[key] = value.strip()
    _require(
        set(fields) == {"pos", "flags", "mnt_id", "ino"}
        and re.fullmatch(r"[0-9]{1,20}", fields["pos"]) is not None
        and re.fullmatch(r"[0-7]{1,16}", fields["flags"]) is not None
        and re.fullmatch(r"[1-9][0-9]{0,19}", fields["mnt_id"]) is not None
        and re.fullmatch(r"[1-9][0-9]{0,19}", fields["ino"]) is not None,
        "DESCRIPTOR_CHANGED",
    )
    return int(fields["pos"]), int(fields["flags"], 8), int(fields["ino"])


def _handoff_descriptors(
    captured: CapturedNativeCudaIndexLaunchFiles, snapshot: NativeCudaIndexReadySnapshot
) -> tuple[tuple[int, ...], ...]:
    pid, uid = snapshot.readiness.pid, captured.worker_uid
    process = Path("/proc") / str(pid)
    observed: list[tuple[int, ...]] = []

    def regular(
        number: int, expected: tuple[int, ...], *, access: int, position: int, cloexec: bool
    ) -> None:
        value = _epoch((process / "fd" / str(number)).stat())
        pos, flags, inode = _descriptor_info(pid, number, uid)
        _require(
            value == expected
            and inode == value[1]
            and pos == position
            and flags & (os.O_ACCMODE | os.O_APPEND | os.O_PATH) == access
            and (not cloexec or bool(flags & os.O_CLOEXEC)),
            "DESCRIPTOR_CHANGED",
        )
        observed.append((number, *value, pos, flags))

    regular(0, captured.input_epoch, access=os.O_RDONLY, position=0, cloexec=False)
    regular(3, snapshot.epoch, access=os.O_RDWR, position=snapshot.epoch[6], cloexec=True)
    for number in (1, 2):
        value = (process / "fd" / str(number)).stat()
        pos, flags, inode = _descriptor_info(pid, number, uid)
        _require(
            stat.S_ISCHR(value.st_mode)
            and (os.major(value.st_rdev), os.minor(value.st_rdev)) == (1, 3)
            and inode == value.st_ino
            and flags & (os.O_ACCMODE | os.O_APPEND | os.O_PATH) == os.O_WRONLY,
            "DIAGNOSTICS_CHANGED",
        )
        observed.append((number, *_epoch(value), pos, flags))
    matches: list[list[int]] = [[], []]
    with os.scandir(process / "fd") as entries:
        for count, entry in enumerate(entries, 1):
            _require(
                count <= _MAX_WORKER_FDS and re.fullmatch(r"[0-9]{1,7}", entry.name) is not None,
                "DESCRIPTOR_CHANGED",
            )
            number = int(entry.name)
            if number < 4:
                continue
            output_epoch = _epoch((process / "fd" / entry.name).stat())
            for index, identity in enumerate(captured.output_identities):
                if output_epoch[:2] == identity[:2]:
                    _require(
                        output_epoch[:6] == identity and output_epoch[6] == 0, "OUTPUT_CHANGED"
                    )
                    regular(number, output_epoch, access=os.O_WRONLY, position=0, cloexec=True)
                    matches[index].append(number)
    _require(all(len(rows) == 1 for rows in matches), "OUTPUT_CHANGED")
    return tuple(sorted(observed))


@dataclass(frozen=True, slots=True)
class NativeCudaIndexReadyObservation:
    execution_id: str
    job_id: str
    unit: CpuUnitObservation
    pid: int
    start_time_ticks: int
    cgroup: str
    association_sha256: str
    input_raw_sha256: str
    ready_raw_sha256: str
    ready_epoch: RootLocalStatEpoch
    environment_raw_sha256: str
    effective_policy_sha256: str
    loaded_members_sha256: str
    executable_members: tuple[NativeExecutableMapping, ...]
    resources: CudaProbeResourceObservation
    device: CudaRuntimeDeviceCapture


def observe_native_cuda_index_ready(
    captured: CapturedNativeCudaIndexLaunchFiles,
) -> NativeCudaIndexReadyObservation:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(captured) is CapturedNativeCudaIndexLaunchFiles, "BASIS_INVALID")
    snapshot = captured.read_ready_snapshot()
    ready, launch = snapshot.readiness, captured.basis.launch
    unit = native_cuda_index_unit(launch.execution_id)
    cgroup = "/system.slice/" + unit
    before = inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE)
    _require(
        before.main_pid == ready.pid
        and before.status.active_state == "activating"
        and before.status.sub_state == "start"
        and before.status.process_started
        and before.exited_monotonic == 0
        and re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is not None,
        "NOT_RUNNING",
    )
    policy = observe_native_cuda_index_unit_policy(unit)
    process = Path("/proc") / str(ready.pid)
    arguments = (
        str(_PREFIX / "bin/python3.12"),
        "-I",
        "-B",
        str(CUDA_INDEX_ENTRY),
        *native_cuda_index_launch_arguments(launch),
    )

    def read(name: str, maximum: int = 128 * 1024) -> bytes:
        return read_live_runtime_os_file(
            process / name, maximum=maximum, owner_uid=captured.worker_uid
        )

    def current() -> None:
        now = time.monotonic_ns()
        _require(now < launch.expires_ns <= now + 180 * 10**9, "EXPIRED")
        _owner_current(captured)
        _require(
            native_process_start_ticks(read("stat"), ready.pid) == ready.start_time_ticks,
            "PROCESS_CHANGED",
        )
        _require(
            read("cgroup") == f"0::{cgroup}\n".encode()
            and root_owned_unit_processes(unit) == (ready.pid,),
            "CGROUP_CHANGED",
        )
        status = read("status")
        require_native_cuda_process_status(
            status, uid=captured.worker_uid, gid=captured.worker_gid, lease_gid=captured.lease_gid
        )
        fields = dict(line.split(":", 1) for line in status.decode("ascii").splitlines())
        mask = fields.get("SigBlk", "").strip()
        _require(
            fields.get("Pid", "").strip() == str(ready.pid)
            and fields.get("Tgid", "").strip() == str(ready.pid)
            and fields.get("Threads", "").strip() == "1"
            and os.listdir(process / "task") == [str(ready.pid)]
            and re.fullmatch(r"[0-9a-f]{16}", mask) is not None
            and bool(int(mask, 16) & (1 << (signal.SIGUSR1 - 1))),
            "ACK_FRAME_CHANGED",
        )
        _require(
            read("cmdline", 8192) == b"\0".join(value.encode() for value in arguments) + b"\0",
            "ARGUMENTS_CHANGED",
        )
        expected, cwd = CUDA_LOADER_EMPTY_DIRECTORY.lstat(), (process / "cwd").stat()
        _require((expected.st_dev, expected.st_ino) == (cwd.st_dev, cwd.st_ino), "CWD_CHANGED")
        _require(inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE) == before, "UNIT_CHANGED")
        snapshot.assert_current()
        captured.assert_current()

    current()
    descriptors = _handoff_descriptors(captured, snapshot)
    observe_runtime_device(captured.device)
    members = validate_native_cuda_executable_mappings(
        read("maps", 2 * 1024**2),
        inventory=captured.inventory,
        host=captured.host,
    )
    resources = observe_native_cuda_index_ready_resources(
        ready, unit=unit, lease_gid=captured.lease_gid
    )
    _require(observe_cuda_probe_gpu_clients(captured.device) == (), "GPU_BUSY")
    current()
    _require(
        parse_native_executable_mappings(read("maps", 2 * 1024**2)) == members
        and _handoff_descriptors(captured, snapshot) == descriptors
        and observe_native_cuda_index_ready_resources(
            ready, unit=unit, lease_gid=captured.lease_gid
        )
        == resources
        and observe_native_cuda_index_unit_policy(unit) == policy,
        "PROCESS_CHANGED",
    )
    late = captured.read_ready_snapshot()
    _require(
        (late.raw_sha256, late.epoch) == (snapshot.raw_sha256, snapshot.epoch), "READY_CHANGED"
    )
    late.assert_current()
    observe_runtime_device(captured.device)
    _require(observe_cuda_probe_gpu_clients(captured.device) == (), "GPU_BUSY")
    current()
    return NativeCudaIndexReadyObservation(
        launch.execution_id,
        launch.job_id,
        before,
        ready.pid,
        ready.start_time_ticks,
        cgroup,
        launch.association_sha256,
        launch.input_raw_sha256,
        snapshot.raw_sha256,
        snapshot.epoch,
        sha256_bytes(native_cuda_index_launch_environment_bytes(launch)),
        policy,
        sha256_bytes(
            canonical_json_bytes(
                [
                    {"path": str(member.path), "device": member.device, "inode": member.inode}
                    for member in members
                ]
            )
        ),
        members,
        resources,
        captured.device,
    )


@dataclass(frozen=True, slots=True)
class NativeCudaIndexTerminalObservation:
    ready: NativeCudaIndexReadyObservation
    terminal_unit: CpuUnitObservation
    original_outcome: Literal["SUCCEEDED", "FAILED"]
    observed_at_utc: str


def require_native_cuda_index_observation_basis(
    ready: NativeCudaIndexReadyObservation,
    captured: CapturedNativeCudaIndexLaunchFiles,
) -> str:
    """Pinned linkage only; no live owner/deadline needed to prove later physical cleanup."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        type(ready) is NativeCudaIndexReadyObservation
        and type(captured) is CapturedNativeCudaIndexLaunchFiles,
        "BASIS_INVALID",
    )
    snapshot, launch = captured.read_ready_snapshot(), captured.basis.launch
    _require(
        (ready.execution_id, ready.job_id, ready.pid, ready.start_time_ticks)
        == (
            launch.execution_id,
            launch.job_id,
            snapshot.readiness.pid,
            snapshot.readiness.start_time_ticks,
        )
        and ready.association_sha256 == launch.association_sha256
        and ready.input_raw_sha256 == launch.input_raw_sha256
        and (ready.ready_raw_sha256, ready.ready_epoch) == (snapshot.raw_sha256, snapshot.epoch)
        and ready.environment_raw_sha256
        == sha256_bytes(native_cuda_index_launch_environment_bytes(launch))
        and ready.device == captured.device,
        "PINNED_BASIS_CHANGED",
    )
    unit = native_cuda_index_unit(ready.execution_id)
    _require(ready.cgroup == "/system.slice/" + unit, "BASIS_INVALID")
    return unit


def require_native_cuda_index_processes_ended(ready: NativeCudaIndexReadyObservation) -> None:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(ready) is NativeCudaIndexReadyObservation, "BASIS_INVALID")
    unit = native_cuda_index_unit(ready.execution_id)
    _require(ready.cgroup == "/system.slice/" + unit, "BASIS_INVALID")
    original = Path("/proc") / str(ready.pid)
    try:
        uid = original.lstat().st_uid
        raw = read_live_runtime_os_file(original / "stat", maximum=65536, owner_uid=uid)
    except FileNotFoundError:
        pass
    else:
        _require(
            native_process_start_ticks(raw, ready.pid) != ready.start_time_ticks,
            "TERMINATION_UNCERTAIN",
        )
    try:
        members = root_owned_unit_processes(unit)
    except FileNotFoundError:
        _require(not (Path("/sys/fs/cgroup/system.slice") / unit).exists(), "TERMINATION_UNCERTAIN")
        members = ()
    _require(members == (), "TERMINATION_UNCERTAIN")


def verify_native_cuda_index_terminal(
    ready: NativeCudaIndexReadyObservation,
    captured: CapturedNativeCudaIndexLaunchFiles,
) -> NativeCudaIndexTerminalObservation:
    """Original terminal/retained-fence readback, not successful retirement or publication."""
    unit = require_native_cuda_index_observation_basis(ready, captured)
    before = inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE)
    _require(
        before.invocation_id == ready.unit.invocation_id
        and before.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic,
        "TERMINATION_UNCERTAIN",
    )
    outcome = gpu_unit_terminal_outcome(before)

    def ended() -> None:
        require_native_cuda_index_processes_ended(ready)
        _require(
            inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE) == before, "TERMINATION_UNCERTAIN"
        )

    ended()
    observe_runtime_device(ready.device)
    observe_native_cuda_index_retained_resources(ready.resources, unit=unit)
    _require(observe_cuda_probe_gpu_clients(ready.device) == (), "GPU_CLEANUP_UNCERTAIN")
    observe_native_cuda_index_retained_resources(ready.resources, unit=unit)
    _require(
        observe_native_cuda_index_unit_policy(unit) == ready.effective_policy_sha256,
        "POLICY_CHANGED",
    )
    captured.assert_current()
    observe_runtime_device(ready.device)
    ended()
    return NativeCudaIndexTerminalObservation(
        ready,
        before,
        outcome,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )
