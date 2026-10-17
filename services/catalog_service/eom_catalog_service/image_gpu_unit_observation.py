"""Root-only image unit observations, not dispatch, ACK, store retirement or model admission."""

from __future__ import annotations

import grp
import os
import pwd
import re
import shlex
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.models import Sha256
from eom_identifiers import sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    ImageUnitGpuResources,
    observe_image_unit_gpu_resources,
    observe_image_unit_gpu_retained_resources,
)
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import native_process_start_ticks
from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_role, image_gpu_unit_template

_BOOTSTRAP = Path("/usr/local/libexec/eom-image-runtime/run_gpu_unit.py")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("IMAGE_GPU_UNIT_" + suffix)


def _status(raw: bytes, *, pid: int, tid: int, uid: int, gid: int, lease_gid: int) -> None:
    fields = {}
    for line in raw.decode("ascii").splitlines():
        key, separator, value = line.partition(":")
        _require(bool(separator) and key not in fields, "PROCESS_IDENTITY_INVALID")
        fields[key] = value.strip()
    groups = fields.get("Groups", "").split()
    _require(
        all(re.fullmatch(r"[1-9][0-9]{0,9}", group) is not None for group in groups),
        "PROCESS_IDENTITY_INVALID",
    )
    gids = {int(group) for group in groups}
    _require(
        len(gids) == len(groups) and lease_gid in gids and gids <= {gid, lease_gid},
        "PROCESS_IDENTITY_INVALID",
    )
    _require(
        fields.get("Uid", "").split() == [str(uid)] * 4
        and fields.get("Gid", "").split() == [str(gid)] * 4
        and fields.get("Pid") == str(tid)
        and fields.get("Tgid") == str(pid)
        and fields.get("NoNewPrivs") == "1"
        and all(
            fields.get(name) == "0000000000000000"
            for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        ),
        "PROCESS_IDENTITY_INVALID",
    )
    blocked = fields.get("SigBlk", "")
    _require(
        re.fullmatch(r"[0-9a-f]{16}", blocked) is not None
        and bool(int(blocked, 16) & (1 << (signal.SIGUSR1 - 1))),
        "ACK_SIGNAL_NOT_RESERVED",
    )


def _policy(unit: str) -> str:
    expected = {
        "User": "eom-image",
        "Group": "eom-image",
        "SupplementaryGroups": "eom-gpu-lease",
        "Type": "oneshot",
        "RemainAfterExit": "yes",
        "NotifyAccess": "main",
        "FileDescriptorStoreMax": "1",
        "FileDescriptorStorePreserve": "yes",
        "CollectMode": "inactive",
        "Restart": "no",
        "KillMode": "control-group",
        "NoNewPrivileges": "yes",
        "PrivateNetwork": "yes",
        "PrivateDevices": "no",
        "DevicePolicy": "closed",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "show",
            unit,
            *("--property=" + field for field in (*expected, "DeviceAllow")),
        ),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    _require(
        result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
        "POLICY_UNAVAILABLE",
    )
    fields, devices = {}, []
    for line in result.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        _require(bool(separator), "POLICY_INVALID")
        if key == "DeviceAllow":
            devices.append(value)
        else:
            _require(key in expected and key not in fields, "POLICY_INVALID")
            fields[key] = value
    _require(
        fields == expected
        and len(devices) == 5
        and set(devices)
        == {
            "char-rtc r",
            "/dev/nvidia0 rw",
            "/dev/nvidiactl rw",
            "/dev/nvidia-uvm rw",
            "/dev/nvidia-uvm-tools rw",
        },
        "POLICY_INVALID",
    )
    return sha256_bytes(result.stdout)


def image_gpu_unit_arguments(raw: bytes, unit: str) -> tuple[str, ...]:
    text = raw.decode("utf-8", errors="strict")
    starts = [
        line.removeprefix("ExecStart=")
        for line in text.splitlines()
        if line.startswith("ExecStart=")
    ]
    _require(len(starts) == 1 and len(starts[0]) <= 8192, "ENTRYPOINT_INVALID")
    instance = unit.partition("@")[2].removesuffix(".service")
    command = starts[0].replace("%i", instance)
    _require(not any(char in command for char in ("%", "$", "`", "\x00")), "ENTRYPOINT_INVALID")
    arguments = tuple(shlex.split(command))
    role = image_gpu_unit_role(unit)
    prefix = Path(
        "/srv/eom/conda/envs/eom-image"
        if role == "PROVIDER"
        else "/srv/eom/conda/envs/eom-image-trainer"
    )
    _require(
        arguments[:5] == (str(prefix / "bin/python3.11"), "-I", "-B", str(_BOOTSTRAP), role)
        and len(arguments) <= 64,
        "ENTRYPOINT_INVALID",
    )
    locks = tuple(index for index, value in enumerate(arguments) if value == "--gpu-lock")
    _require(
        len(locks) == 1
        and locks[0] + 1 < len(arguments)
        and arguments[locks[0] + 1] == "/run/eom-gpu-lease/gpu0.lock",
        "ENTRYPOINT_INVALID",
    )
    return arguments


@dataclass(frozen=True, slots=True)
class ImageGpuUnitReadyObservation:
    unit_name: str
    template_sha256: str
    bootstrap_sha256: str
    effective_policy_sha256: str
    unit: CpuUnitObservation
    pid: int
    start_time_ticks: int
    worker_uid: int
    worker_gid: int
    lease_gid: int
    thread_ids: tuple[int, ...]
    device: CudaRuntimeDeviceCapture
    resources: ImageUnitGpuResources


@dataclass(frozen=True, slots=True)
class ImageGpuUnitTerminalObservation:
    ready: ImageGpuUnitReadyObservation
    terminal_unit: CpuUnitObservation
    original_outcome: Literal["SUCCEEDED", "FAILED"]
    terminated_at_utc: str


@dataclass(frozen=True, slots=True)
class ImageGpuUnitUnleasedTerminalObservation:
    unit_name: str
    template_sha256: str
    bootstrap_sha256: str
    effective_policy_sha256: str
    terminal_unit: CpuUnitObservation
    original_outcome: Literal["SUCCEEDED", "FAILED"]
    terminated_at_utc: str


def image_gpu_unit_descriptor_count(unit: str) -> int:
    """Actual fixed-unit store count only; never infer another unit's GPU ownership."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    image_gpu_unit_template(unit)
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", unit, "--property=NFileDescriptorStore", "--value"),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("IMAGE_GPU_UNIT_STORE_UNAVAILABLE") from None
    _require(
        result.returncode == 0
        and result.stdout in {b"0\n", b"1\n"}
        and len(result.stderr) <= 16384,
        "STORE_UNAVAILABLE",
    )
    return int(result.stdout)


def observe_unleased_image_gpu_unit_terminal(
    unit: str,
    *,
    template_sha256: str,
    bootstrap_sha256: str,
    expected_unit: CpuUnitObservation,
) -> ImageGpuUnitUnleasedTerminalObservation:
    """A cache/input/busy exit has no READY lease and must never fake one."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    template = image_gpu_unit_template(unit)
    _require(
        type(expected_unit) is CpuUnitObservation
        and re.fullmatch(r"[0-9a-f]{32}", expected_unit.invocation_id) is not None,
        "IDENTITY_INVALID",
    )
    outcome = image_gpu_unit_terminal_outcome(expected_unit)
    files = NumericalRuntimeFileSnapshots(0)
    raw = files.read(Path("/etc/systemd/system") / template, sha256=template_sha256, maximum=65536)
    image_gpu_unit_arguments(raw, unit)
    files.read(_BOOTSTRAP, sha256=bootstrap_sha256, maximum=128 * 1024)
    policy = _policy(unit)
    for _ in range(2):
        _require(
            inspect_cpu_unit(unit, template=template) == expected_unit
            and image_gpu_unit_descriptor_count(unit) == 0,
            "TERMINATION_UNCERTAIN",
        )
        try:
            members = root_owned_unit_processes(unit)
        except FileNotFoundError:
            _require(
                not (Path("/sys/fs/cgroup/system.slice") / unit).exists(), "TERMINATION_UNCERTAIN"
            )
            members = ()
        _require(members == (), "TERMINATION_UNCERTAIN")
    _require(_policy(unit) == policy, "POLICY_CHANGED")
    files.assert_unchanged()
    return ImageGpuUnitUnleasedTerminalObservation(
        unit,
        template_sha256,
        bootstrap_sha256,
        policy,
        expected_unit,
        outcome,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def image_gpu_unit_terminal_outcome(terminal: CpuUnitObservation) -> Literal["SUCCEEDED", "FAILED"]:
    """One original-outcome rule for terminal capture and read-only recovery."""
    _require(type(terminal) is CpuUnitObservation, "TERMINATION_UNCERTAIN")
    if terminal.succeeded:
        return "SUCCEEDED"
    if (
        terminal.main_pid == 0
        and terminal.status.active_state == "failed"
        and terminal.status.sub_state == "failed"
        and terminal.status.process_started
        and terminal.status.exec_main_code in {1, 2, 3}
        and terminal.status.result
        in {
            "exit-code",
            "signal",
            "core-dump",
            "timeout",
            "watchdog",
            "oom-kill",
            "resources",
            "protocol",
        }
        and terminal.exited_monotonic >= terminal.status.exec_main_started_monotonic
    ):
        return "FAILED"
    raise ValueError("IMAGE_GPU_UNIT_TERMINATION_UNCERTAIN")


def verify_image_gpu_unit_terminal(
    ready: ImageGpuUnitReadyObservation,
) -> ImageGpuUnitTerminalObservation:
    """Keep success/failure distinct; require actual ended workload and retained fence.

    This is read-only. A timeout, missing observation or changed identity is never
    permission to stop/reset a unit, clear PID1's store or mark a Job successful.
    """
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(type(ready) is ImageGpuUnitReadyObservation, "IDENTITY_INVALID")
    template = image_gpu_unit_template(ready.unit_name)
    files = NumericalRuntimeFileSnapshots(0)
    files.read(Path("/etc/systemd/system") / template, sha256=ready.template_sha256, maximum=65536)
    files.read(_BOOTSTRAP, sha256=ready.bootstrap_sha256, maximum=128 * 1024)
    user, group = pwd.getpwnam("eom-image"), grp.getgrnam("eom-image")
    _require(
        (user.pw_uid, user.pw_gid, group.gr_gid, grp.getgrnam("eom-gpu-lease").gr_gid)
        == (ready.worker_uid, ready.worker_gid, ready.worker_gid, ready.lease_gid),
        "ACCOUNT_CHANGED",
    )
    terminal = inspect_cpu_unit(ready.unit_name, template=template)
    _require(
        terminal.invocation_id == ready.unit.invocation_id
        and terminal.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic,
        "TERMINATION_UNCERTAIN",
    )
    outcome = image_gpu_unit_terminal_outcome(terminal)

    def ended() -> None:
        original = Path("/proc") / str(ready.pid)
        try:
            current_uid = original.lstat().st_uid
            current = read_live_runtime_os_file(
                original / "stat", maximum=65536, owner_uid=current_uid
            )
        except FileNotFoundError:
            pass
        else:
            # A PID number may be reused during recovery. Never confuse that new
            # process with the original PID+start identity or signal/kill it.
            _require(
                native_process_start_ticks(current, ready.pid) != ready.start_time_ticks,
                "TERMINATION_UNCERTAIN",
            )
        try:
            members = root_owned_unit_processes(ready.unit_name)
        except FileNotFoundError:
            _require(
                not (Path("/sys/fs/cgroup/system.slice") / ready.unit_name).exists(),
                "TERMINATION_UNCERTAIN",
            )
            members = ()
        _require(
            members == () and inspect_cpu_unit(ready.unit_name, template=template) == terminal,
            "TERMINATION_UNCERTAIN",
        )

    ended()
    observe_runtime_device(ready.device)
    observe_image_unit_gpu_retained_resources(ready.resources, unit=ready.unit_name)
    _require(observe_cuda_probe_gpu_clients(ready.device) == (), "GPU_CLEANUP_UNCERTAIN")
    observe_image_unit_gpu_retained_resources(ready.resources, unit=ready.unit_name)
    _require(_policy(ready.unit_name) == ready.effective_policy_sha256, "POLICY_CHANGED")
    ended()
    files.assert_unchanged()
    return ImageGpuUnitTerminalObservation(
        ready,
        terminal,
        outcome,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def observe_image_gpu_unit_ready(
    unit: str,
    *,
    template_sha256: str,
    bootstrap_sha256: str,
    device: CudaRuntimeDeviceCapture,
) -> ImageGpuUnitReadyObservation:
    """Capture actual per-unit readiness using root-installed pins, never worker authority.

    The caller still owns the full19-unit installation/migration fence, existing
    application admission, ACK and terminal cleanup. This value alone grants none.
    """
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    template = image_gpu_unit_template(unit)
    template_sha256 = TypeAdapter(Sha256).validate_python(template_sha256, strict=True)
    bootstrap_sha256 = TypeAdapter(Sha256).validate_python(bootstrap_sha256, strict=True)
    device = CudaRuntimeDeviceCapture.model_validate(device)
    files = NumericalRuntimeFileSnapshots(0)
    template_raw = files.read(
        Path("/etc/systemd/system") / template, sha256=template_sha256, maximum=65536
    )
    expected_arguments = image_gpu_unit_arguments(template_raw, unit)
    files.read(_BOOTSTRAP, sha256=bootstrap_sha256, maximum=128 * 1024)
    user, group = pwd.getpwnam("eom-image"), grp.getgrnam("eom-image")
    lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
    _require(
        user.pw_uid > 0
        and group.gr_gid > 0
        and user.pw_gid == group.gr_gid
        and lease_gid > 0
        and lease_gid != group.gr_gid,
        "ACCOUNT_INVALID",
    )
    before = inspect_cpu_unit(unit, template=template)
    _require(
        before.main_pid > 0
        and before.exited_monotonic == 0
        and before.status.active_state == "activating"
        and before.status.sub_state == "start"
        and before.status.process_started
        and re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is not None,
        "NOT_RUNNING",
    )
    policy = _policy(unit)
    pid = before.main_pid
    root = Path("/proc") / str(pid)

    def read(name: str, maximum: int = 131072) -> bytes:
        return read_live_runtime_os_file(root / name, maximum=maximum, owner_uid=user.pw_uid)

    start_ticks = native_process_start_ticks(read("stat"), pid)
    cgroup = "/system.slice/" + unit

    def process() -> None:
        _require(native_process_start_ticks(read("stat"), pid) == start_ticks, "PROCESS_CHANGED")
        _require(
            inspect_cpu_unit(unit, template=template) == before
            and read("cgroup") == ("0::" + cgroup + "\n").encode()
            and root_owned_unit_processes(unit) == (pid,),
            "PROCESS_CHANGED",
        )
        _status(
            read("status"), pid=pid, tid=pid, uid=user.pw_uid, gid=group.gr_gid, lease_gid=lease_gid
        )
        command = read("cmdline", 8192)
        _require(
            command.endswith(b"\x00")
            and tuple(part.decode("utf-8", errors="strict") for part in command[:-1].split(b"\x00"))
            == expected_arguments,
            "ENTRYPOINT_INVALID",
        )
        _require((root / "exe").readlink() == Path(expected_arguments[0]), "ENTRYPOINT_INVALID")

    def threads() -> tuple[int, ...]:
        values = []
        with os.scandir(root / "task") as entries:
            for count, entry in enumerate(entries, 1):
                _require(
                    count <= 512 and re.fullmatch(r"[1-9][0-9]{0,9}", entry.name) is not None,
                    "THREAD_IDENTITY_INVALID",
                )
                tid = int(entry.name)
                _require(tid <= 2147483647, "THREAD_IDENTITY_INVALID")
                _status(
                    read("task/" + entry.name + "/status"),
                    pid=pid,
                    tid=tid,
                    uid=user.pw_uid,
                    gid=group.gr_gid,
                    lease_gid=lease_gid,
                )
                values.append(tid)
        _require(pid in values and len(values) == len(set(values)), "THREAD_IDENTITY_INVALID")
        return tuple(sorted(values))

    process()
    tasks = threads()
    observe_runtime_device(device)
    _require(observe_cuda_probe_gpu_clients(device) == (), "GPU_NOT_IDLE")
    resources = observe_image_unit_gpu_resources(
        unit=unit,
        pid=pid,
        start_time_ticks=start_ticks,
        worker_uid=user.pw_uid,
        lease_gid=lease_gid,
    )
    _require(
        type(resources) is ImageUnitGpuResources
        and resources.shared_gpu_lease.holder_pid == pid
        and resources.shared_gpu_lease.holder_start_time_ticks == start_ticks
        and resources.shared_gpu_lease.lease_gid == lease_gid,
        "RESOURCE_OBSERVATION_INVALID",
    )
    process()
    _require(threads() == tasks and _policy(unit) == policy, "PROCESS_CHANGED")
    files.assert_unchanged()
    observe_runtime_device(device)
    return ImageGpuUnitReadyObservation(
        unit,
        template_sha256,
        bootstrap_sha256,
        policy,
        before,
        pid,
        start_ticks,
        user.pw_uid,
        group.gr_gid,
        lease_gid,
        tasks,
        device,
        resources,
    )
