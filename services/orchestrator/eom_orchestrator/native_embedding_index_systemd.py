"""Fixed native INDEX units with serialized capacity and exact-invocation readback."""

from __future__ import annotations

import fcntl
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingResult

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import (
    CpuUnitObservation,
    inspect_cpu_unit,
    require_fixed_cpu_unit_template,
    require_native_cpu_environment_file,
)
from eom_orchestrator.native_embedding_index_handoff import (
    OWNER_ROOT,
    RUNTIME_ROOT,
    NativeIndexHandoffError,
    PreparedNativeIndex,
    materialize_native_index_output,
    validate_native_index_execution_id,
)

PREPARE_TEMPLATE = "eom-embedding-native-index-prepare@.service"
INDEX_TEMPLATE = "eom-embedding-native-cpu-index@.service"
PREPARE_TEMPLATE_SHA256 = "d07b54290623ffef7997ac4a7bd0d836637da7e081fa0e95a13ac32dc794874c"
INDEX_TEMPLATE_SHA256 = "ad7180dd2c962082a069be79f2255b8d378050d61dc86d442d16ebceb8ee9380"
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}
_CGROUP_ROOT = Path("/sys/fs/cgroup/system.slice")


class NativeIndexLaunchError(ValueError):
    """BUSY and UNCERTAIN preserve ownership; neither permits another model execution."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def native_index_unit_names(execution_id: str) -> tuple[str, str]:
    identity = validate_native_index_execution_id(execution_id)
    return (
        PREPARE_TEMPLATE.replace("@.service", f"@{identity}.service"),
        INDEX_TEMPLATE.replace("@.service", f"@{identity}.service"),
    )


def _require_runtime_roots() -> None:
    """Reject missing namespace-denial roots before consuming a unit invocation.

    Root may still change the layout between this check and PID1. That remains
    an observed failed execution, never permission to reset/restart its handle.
    """
    owner = fixed_owner_identity()
    roots = (
        (RUNTIME_ROOT, owner.owner_gid, 0o750),
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
                raise NativeIndexLaunchError("NATIVE_INDEX_RUNTIME_LAYOUT_INVALID")
    except OSError:
        raise NativeIndexLaunchError("NATIVE_INDEX_RUNTIME_LAYOUT_INVALID") from None


@contextmanager
def _cpu_capacity() -> Iterator[None]:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeIndexLaunchError("NATIVE_INDEX_OWNER_REQUIRED")
    with protected_cpu_handoff_directory(
        OWNER_ROOT, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        descriptor = os.open(
            ".cpu-capacity.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
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
                raise NativeIndexLaunchError("NATIVE_INDEX_CAPACITY_INVALID")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NativeIndexLaunchError("NATIVE_INDEX_BUSY") from None
            yield
            after = os.stat(".cpu-capacity.lock", dir_fd=directory, follow_symlinks=False)
            if (after.st_dev, after.st_ino, after.st_nlink) != (value.st_dev, value.st_ino, 1):
                raise NativeIndexLaunchError("NATIVE_INDEX_CAPACITY_CHANGED")
        finally:
            os.close(descriptor)


def _require_no_running_index() -> None:
    # A crashed owner's flock is released by the kernel. Inspect surviving units
    # while holding the new flock before admitting a different execution.
    status = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-pager",
            "--no-legend",
            "list-units",
            "--state=running,activating,deactivating,reloading",
            "--plain",
            "eom-embedding-native-cpu-index@*.service",
        ),
        capture_output=True,
        check=False,
        timeout=15,
        env=_ENV,
    )
    if status.returncode != 0 or len(status.stdout) > 64 * 1024 or len(status.stderr) > 16 * 1024:
        raise NativeIndexLaunchError("NATIVE_INDEX_CAPACITY_UNAVAILABLE")
    for line in status.stdout.decode("ascii").splitlines():
        columns = line.split()
        if (
            len(columns) < 4
            or re.fullmatch(r"eom-embedding-native-cpu-index@[0-9a-f]{32}\.service", columns[0])
            is None
        ):
            raise NativeIndexLaunchError("NATIVE_INDEX_CAPACITY_UNAVAILABLE")
        raise NativeIndexLaunchError("NATIVE_INDEX_BUSY")
    # A main process may have exited with a child still alive. Kernel cgroups
    # are the remaining-process check; historical exited unit rows are not slots.
    for group in _CGROUP_ROOT.glob("eom-embedding-native-cpu-index@*.service"):
        _require_empty_unit_cgroup(group.name)


def _require_empty_unit_cgroup(unit: str) -> None:
    if (
        re.fullmatch(
            r"eom-embedding-native-(?:cpu-index|index-prepare)@[0-9a-f]{32}\.service", unit
        )
        is None
    ):
        raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
    descriptor: int | None = None
    member: int | None = None
    try:
        descriptor = os.open(
            _CGROUP_ROOT / unit, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        if os.fstat(descriptor).st_uid != 0:
            raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
        member = os.open(
            "cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
        )
        if os.fstat(member).st_uid != 0 or os.read(member, 4096):
            raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
    except FileNotFoundError:
        # A terminal unit's removed kernel cgroup has no surviving members.
        return
    finally:
        if member is not None:
            os.close(member)
        if descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class FixedNativeIndexLauncher:
    """Installed-runtime callback is supplied by actual composition, never request data."""

    cpu_environment_sha256: str
    owner_environment_sha256: str
    assert_runtime_current: Callable[[], None]

    def __post_init__(self) -> None:
        if not callable(self.assert_runtime_current) or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.cpu_environment_sha256, self.owner_environment_sha256)
        ):
            raise NativeIndexLaunchError("NATIVE_INDEX_CONFIGURATION_INVALID")

    def _installed(self) -> None:
        require_fixed_cpu_unit_template(PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256)
        require_fixed_cpu_unit_template(INDEX_TEMPLATE, INDEX_TEMPLATE_SHA256)
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-cpu.env"), self.cpu_environment_sha256
        )
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-owner.env"), self.owner_environment_sha256
        )
        _require_runtime_roots()
        self.assert_runtime_current()

    def _observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        prepare, index = native_index_unit_names(execution_id)
        return inspect_cpu_unit(prepare, template=PREPARE_TEMPLATE), inspect_cpu_unit(
            index, template=INDEX_TEMPLATE
        )

    def observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        """Protected exact-unit read only; no start, source grant or held capacity."""
        validate_native_index_execution_id(execution_id)
        self._installed()
        return self._observe(execution_id)

    def assert_current_runtime(self) -> None:
        """Readiness-only installed closure; no IAM write, capacity claim or unit start."""
        self._installed()

    def run(self, prepared: PreparedNativeIndex) -> IncrementalEmbeddingResult:
        prepared = PreparedNativeIndex(
            prepared.execution_id, prepared.association, prepared.request
        )
        try:
            with _cpu_capacity():
                self._installed()
                before = self._observe(prepared.execution_id)
                if all(row.succeeded for row in before):
                    # Exact same terminal execution: validate/copy its bytes, never start again.
                    for unit in native_index_unit_names(prepared.execution_id):
                        _require_empty_unit_cgroup(unit)
                    result = materialize_native_index_output(prepared)
                    if self._observe(prepared.execution_id) != before:
                        raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
                    return result
                if not all(row.fresh for row in before):
                    raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
                _require_no_running_index()
                _prepare, main = native_index_unit_names(prepared.execution_id)
                # Observe the same exact handle after a transport timeout.
                with suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(
                        ("/usr/bin/systemctl", "--no-ask-password", "start", main),
                        capture_output=True,
                        check=False,
                        timeout=210,
                        env=_ENV,
                    )
                after = self._observe(prepared.execution_id)
                if all(row.succeeded for row in after):
                    for unit in native_index_unit_names(prepared.execution_id):
                        _require_empty_unit_cgroup(unit)
                    result = materialize_native_index_output(prepared)
                    self._installed()
                    if self._observe(prepared.execution_id) != after:
                        raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
                    return result
                if after[1].failed or (after[0].failed and not after[1].status.process_started):
                    raise NativeIndexLaunchError("NATIVE_INDEX_KNOWN_FAILED")
                raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN")
        except NativeIndexLaunchError:
            raise
        except (
            CpuHandoffError,
            NativeIndexHandoffError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ):
            raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN") from None
