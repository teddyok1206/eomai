"""Fixed prepare/main units implement the removable local CPU execution port."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from eom_orchestrator.inference_transfer_cpu_handoff import (
    OWNER_ROOT,
    CpuHandoffError,
    fixed_owner_identity,
    materialize_cpu_output,
    validate_cpu_execution_id,
)
from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunError,
    LocalExperimentInput,
)
from eom_orchestrator.worker_systemd import FixedUnitStatus, parse_unit_status

SYSTEMCTL = "/usr/bin/systemctl"
UNIT_ROOT = Path("/etc/systemd/system")
CPU_PYTHON = Path("/opt/eom/conda/envs/eom-embedding-experiment/bin/python")
PREPARE_PYTHON = CPU_PYTHON
CPU_TIMEOUT_SECONDS = 1800
# The measured 18-text BGE pilot projects roughly 64 minutes for 520 x 3 views;
# this bounded ceiling accommodates that projection without changing CPU, memory or retry policy.
BGE_CPU_TIMEOUT_SECONDS = 5400
CPU_CLIENT_GUARD_SECONDS = 30
PREPARE_TEMPLATE = "eom-embedding-experiment-prepare@.service"
CPU_TEMPLATE = "eom-embedding-experiment@.service"
PREPARE_TEMPLATE_SHA256 = "432f8d2cd0a9997f01edec6c559217c3a2bb5956a3341bde76d420722b7c9a4b"
CPU_TEMPLATE_SHA256 = "1097b66b9ac385e0f9b6ae28e2c45b33ca6fb497532a6e80245fb24c110ff832"
BGE_CPU_TEMPLATE = "eom-embedding-experiment-bge@.service"
BGE_CPU_TEMPLATE_SHA256 = "d54b75b04619490b095f529086b3c2169c87901016871152df52cab5f4183454"
_ROOT_UID = 0
_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
    "ExecMainStartTimestampMonotonic",
    "ExecMainExitTimestampMonotonic",
    "NeedDaemonReload",
    "MainPID",
    "InvocationID",
    "FragmentPath",
    "DropInPaths",
)


class CpuResourceProfile(StrEnum):
    E5 = "E5"
    BGE = "BGE"


@dataclass(frozen=True, slots=True)
class CpuResourceLimits:
    template: str
    template_sha256: str
    memory_max_bytes: int
    timeout_seconds: int


# Two reviewed real resource cases, not a runtime registry or a caller-supplied unit override.
_RESOURCE_LIMITS = MappingProxyType(
    {
        CpuResourceProfile.E5: CpuResourceLimits(
            CPU_TEMPLATE, CPU_TEMPLATE_SHA256, 2 * 1024**3, CPU_TIMEOUT_SECONDS
        ),
        CpuResourceProfile.BGE: CpuResourceLimits(
            BGE_CPU_TEMPLATE, BGE_CPU_TEMPLATE_SHA256, 6 * 1024**3, BGE_CPU_TIMEOUT_SECONDS
        ),
    }
)


def cpu_resource_limits(profile: CpuResourceProfile = CpuResourceProfile.E5) -> CpuResourceLimits:
    if not isinstance(profile, CpuResourceProfile):
        raise ValueError("INFERENCE_CPU_RESOURCE_PROFILE_INVALID")
    return _RESOURCE_LIMITS[profile]


@dataclass(frozen=True, slots=True)
class CpuUnitObservation:
    status: FixedUnitStatus
    main_pid: int
    exited_monotonic: int
    invocation_id: str
    fragment_path: str
    drop_in_paths: str

    @property
    def fresh(self) -> bool:
        return (
            self.status.active_state == "inactive"
            and self.status.sub_state == "dead"
            and self.status.result == "success"
            and self.status.exec_main_code == 0
            and self.status.exec_main_status == 0
            and not self.status.process_started
            and self.main_pid == 0
            and self.exited_monotonic == 0
            and not self.invocation_id
        )

    @property
    def succeeded(self) -> bool:
        # RemainAfterExit intentionally remains active; no process may still be running.
        return (
            self.status.active_state == "active"
            and self.status.sub_state == "exited"
            and self.main_pid == 0
            and self.status.result == "success"
            and self.status.exec_main_code == 1
            and self.status.exec_main_status == 0
            and self.status.exec_main_started_monotonic > 0
            and self.exited_monotonic >= self.status.exec_main_started_monotonic
            and re.fullmatch(r"[0-9a-f]{32}", self.invocation_id) is not None
        )

    @property
    def failed(self) -> bool:
        return (
            self.status.active_state == "failed"
            and self.status.sub_state == "failed"
            and self.main_pid == 0
            and self.status.result not in {"", "success", "timeout"}
            and self.status.exec_main_code > 0
            and self.status.exec_main_started_monotonic > 0
            and self.exited_monotonic >= self.status.exec_main_started_monotonic
            and re.fullmatch(r"[0-9a-f]{32}", self.invocation_id) is not None
        )


def cpu_unit_names(
    execution_id: str, *, profile: CpuResourceProfile = CpuResourceProfile.E5
) -> tuple[str, str]:
    identity = validate_cpu_execution_id(execution_id)
    limits = cpu_resource_limits(profile)
    return (
        f"eom-embedding-experiment-prepare@{identity}.service",
        limits.template.replace("@.service", f"@{identity}.service"),
    )


def _root_path(path: Path, *, allow_final_symlink: bool = False) -> Path:
    for member in (path, *path.parents):
        value = member.lstat()
        if (
            value.st_uid != _ROOT_UID
            or (stat.S_ISLNK(value.st_mode) and not (member == path and allow_final_symlink))
            or (not stat.S_ISLNK(value.st_mode) and value.st_mode & 0o022)
        ):
            raise ValueError("INFERENCE_CPU_INSTALLED_PATH_INVALID")
    resolved = path.resolve(strict=True)
    if resolved != path:
        _root_path(resolved)
    return resolved


def _require_template(name: str, expected_sha256: str) -> None:
    path = _root_path(UNIT_ROOT / name)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        initial = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial.st_mode)
            or initial.st_uid != _ROOT_UID
            or initial.st_mode & 0o022
            or initial.st_nlink != 1
            or not 0 < initial.st_size <= 128 * 1024
        ):
            raise ValueError("INFERENCE_CPU_TEMPLATE_INVALID")
        payload = os.read(descriptor, initial.st_size + 1)
        final = os.fstat(descriptor)
        named = path.lstat()
        if (
            _template_epoch(initial) != _template_epoch(final)
            or _template_epoch(final) != _template_epoch(named)
            or len(payload) != initial.st_size
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise ValueError("INFERENCE_CPU_TEMPLATE_INVALID")
    finally:
        os.close(descriptor)


def _template_epoch(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def require_cpu_runtime(*, profile: CpuResourceProfile = CpuResourceProfile.E5) -> None:
    """Installed fixed files only; absence never falls back to a repo/ambient interpreter."""
    limits = cpu_resource_limits(profile)
    _require_template(PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256)
    _require_template(limits.template, limits.template_sha256)
    for path in (PREPARE_PYTHON, CPU_PYTHON):
        value = _root_path(path, allow_final_symlink=True).stat()
        if not stat.S_ISREG(value.st_mode) or not value.st_mode & 0o111:
            raise ValueError("INFERENCE_CPU_INTERPRETER_INVALID")


def inspect_cpu_unit(unit_name: str, *, template: str) -> CpuUnitObservation:
    result = subprocess.run(
        (
            SYSTEMCTL,
            "--no-pager",
            "show",
            unit_name,
            *(f"--property={name}" for name in _PROPERTIES),
        ),
        capture_output=True,
        check=False,
        timeout=15,
        env=_ENVIRONMENT,
    )
    if result.returncode != 0 or len(result.stdout) > 16 * 1024 or len(result.stderr) > 16 * 1024:
        raise ValueError("INFERENCE_CPU_STATUS_UNAVAILABLE")
    output = result.stdout.decode("utf-8", errors="strict")
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in values or key not in _PROPERTIES:
            raise ValueError("INFERENCE_CPU_STATUS_INVALID")
        values[key] = value
    if set(values) != set(_PROPERTIES):
        raise ValueError("INFERENCE_CPU_STATUS_INVALID")
    status = parse_unit_status(output)
    observation = CpuUnitObservation(
        status,
        int(values["MainPID"]),
        int(values["ExecMainExitTimestampMonotonic"] or "0"),
        values["InvocationID"],
        values["FragmentPath"],
        values["DropInPaths"],
    )
    if (
        status.load_state != "loaded"
        or status.need_daemon_reload
        or values["NeedDaemonReload"] != "no"
        or observation.fragment_path != str(UNIT_ROOT / template)
        or observation.drop_in_paths
        or min(
            observation.main_pid, observation.exited_monotonic, status.exec_main_started_monotonic
        )
        < 0
    ):
        raise ValueError("INFERENCE_CPU_STATUS_INVALID")
    return observation


@dataclass(frozen=True, slots=True)
class FixedCpuExperimentLauncher:
    """No submission retry: a return requires both exact fixed units to have terminated."""

    profile: CpuResourceProfile = CpuResourceProfile.E5

    def __post_init__(self) -> None:
        cpu_resource_limits(self.profile)

    def run(self, prepared: LocalExperimentInput) -> None:
        try:
            limits = cpu_resource_limits(self.profile)
            owner = fixed_owner_identity()
            if (
                os.geteuid() != owner.owner_uid
                or prepared.workspace != OWNER_ROOT / prepared.execution_id
            ):
                raise ValueError("INFERENCE_CPU_OWNER_IDENTITY_INVALID")
            prepare_unit, main_unit = cpu_unit_names(prepared.execution_id, profile=self.profile)
            require_cpu_runtime(profile=self.profile)
        except (CpuHandoffError, OSError, ValueError, KeyError) as exc:
            raise CpuExperimentRunError("KNOWN_FAILED") from exc
        try:
            before = (
                inspect_cpu_unit(prepare_unit, template=PREPARE_TEMPLATE),
                inspect_cpu_unit(main_unit, template=limits.template),
            )
            if any(not value.fresh for value in before):
                raise CpuExperimentRunError("UNCERTAIN")
            # --wait waits for deactivation, which RemainAfterExit intentionally prevents.
            # Normal start waits for completion of both oneshot start jobs instead.
            started = subprocess.run(
                (SYSTEMCTL, "--no-ask-password", "start", main_unit),
                capture_output=True,
                check=False,
                timeout=limits.timeout_seconds + CPU_CLIENT_GUARD_SECONDS,
                env=_ENVIRONMENT,
            )
            after = (
                inspect_cpu_unit(prepare_unit, template=PREPARE_TEMPLATE),
                inspect_cpu_unit(main_unit, template=limits.template),
            )
            if all(value.succeeded for value in after):
                materialize_cpu_output(prepared)
                final = (
                    inspect_cpu_unit(prepare_unit, template=PREPARE_TEMPLATE),
                    inspect_cpu_unit(main_unit, template=limits.template),
                )
                if final != after:
                    raise CpuExperimentRunError("UNCERTAIN")
                return
            if after[1].failed or (after[0].failed and not after[1].status.process_started):
                raise CpuExperimentRunError("KNOWN_FAILED")
            # Start return code alone cannot prove whether the model process ran.
            _ = started.returncode
            raise CpuExperimentRunError("UNCERTAIN")
        except CpuExperimentRunError:
            raise
        except (OSError, ValueError, CpuHandoffError, subprocess.SubprocessError) as exc:
            raise CpuExperimentRunError("UNCERTAIN") from exc
