"""Numerical-runtime maintenance observations; not Orchestrator dispatch or a launcher."""

from __future__ import annotations

import grp
import os
import pwd
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_native_cpu_probe import ExecutionId, NativeCpuProbeResult
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import (
    UnitProcessObservationError,
    root_owned_unit_processes,
)
from pydantic import TypeAdapter

from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_host_closure import ProtectedEmbeddingHostClosure
from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory
from eom_catalog_service.embedding_runtime_process_identity import native_process_start_ticks

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure

CPU_PROBE_TEMPLATE = "eom-embedding-native-cpu-probe@.service"
CPU_PROBE_TEMPLATE_SHA256 = (
    "sha256:dcfa3596b92297ada1330c4393fb6a305c9703b3a1678476125f6f7eb96ae34f"
)
_PREFIX = Path("/opt/eom/conda/envs/eom-embedding-index-cpu")
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_KERNEL_CODE = {"[vdso]", "[vsyscall]"}


def require_native_cpu_probe_unit() -> tuple[int, int]:
    """Exact installed template and account only; caller still owns pre-exec prefix admission."""
    files = NumericalRuntimeFileSnapshots(0)
    files.read(
        Path("/etc/systemd/system") / CPU_PROBE_TEMPLATE,
        sha256=CPU_PROBE_TEMPLATE_SHA256,
        maximum=64 * 1024,
    )
    user = pwd.getpwnam("eom-embedding-index-cpu")
    group = grp.getgrnam("eom-embedding-index-cpu")
    if (
        user.pw_uid <= 0
        or group.gr_gid <= 0
        or user.pw_gid != group.gr_gid
        or set(os.getgrouplist(user.pw_name, user.pw_gid)) != {group.gr_gid}
    ):
        raise ValueError("NATIVE_CPU_PROBE_ACCOUNT_INVALID")
    files.assert_unchanged()
    return user.pw_uid, user.pw_gid


@dataclass(frozen=True, slots=True)
class NativeExecutableMapping:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class NativeCpuProbeProcessObservation:
    execution_id: str
    invocation_id: str
    pid: int
    start_time_ticks: int
    cgroup: str
    loaded_members_sha256: str
    executable_members: tuple[NativeExecutableMapping, ...]


def parse_native_executable_mappings(raw: bytes) -> tuple[NativeExecutableMapping, ...]:
    """Bounded maps projection; addresses/ASLR are not numerical runtime identity."""
    if type(raw) is not bytes or not 0 < len(raw) <= 2 * 1024**2:
        raise ValueError("NATIVE_CPU_PROBE_MAPS_INVALID")
    members: dict[Path, NativeExecutableMapping] = {}
    last_end = 0
    for line in raw.decode("utf-8", errors="strict").splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) not in (5, 6):
            raise ValueError("NATIVE_CPU_PROBE_MAPS_INVALID")
        address, mode, offset, device, inode = parts[:5]
        if (
            re.fullmatch(r"[0-9a-f]+-[0-9a-f]+", address) is None
            or re.fullmatch(r"[r-][w-][x-][ps]", mode) is None
            or re.fullmatch(r"[0-9a-f]+", offset) is None
            or re.fullmatch(r"[0-9a-f]+:[0-9a-f]+", device) is None
            or re.fullmatch(r"[0-9]+", inode) is None
        ):
            raise ValueError("NATIVE_CPU_PROBE_MAPS_INVALID")
        start, end = (int(value, 16) for value in address.split("-"))
        if not last_end <= start < end <= 2**64:
            raise ValueError("NATIVE_CPU_PROBE_MAPS_INVALID")
        last_end = end
        if "x" not in mode:
            continue
        name = parts[5] if len(parts) == 6 else ""
        major, minor = (int(value, 16) for value in device.split(":"))
        number = int(inode)
        if "w" in mode or mode[-1] != "p":
            raise ValueError("NATIVE_CPU_PROBE_EXECUTABLE_MAPPING_UNSAFE")
        if name in _KERNEL_CODE and (major, minor, number, int(offset, 16)) == (0, 0, 0, 0):
            continue
        path = Path(name)
        if (
            not name.startswith("/")
            or str(path) != name
            or any(part in (".", "..") for part in name.split("/"))
            or "\\" in name
            or any(ord(char) < 32 for char in name)
            or name.endswith(" (deleted)")
            or not 0 < number <= 2**64 - 1
            or not 0 <= major <= 2**32 - 1
            or not 0 <= minor <= 2**32 - 1
        ):
            raise ValueError("NATIVE_CPU_PROBE_EXECUTABLE_MAPPING_UNSAFE")
        member = NativeExecutableMapping(path, os.makedev(major, minor), number)
        if path in members and members[path] != member:
            raise ValueError("NATIVE_CPU_PROBE_MAPS_CHANGED")
        members[path] = member
        if len(members) > 1024:
            raise ValueError("NATIVE_CPU_PROBE_MAPS_INVALID")
    if not members:
        raise ValueError("NATIVE_CPU_PROBE_MAPS_EMPTY")
    return tuple(members[path] for path in sorted(members))


def validate_native_executable_mappings(
    raw: bytes, *, inventory: PrefixRuntimeInventory, host: ProtectedEmbeddingHostClosure
) -> tuple[NativeExecutableMapping, ...]:
    """Reuse the existing byte-audited prefix/host ledgers; do not parse ELF or hash again."""
    return _validate_executable_mappings(raw, inventory=inventory, host=host, prefix=_PREFIX)


def validate_native_cuda_executable_mappings(
    raw: bytes, *, inventory: PrefixRuntimeInventory, host: ProtectedCudaEmbeddingHostClosure
) -> tuple[NativeExecutableMapping, ...]:
    """Same map/ledger algorithm, exact CUDA prefix and its separately captured host only."""
    try:
        return _validate_executable_mappings(
            raw,
            inventory=inventory,
            host=host,
            prefix=Path("/opt/eom/conda/envs/eom-embedding-cuda"),
        )
    except ValueError:
        raise ValueError("NATIVE_CUDA_PROBE_MAPS_INVALID") from None


def _validate_executable_mappings(
    raw: bytes,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedEmbeddingHostClosure | ProtectedCudaEmbeddingHostClosure,
    prefix: Path,
) -> tuple[NativeExecutableMapping, ...]:
    if type(inventory) is not PrefixRuntimeInventory or inventory.prefix != prefix:
        raise ValueError("NATIVE_CPU_PROBE_PREFIX_INVALID")
    inventory.assert_unchanged()
    host.assert_current()
    members = parse_native_executable_mappings(raw)
    regular = {
        inventory.prefix / entry.relative_member: entry
        for entry in inventory.entries
        if stat.S_ISREG(entry.epoch[4])
    }
    for member in members:
        if member.path.is_relative_to(inventory.prefix):
            entry = regular.get(member.path)
            if entry is None or entry.epoch[:2] != (member.device, member.inode):
                raise ValueError("NATIVE_CPU_PROBE_PREFIX_MAPPING_INVALID")
        else:
            host.assert_mapped_file(member.path, device=member.device, inode=member.inode)
    if inventory.prefix / "bin/python3.12" not in {member.path for member in members}:
        raise ValueError("NATIVE_CPU_PROBE_INTERPRETER_MAPPING_MISSING")
    inventory.assert_unchanged()
    host.assert_current()
    return members


def native_probe_start_ticks(raw: bytes, pid: int) -> int:
    """Linux proc stat's comm may contain spaces or parentheses; split at its final boundary."""
    try:
        return native_process_start_ticks(raw, pid)
    except ValueError:
        raise ValueError("NATIVE_CPU_PROBE_PROCESS_INVALID") from None


def _unit(execution_id: str) -> tuple[str, str]:
    identity: str = TypeAdapter(ExecutionId).validate_python(execution_id)
    name = CPU_PROBE_TEMPLATE.replace("@.service", f"@{identity}.service")
    return name, f"/system.slice/{name}"


def native_probe_cgroup_members(cgroup: str) -> tuple[int, ...]:
    if (
        re.fullmatch(
            r"/system\.slice/eom-embedding-native-(?:cpu|cuda)-probe@[0-9a-f]{32}\.service", cgroup
        )
        is None
    ):
        raise ValueError("NATIVE_CPU_PROBE_CGROUP_INVALID")
    try:
        return root_owned_unit_processes(cgroup.removeprefix("/system.slice/"))
    except UnitProcessObservationError as error:
        label = "NESTED_CGROUP" if error.code == "NESTED_CGROUP" else "CGROUP_INVALID"
        raise ValueError("NATIVE_CPU_PROBE_" + label) from error


def _cgroup_members(cgroup: str) -> tuple[int, ...]:
    return native_probe_cgroup_members(cgroup)


def _require_root() -> None:
    if os.getresuid() != (0, 0, 0):
        raise ValueError("NATIVE_CPU_PROBE_OWNER_REQUIRED")


def observe_native_cpu_probe_process(
    report: NativeCpuProbeResult,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedEmbeddingHostClosure,
) -> NativeCpuProbeProcessObservation:
    """Read live identity/maps on both sides of validation, before the caller acknowledges."""
    _require_root()
    report = NativeCpuProbeResult.model_validate(report)
    if (report.worker_uid, report.worker_gid) != require_native_cpu_probe_unit():
        raise ValueError("NATIVE_CPU_PROBE_ACCOUNT_INVALID")
    unit, cgroup = _unit(report.execution_id)
    before = inspect_cpu_unit(unit, template=CPU_PROBE_TEMPLATE)
    if (
        before.main_pid != report.pid
        or re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is None
        or before.status.active_state != "activating"
        or before.status.sub_state != "start"
        or not before.status.process_started
        or before.exited_monotonic != 0
    ):
        raise ValueError("NATIVE_CPU_PROBE_UNIT_NOT_RUNNING")
    process = Path("/proc") / str(report.pid)

    def read(name: str, maximum: int = 64 * 1024) -> bytes:
        return read_live_runtime_os_file(
            process / name, maximum=maximum, owner_uid=report.worker_uid
        )

    start = native_probe_start_ticks(read("stat"), report.pid)
    if read("cgroup") != f"0::{cgroup}\n".encode() or _cgroup_members(cgroup) != (report.pid,):
        raise ValueError("NATIVE_CPU_PROBE_CGROUP_MISMATCH")
    maps = read("maps", 2 * 1024**2)
    members = validate_native_executable_mappings(maps, inventory=inventory, host=host)
    if (
        native_probe_start_ticks(read("stat"), report.pid) != start
        or parse_native_executable_mappings(read("maps", 2 * 1024**2)) != members
        or read("cgroup") != f"0::{cgroup}\n".encode()
        or _cgroup_members(cgroup) != (report.pid,)
        or inspect_cpu_unit(unit, template=CPU_PROBE_TEMPLATE) != before
    ):
        raise ValueError("NATIVE_CPU_PROBE_PROCESS_CHANGED")
    digest = sha256_bytes(
        canonical_json_bytes(
            [
                {"path": str(member.path), "device": member.device, "inode": member.inode}
                for member in members
            ]
        )
    )
    return NativeCpuProbeProcessObservation(
        report.execution_id, before.invocation_id, report.pid, start, cgroup, digest, members
    )


def acknowledge_native_cpu_probe(
    observed: NativeCpuProbeProcessObservation,
    report: NativeCpuProbeResult,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedEmbeddingHostClosure,
) -> None:
    """Only the exact current fixed unit is signalled; this is not terminal acceptance."""
    if observe_native_cpu_probe_process(report, inventory=inventory, host=host) != observed:
        raise ValueError("NATIVE_CPU_PROBE_PROCESS_CHANGED")
    unit, _ = _unit(observed.execution_id)
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "kill",
            "--kill-whom=main",
            "--signal=SIGUSR1",
            unit,
        ),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    if result.returncode != 0:
        raise ValueError("NATIVE_CPU_PROBE_ACK_UNCERTAIN")


def verify_native_cpu_probe_terminal(
    observed: NativeCpuProbeProcessObservation,
) -> CpuUnitObservation:
    """Called after the owner awaited the original unit; never resets/restarts failed history."""
    _require_root()
    require_native_cpu_probe_unit()
    unit, cgroup = _unit(observed.execution_id)
    terminal = inspect_cpu_unit(unit, template=CPU_PROBE_TEMPLATE)
    if (
        not terminal.succeeded
        or terminal.invocation_id != observed.invocation_id
        or cgroup != observed.cgroup
    ):
        raise ValueError("NATIVE_CPU_PROBE_TERMINATION_UNCERTAIN")
    try:
        members = _cgroup_members(cgroup)
    except FileNotFoundError:
        # systemd can remove an empty cgroup after the known invocation exits.
        if (_CGROUP_ROOT / cgroup.removeprefix("/")).exists():
            raise ValueError("NATIVE_CPU_PROBE_TERMINATION_UNCERTAIN") from None
        members = ()
    if members or inspect_cpu_unit(unit, template=CPU_PROBE_TEMPLATE) != terminal:
        raise ValueError("NATIVE_CPU_PROBE_TERMINATION_UNCERTAIN")
    return terminal
