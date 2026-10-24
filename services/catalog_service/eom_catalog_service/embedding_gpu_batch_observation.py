"""Root batch machine/file/READY observations, never source authority, ACK or retirement."""

from __future__ import annotations

import grp
import os
import pwd
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationReady,
    parse_embedding_gpu_control,
    validate_embedding_gpu_allocation_link,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_identifiers import sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
    observe_embedding_gpu_allocation_resources,
)
from eom_catalog_service.embedding_gpu_batch_handoff import (
    PreparedEmbeddingGpuBatch,
    validate_embedding_gpu_batch_original,
    validate_embedding_gpu_batch_reconciliation_pins,
)
from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_RUNTIME_ROOT,
    GPU_BATCH_SOCKET_TEMPLATE,
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_environment,
    native_embedding_gpu_batch_launch_arguments,
    native_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_gpu_batch_unit_descriptor import (
    embedding_gpu_batch_descriptor_bytes,
    embedding_gpu_batch_descriptor_path,
    inspect_embedding_gpu_batch_unit,
    require_embedding_gpu_batch_descriptor,
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
from eom_catalog_service.gpu_unit_policy_observation import observe_embedding_gpu_batch_unit_policy

_PREFIX = Path("/opt/eom/conda/envs/eom-embedding-cuda")
_SERVICE_SHA = "sha256:65b46025623c85260c39f50ac51318ad26ce4af260cef46c10b663f513e4c6da"
_SOCKET_SHA = "sha256:77be677e8333c36b2b11b7542c2eed6be4421d9a927af0aa5a53f76b0cff2bfb"
_ENTRY_SHA = "sha256:da1c1ef262ff2a52adfdd0b9dc726f1cc6df31c1aef2d51478a54e5f6edd3909"
_ENTRY_MEMBER = "lib/python3.12/site-packages/eom_catalog_service/embedding_gpu_batch_entry.py"


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_OBSERVATION_INVALID")


def _epoch(value: os.stat_result) -> tuple[int, ...]:
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


def _member(path: Path, *, mode: int, gid: int) -> tuple[int, ...]:
    value = path.lstat()
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == 0
        and value.st_gid == gid
        and stat.S_IMODE(value.st_mode) == mode
        and value.st_nlink == 1
        and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(path)
        )
    )
    return _epoch(value)


def _accounts() -> tuple[int, int, int]:
    worker = pwd.getpwnam("eom-embedding-cuda")
    group = grp.getgrnam("eom-embedding-cuda")
    lease = grp.getgrnam("eom-gpu-lease").gr_gid
    _require(
        min(worker.pw_uid, group.gr_gid, lease) > 0
        and worker.pw_gid == group.gr_gid
        and group.gr_gid != lease
        and set(os.getgrouplist(worker.pw_name, worker.pw_gid)) == {group.gr_gid, lease}
    )
    return worker.pw_uid, group.gr_gid, lease


@dataclass(frozen=True, slots=True)
class CapturedEmbeddingGpuBatchMachine:
    prepared: PreparedEmbeddingGpuBatch
    files: NumericalRuntimeFileSnapshots
    installation: ProtectedCudaInstallationFiles
    device: CudaRuntimeDeviceCapture
    worker_uid: int
    worker_gid: int
    lease_gid: int
    owner_gid: int
    allocation_epoch: tuple[int, ...]
    output_identities: tuple[tuple[int, ...], tuple[int, ...]]

    @property
    def execution(self) -> Path:
        return GPU_BATCH_RUNTIME_ROOT / self.prepared.launch.attempt_hex

    def assert_current(self) -> None:
        _require(os.getresuid() == (0, 0, 0))
        _require(_accounts() == (self.worker_uid, self.worker_gid, self.lease_gid))
        _require(fixed_owner_identity().owner_gid == self.owner_gid)
        self.files.assert_unchanged()
        self.installation.assert_current()
        _require(
            _member(self.execution / "input.json", mode=0o600, gid=self.owner_gid)[:6]
            == self.prepared.input_epoch[:6]
        )
        for name, identity in zip(
            ("result.json", "vectors.f32"), self.output_identities, strict=True
        ):
            _require(_member(self.execution / name, mode=0o640, gid=self.owner_gid)[:6] == identity)

    def assert_precompute(self) -> None:
        _require(self.prepared.launch.root_pid == os.getpid())
        self.assert_current()
        _require(
            _member(self.execution / "input.json", mode=0o600, gid=self.owner_gid)
            == self.prepared.input_epoch
            and self.prepared.input_epoch[6] == 0
        )
        try:
            (self.execution / "input-grant.json").lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("EMBEDDING_GPU_BATCH_OBSERVATION_INVALID")
        _require(
            all(
                _member(self.execution / name, mode=0o640, gid=self.owner_gid)[6] == 0
                for name in ("result.json", "vectors.f32")
            )
        )

    def close(self) -> None:
        self.installation.close()

    def __enter__(self) -> CapturedEmbeddingGpuBatchMachine:
        try:
            self.assert_current()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def capture_embedding_gpu_batch_machine(
    prepared: PreparedEmbeddingGpuBatch,
) -> CapturedEmbeddingGpuBatchMachine:
    """Capture the original root staging and installed CUDA closure, not a work grant."""
    _require(type(prepared) is PreparedEmbeddingGpuBatch)
    validate_embedding_gpu_batch_original(prepared.launch, prepared.request)
    captured = _capture_embedding_gpu_batch_files(prepared)
    try:
        captured.assert_precompute()
        return captured
    except BaseException:
        captured.close()
        raise


def capture_embedding_gpu_batch_reconciliation(
    prepared: PreparedEmbeddingGpuBatch, original: EmbeddingGpuBatchReadyObservation
) -> CapturedEmbeddingGpuBatchMachine:
    """Recapture exact original file identities after controller restart; never GRANT.

    The caller restores this original observation from its protected immutable
    record. Precompute still requires the original PID, empty input and no grant
    intent; cleanup must not require the original controller to remain alive.
    """
    _require(
        type(prepared) is PreparedEmbeddingGpuBatch
        and type(original) is EmbeddingGpuBatchReadyObservation
    )
    validate_embedding_gpu_allocation_link(prepared.request, original.readiness)
    _require(prepared.input_epoch == original.input_epoch)
    captured = _capture_embedding_gpu_batch_files(prepared)
    try:
        _require(
            captured.allocation_epoch == original.allocation_epoch
            and captured.output_identities == original.output_identities
        )
        return captured
    except BaseException:
        captured.close()
        raise


def _capture_embedding_gpu_batch_files(
    prepared: PreparedEmbeddingGpuBatch,
) -> CapturedEmbeddingGpuBatchMachine:
    """Shared protected files only; explicit public compositions choose their own phase."""
    _require(os.getresuid() == (0, 0, 0) and type(prepared) is PreparedEmbeddingGpuBatch)
    launch, request = prepared.launch, prepared.request
    raw = validate_embedding_gpu_batch_reconciliation_pins(launch, request)
    _require(len(prepared.input_epoch) == 9)
    worker_uid, worker_gid, lease_gid = _accounts()
    owner_gid = fixed_owner_identity().owner_gid
    files = NumericalRuntimeFileSnapshots(0)
    installation = ProtectedCudaInstallationFiles(
        request.configuration, expected_receipt_raw_sha256=request.receipt_raw_sha256
    )
    try:
        _require(
            installation.configuration_sha256 == launch.backend.configuration_sha256
            and installation.inventory.prefix == _PREFIX
        )
        files.read(
            Path("/etc/systemd/system") / GPU_BATCH_TEMPLATE, sha256=_SERVICE_SHA, maximum=65536
        )
        files.read(
            Path("/etc/systemd/system") / GPU_BATCH_SOCKET_TEMPLATE,
            sha256=_SOCKET_SHA,
            maximum=65536,
        )
        descriptor_raw = embedding_gpu_batch_descriptor_bytes(launch.attempt_hex)
        files.read(
            embedding_gpu_batch_descriptor_path(launch.attempt_hex),
            sha256=sha256_bytes(descriptor_raw),
            maximum=4096,
        )
        entries = {entry.relative_member: entry for entry in installation.inventory.entries}
        _require(_ENTRY_MEMBER in entries and entries[_ENTRY_MEMBER].sha256 == _ENTRY_SHA)
        files.verify(
            _PREFIX / _ENTRY_MEMBER,
            sha256=_ENTRY_SHA,
            size=entries[_ENTRY_MEMBER].epoch[6],
            maximum=128 * 1024,
        )
        files.observe_empty_directory(CUDA_LOADER_EMPTY_DIRECTORY)
        execution = GPU_BATCH_RUNTIME_ROOT / launch.attempt_hex
        for path in (GPU_BATCH_RUNTIME_ROOT, execution):
            value = path.lstat()
            _require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid == 0
                and value.st_gid == owner_gid
                and stat.S_IMODE(value.st_mode) == 0o750
                and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                    os.listxattr(path)
                )
            )
        _require(
            files.read(
                execution / "allocation.json",
                sha256=launch.allocation_raw_sha256,
                maximum=32 * 1024,
            )
            == raw
        )
        environment = native_embedding_gpu_batch_environment(launch)
        _require(
            files.read(execution / "launch.env", sha256=sha256_bytes(environment), maximum=4096)
            == environment
        )
        allocation_epoch = _member(execution / "allocation.json", mode=0o600, gid=owner_gid)
        _member(execution / "launch.env", mode=0o600, gid=owner_gid)
        outputs = tuple(
            _member(execution / name, mode=0o640, gid=owner_gid)[:6]
            for name in ("result.json", "vectors.f32")
        )
        _require(
            len(
                {
                    prepared.input_epoch[:2],
                    *(identity[:2] for identity in outputs),
                    _member(execution / "allocation.json", mode=0o600, gid=owner_gid)[:2],
                }
            )
            == 4
        )
        receipt, _ = read_pinned_cuda_admission_receipt(
            files, request.configuration, receipt_raw_sha256=request.receipt_raw_sha256
        )
        captured = CapturedEmbeddingGpuBatchMachine(
            prepared,
            files,
            installation,
            receipt.device_capture,
            worker_uid,
            worker_gid,
            lease_gid,
            owner_gid,
            allocation_epoch,
            (outputs[0], outputs[1]),
        )
        captured.assert_current()
        return captured
    except BaseException:
        installation.close()
        raise


@dataclass(frozen=True, slots=True)
class EmbeddingGpuBatchReadyObservation:
    readiness: EmbeddingGpuAllocationReady
    unit: CpuUnitObservation
    cgroup: str
    effective_policy_sha256: str
    executable_members: tuple[NativeExecutableMapping, ...]
    resources: CudaProbeResourceObservation
    input_epoch: tuple[int, ...]
    allocation_epoch: tuple[int, ...]
    output_identities: tuple[tuple[int, ...], tuple[int, ...]]


def _handoff_descriptors(
    captured: CapturedEmbeddingGpuBatchMachine, pid: int
) -> tuple[tuple[int, ...], ...]:
    """Read real process descriptor metadata only; never read document/vector bytes."""
    process = Path("/proc") / str(pid)
    observed = []

    def regular(
        number: int, expected: tuple[int, ...], *, access: int, position: int, cloexec: bool
    ) -> None:
        actual = _epoch((process / "fd" / str(number)).stat())
        raw = read_live_runtime_os_file(
            process / "fdinfo" / str(number), maximum=16384, owner_uid=captured.worker_uid
        )
        fields = {}
        for line in raw.decode("ascii").splitlines():
            name, separator, value = line.partition(":")
            _require(
                bool(separator) and name in {"pos", "flags", "mnt_id", "ino"} and name not in fields
            )
            fields[name] = value.strip()
        _require(
            set(fields) == {"pos", "flags", "mnt_id", "ino"}
            and re.fullmatch(r"[0-7]{1,16}", fields["flags"]) is not None
        )
        flags = int(fields["flags"], 8)
        _require(
            actual == expected
            and fields["ino"] == str(actual[1])
            and fields["pos"] == str(position)
            and flags & (os.O_ACCMODE | os.O_APPEND | os.O_PATH) == access
            and (not cloexec or bool(flags & os.O_CLOEXEC))
        )
        observed.append((number, *actual, flags, position))

    regular(0, captured.prepared.input_epoch, access=os.O_RDONLY, position=0, cloexec=False)
    for number in (1, 2):
        value = (process / "fd" / str(number)).stat()
        _require(
            stat.S_ISCHR(value.st_mode)
            and (os.major(value.st_rdev), os.minor(value.st_rdev)) == (1, 3)
        )
        regular(number, _epoch(value), access=os.O_WRONLY, position=0, cloexec=False)
    identities = {captured.allocation_epoch[:2]: ("allocation", captured.allocation_epoch)}
    identities.update(
        {
            identity[:2]: (name, identity)
            for name, identity in zip(
                ("result", "vectors"), captured.output_identities, strict=True
            )
        }
    )
    matches: set[str] = set()
    with os.scandir(process / "fd") as entries:
        for count, item in enumerate(entries, 1):
            _require(count <= 4096 and re.fullmatch(r"[0-9]{1,7}", item.name) is not None)
            number = int(item.name)
            if number < 3:
                continue
            actual = _epoch((process / "fd" / item.name).stat())
            found = identities.get(actual[:2])
            if found is None:
                continue
            name, identity = found
            _require(name not in matches)
            matches.add(name)
            if name == "allocation":
                regular(number, identity, access=os.O_RDONLY, position=identity[6], cloexec=True)
            else:
                _require(actual[:6] == identity and actual[6] == 0)
                regular(number, actual, access=os.O_WRONLY, position=0, cloexec=True)
    _require(matches == {"allocation", "result", "vectors"})
    return tuple(sorted(observed))


def observe_embedding_gpu_batch_ready(
    captured: CapturedEmbeddingGpuBatchMachine, readiness: EmbeddingGpuAllocationReady
) -> EmbeddingGpuBatchReadyObservation:
    """Independent original-unit/process/kernel facts before root may send compute GRANT."""
    _require(os.getresuid() == (0, 0, 0) and type(captured) is CapturedEmbeddingGpuBatchMachine)
    checked = parse_embedding_gpu_control(readiness)
    _require(type(checked) is EmbeddingGpuAllocationReady)
    assert isinstance(checked, EmbeddingGpuAllocationReady)
    validate_embedding_gpu_allocation_link(captured.prepared.request, checked)
    launch = captured.prepared.launch
    unit = native_embedding_gpu_batch_unit(launch.attempt_hex)
    cgroup = "/system.slice/" + unit
    before = inspect_embedding_gpu_batch_unit(unit, template=GPU_BATCH_TEMPLATE)
    require_embedding_gpu_batch_descriptor(launch.attempt_hex, before.drop_in_paths)
    _require(
        before.main_pid == checked.pid
        and before.status.active_state == "activating"
        and before.status.sub_state == "start"
        and before.status.process_started
        and before.exited_monotonic == 0
        and re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is not None
    )
    _require(
        (checked.worker_uid, checked.worker_gid, checked.supplementary_gids)
        == (captured.worker_uid, captured.worker_gid, (captured.lease_gid,))
        and checked.expected_device_capture == captured.device
    )
    process = Path("/proc") / str(checked.pid)
    policy = observe_embedding_gpu_batch_unit_policy(unit)
    arguments = (
        str(_PREFIX / "bin/python3.12"),
        "-I",
        "-B",
        "-m",
        "eom_catalog_service.embedding_gpu_batch_entry",
        *native_embedding_gpu_batch_launch_arguments(launch),
    )

    def read(name: str, maximum: int = 128 * 1024) -> bytes:
        return read_live_runtime_os_file(
            process / name, maximum=maximum, owner_uid=captured.worker_uid
        )

    def current() -> None:
        _require(time.monotonic_ns() < captured.prepared.request.expires_monotonic_ns)
        captured.assert_precompute()
        _require(native_process_start_ticks(read("stat"), checked.pid) == checked.start_time_ticks)
        _require(
            read("cgroup") == f"0::{cgroup}\n".encode()
            and root_owned_unit_processes(unit) == (checked.pid,)
        )
        status = read("status")
        require_native_cuda_process_status(
            status, uid=captured.worker_uid, gid=captured.worker_gid, lease_gid=captured.lease_gid
        )
        fields = dict(line.split(":", 1) for line in status.decode("ascii").splitlines())
        _require(
            fields.get("Pid", "").strip() == str(checked.pid)
            and fields.get("Tgid", "").strip() == str(checked.pid)
            and fields.get("Threads", "").strip() == "1"
            and os.listdir(process / "task") == [str(checked.pid)]
        )
        _require(read("cmdline", 8192) == b"\0".join(value.encode() for value in arguments) + b"\0")
        actual, expected = (process / "cwd").stat(), CUDA_LOADER_EMPTY_DIRECTORY.lstat()
        _require((actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino))
        _require(inspect_embedding_gpu_batch_unit(unit, template=GPU_BATCH_TEMPLATE) == before)

    current()
    descriptors = _handoff_descriptors(captured, checked.pid)
    observe_runtime_device(captured.device)
    members = validate_native_cuda_executable_mappings(
        read("maps", 2 * 1024**2),
        inventory=captured.installation.inventory,
        host=captured.installation.host,
    )
    resources = observe_embedding_gpu_allocation_resources(
        checked, unit=unit, lease_gid=captured.lease_gid
    )
    _require(observe_cuda_probe_gpu_clients(captured.device) == ())
    current()
    _require(
        parse_native_executable_mappings(read("maps", 2 * 1024**2)) == members
        and _handoff_descriptors(captured, checked.pid) == descriptors
        and observe_embedding_gpu_allocation_resources(
            checked, unit=unit, lease_gid=captured.lease_gid
        )
        == resources
        and observe_embedding_gpu_batch_unit_policy(unit) == policy
    )
    observe_runtime_device(captured.device)
    _require(observe_cuda_probe_gpu_clients(captured.device) == ())
    current()
    return EmbeddingGpuBatchReadyObservation(
        checked,
        before,
        cgroup,
        policy,
        members,
        resources,
        captured.prepared.input_epoch,
        captured.allocation_epoch,
        captured.output_identities,
    )
