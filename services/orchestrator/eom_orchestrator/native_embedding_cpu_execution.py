"""Shared fixed INDEX/QUERY CPU capacity and exact-invocation lifecycle.

No source/claim authority, queue or numerical backend lives here. The two concrete
adapters supply only installed-runtime, observation and typed materialization calls.
"""

from __future__ import annotations

import fcntl
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation

type NativeCpuPurpose = Literal["INDEX", "QUERY", "PRIVATE_CHAT_QUERY"]
type NativeCpuObservations = tuple[CpuUnitObservation, CpuUnitObservation]

# Retain the existing lock inode/location across the owner-release transition.
CAPACITY_ROOT = Path("/var/lib/eom-workflow-runner/incremental-embeddings/index")
CGROUP_ROOT = Path("/sys/fs/cgroup/system.slice")
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}
_UNIT = re.compile(
    r"(?:eom-embedding-native-(?:cpu-(?:index|query|private-chat-query)|(?:index|query|private-chat-query)-prepare)"
    r"|eom-embedding-benchmark-(?:cpu|cuda))@[0-9a-f]{32}\.service\Z",
    re.ASCII,
)
_UNIT_GLOBS = (
    "eom-embedding-native-cpu-index@*.service",
    "eom-embedding-native-index-prepare@*.service",
    "eom-embedding-native-cpu-query@*.service",
    "eom-embedding-native-query-prepare@*.service",
    "eom-embedding-native-cpu-private-chat-query@*.service",
    "eom-embedding-native-private-chat-query-prepare@*.service",
    "eom-embedding-benchmark-cpu@*.service",
    "eom-embedding-benchmark-cuda@*.service",
)
_FIXED_RESOURCE_VALUES = MappingProxyType(
    {
        "device": "CPU",
        "threads": 4,
        "batch_size": 4,
        "memory_max_bytes": 6 * 1024**3,
        "gpu_vram_max_bytes": 0,
        "cpu_quota_percent": 400,
        "timeout_seconds": 180,
        "tasks_max": 64,
        "output_max_bytes": 64 * 1024**2,
        "maximum_active_launches": 1,
        "physical_gpu_lease": "NONE",
        "network": "DISABLED",
    }
)


class NativeCpuExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_fixed_native_cpu_resources(value: LocalEmbeddingResourceProfile) -> None:
    value = LocalEmbeddingResourceProfile.model_validate(raw_similarity_contract_value(value))
    if value.model_dump(mode="json", exclude={"resource_profile_sha256"}) != _FIXED_RESOURCE_VALUES:
        raise NativeCpuExecutionError("NATIVE_CPU_RESOURCE_PROFILE_INVALID")


def native_cpu_unit_names(purpose: NativeCpuPurpose, execution_id: str) -> tuple[str, str]:
    if (
        purpose not in {"INDEX", "QUERY", "PRIVATE_CHAT_QUERY"}
        or type(execution_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", execution_id, re.ASCII) is None
    ):
        raise NativeCpuExecutionError("NATIVE_CPU_EXECUTION_ID_INVALID")
    key = purpose.lower().replace("_", "-")
    return (
        f"eom-embedding-native-{key}-prepare@{execution_id}.service",
        f"eom-embedding-native-cpu-{key}@{execution_id}.service",
    )


def require_native_cpu_runtime_roots() -> None:
    owner = fixed_owner_identity()
    roots = (
        (Path("/run/eom-embedding-native-index"), owner.owner_gid, 0o750),
        (Path("/run/eom-embedding-native-query"), owner.owner_gid, 0o750),
        (Path("/run/eom-embedding-native-probe"), 0, 0o700),
    )
    try:
        for path, group, mode in roots:
            value = path.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != 0
                or value.st_gid != group
                or stat.S_IMODE(value.st_mode) != mode
            ):
                raise NativeCpuExecutionError("NATIVE_CPU_RUNTIME_LAYOUT_INVALID")
    except OSError:
        raise NativeCpuExecutionError("NATIVE_CPU_RUNTIME_LAYOUT_INVALID") from None


@contextmanager
def native_cpu_capacity() -> Iterator[None]:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeCpuExecutionError("NATIVE_CPU_OWNER_REQUIRED")
    with protected_cpu_handoff_directory(
        CAPACITY_ROOT, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            # QUERY intentionally cannot write INDEX storage. flock needs only
            # the existing inode, not a writable descriptor or writable mount.
            descriptor = os.open(".cpu-capacity.lock", flags, dir_fd=directory)
        except FileNotFoundError:
            # Preserve cold initialization for the write-capable INDEX owner;
            # absent storage on a read-only mount still fails closed.
            descriptor = os.open(".cpu-capacity.lock", flags | os.O_CREAT, 0o600, dir_fd=directory)
        try:
            value = os.fstat(descriptor)
            named = os.stat(".cpu-capacity.lock", dir_fd=directory, follow_symlinks=False)
            if (
                not stat.S_ISREG(value.st_mode)
                or value.st_nlink != 1
                or value.st_uid != owner.owner_uid
                or value.st_gid != owner.owner_gid
                or stat.S_IMODE(value.st_mode) != 0o600
                or value.st_size != 0
                or (value.st_dev, value.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise NativeCpuExecutionError("NATIVE_CPU_CAPACITY_INVALID")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NativeCpuExecutionError("NATIVE_CPU_BUSY") from None
            yield
            after = os.stat(".cpu-capacity.lock", dir_fd=directory, follow_symlinks=False)
            if (after.st_dev, after.st_ino, after.st_nlink) != (value.st_dev, value.st_ino, 1):
                raise NativeCpuExecutionError("NATIVE_CPU_CAPACITY_CHANGED")
        finally:
            os.close(descriptor)


def _cgroup_parents(prefix: str) -> tuple[Path, Path]:
    default_slice = "system-" + prefix.replace("-", r"\x2d") + ".slice"
    return CGROUP_ROOT, CGROUP_ROOT / default_slice


@contextmanager
def _root_cgroup_directory(path: Path) -> Iterator[int]:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(descriptor).st_uid != 0:
            raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
        yield descriptor
    finally:
        os.close(descriptor)


def require_empty_native_cpu_cgroup(unit: str) -> None:
    if _UNIT.fullmatch(unit) is None:
        raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
    # Existing INDEX prepare is in its per-template slice. Numerical units
    # explicitly use system.slice. Frozen template bytes need not be rewritten.
    for index, parent in enumerate(_cgroup_parents(unit.partition("@")[0])):
        try:
            with _root_cgroup_directory(parent) as directory:
                _require_empty_unit_in_parent(directory, unit)
        except FileNotFoundError:
            if index == 0:
                raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN") from None
            # Optional default template slice may never have been created.


def _require_empty_unit_in_parent(parent: int, unit: str) -> None:
    try:
        descriptor = os.open(
            unit, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
        )
    except FileNotFoundError:
        return  # The unit cgroup itself is absent, not an unobserved membership file.
    member: int | None = None
    try:
        if os.fstat(descriptor).st_uid != 0:
            raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
        try:
            member = os.open(
                "cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
            )
        except FileNotFoundError:
            raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN") from None
        if os.fstat(member).st_uid != 0 or os.read(member, 4096):
            raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
    finally:
        if member is not None:
            os.close(member)
        os.close(descriptor)


def require_no_active_native_cpu_execution() -> None:
    """A crashed controller releases flock, not necessarily its prepare/worker cgroup."""
    status = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-pager",
            "--no-legend",
            "list-units",
            "--state=running,activating,deactivating,reloading",
            "--plain",
            *_UNIT_GLOBS,
        ),
        capture_output=True,
        check=False,
        timeout=15,
        env=_ENV,
    )
    if status.returncode != 0 or len(status.stdout) > 64 * 1024 or len(status.stderr) > 16 * 1024:
        raise NativeCpuExecutionError("NATIVE_CPU_CAPACITY_UNAVAILABLE")
    try:
        lines = status.stdout.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise NativeCpuExecutionError("NATIVE_CPU_CAPACITY_UNAVAILABLE") from None
    for line in lines:
        columns = line.split()
        if len(columns) < 4 or _UNIT.fullmatch(columns[0]) is None:
            raise NativeCpuExecutionError("NATIVE_CPU_CAPACITY_UNAVAILABLE")
        raise NativeCpuExecutionError("NATIVE_CPU_BUSY")
    try:
        with _root_cgroup_directory(CGROUP_ROOT):
            pass
    except FileNotFoundError:
        raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN") from None
    units: set[str] = set()
    for pattern in _UNIT_GLOBS:
        prefix = pattern.partition("@")[0]
        for parent in _cgroup_parents(prefix):
            units.update(group.name for group in parent.glob(pattern))
    for unit in sorted(units):
        require_empty_native_cpu_cgroup(unit)


def run_fixed_native_cpu[Result](
    *,
    purpose: NativeCpuPurpose,
    execution_id: str,
    assert_runtime: Callable[[], None],
    observe: Callable[[str], NativeCpuObservations],
    materialize: Callable[[], Result],
    claim_start: Callable[[], None],
) -> Result:
    """One fixed launch or exact terminal readback; timeout never permits a restart."""
    units = native_cpu_unit_names(purpose, execution_id)
    try:
        with native_cpu_capacity():
            assert_runtime()
            before = observe(execution_id)
            if all(row.succeeded for row in before):
                for unit in units:
                    require_empty_native_cpu_cgroup(unit)
                result = materialize()
                if observe(execution_id) != before:
                    raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
                return result
            if before[1].failed or (before[0].failed and not before[1].status.process_started):
                for unit in units:
                    require_empty_native_cpu_cgroup(unit)
                assert_runtime()
                if observe(execution_id) != before:
                    raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
                raise NativeCpuExecutionError("NATIVE_CPU_KNOWN_FAILED")
            if not all(row.fresh for row in before):
                raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
            require_no_active_native_cpu_execution()
            # Fresh systemd metadata may follow a reboot, not just an unused handle.
            # A consumed durable owner marker must never authorize a second start.
            claim_start()
            with suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ("/usr/bin/systemctl", "--no-ask-password", "start", units[1]),
                    capture_output=True,
                    check=False,
                    timeout=210,
                    env=_ENV,
                )
            after = observe(execution_id)
            if all(row.succeeded for row in after):
                for unit in units:
                    require_empty_native_cpu_cgroup(unit)
                result = materialize()
                assert_runtime()
                if observe(execution_id) != after:
                    raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
                return result
            if after[1].failed or (after[0].failed and not after[1].status.process_started):
                for unit in units:
                    require_empty_native_cpu_cgroup(unit)
                assert_runtime()
                if observe(execution_id) != after:
                    raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
                raise NativeCpuExecutionError("NATIVE_CPU_KNOWN_FAILED")
            raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")
    except NativeCpuExecutionError:
        raise
    except (CpuHandoffError, OSError, subprocess.SubprocessError):
        raise NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN") from None
