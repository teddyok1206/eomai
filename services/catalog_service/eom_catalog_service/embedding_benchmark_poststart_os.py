"""Read-only original CPU failure/retirement and current PID1 facts; no execution authority."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_budget1200_retry_failure import (
    BenchmarkBudget1200RetryControllerPin,
)
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import BenchmarkFailedControllerPin
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkExecutionPolicy,
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.models import UtcDatetime
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.native_embedding_cpu_execution import require_empty_native_cpu_cgroup
from pydantic import TypeAdapter

from eom_catalog_service.embedding_benchmark_cpu_driver import RootBenchmarkCpuRetirement
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_LIFETIME_ROOT
from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
_BOOT = Path("/proc/sys/kernel/random/boot_id")
_ROOT_UID = 0
_ROOT_GID = 0
_COMMON = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "InvocationID",
    "FragmentPath",
    "DropInPaths",
    "NeedDaemonReload",
    "Job",
    "ControlGroup",
    "ControlPID",
)
_SERVICE = (
    "MainPID",
    "NFileDescriptorStore",
    "Restart",
    "NRestarts",
    "Result",
    "ExecMainStartTimestampMonotonic",
    "ExecMainExitTimestampMonotonic",
    "ExecMainStatus",
)
_CONTROLLER = ("ExecStart",)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("BENCHMARK_POSTSTART_MACHINE_UNAVAILABLE")


def _no_acl(paths: tuple[Path, ...]) -> None:
    for path in paths:
        _require(
            not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                os.listxattr(path, follow_symlinks=False)
            )
        )


def _unit(name: str, properties: tuple[str, ...]) -> dict[str, str]:
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", name, *("--property=" + key for key in properties)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
        _require(result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= 16384)
        values: dict[str, str] = {}
        for line in result.stdout.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            _require(bool(separator) and key in properties and key not in values)
            values[key] = value
        _require(set(values) == set(properties))
        return values
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ValueError("BENCHMARK_POSTSTART_MACHINE_UNAVAILABLE") from None


def _dead(value: dict[str, str], *, name: str, fragment: str, controller: bool) -> None:
    _require(
        value["Id"] == name
        and value["LoadState"] == "loaded"
        and value["ActiveState"] == ("failed" if controller else "inactive")
        and value["SubState"] == ("failed" if controller else "dead")
        and value["FragmentPath"] == fragment
        and value["DropInPaths"] == ""
        and value["NeedDaemonReload"] == "no"
        and value["Job"] in {"", "0"}
        and value["ControlGroup"] == ""
        and value["ControlPID"] == "0"
    )


@dataclass(frozen=True, slots=True)
class BenchmarkPoststartMachineObservation:
    boot_id: str
    controller: tuple[tuple[str, str], ...]
    native_service: tuple[tuple[str, str], ...]
    native_socket: tuple[tuple[str, str], ...]

    def snapshot_value(self) -> dict[str, object]:
        return {
            "boot_id": self.boot_id,
            "controller": dict(self.controller),
            "native_service": dict(self.native_service),
            "native_socket": dict(self.native_socket),
        }


class CapturedBenchmarkPoststartMachine:
    """The original controller/source plus dead native handle; never stop/reset/start."""

    def __init__(
        self,
        controller: BenchmarkFailedControllerPin | BenchmarkBudget1200RetryControllerPin,
        *,
        execution_id: str,
        native_invocation_id: str,
        owner_pid: int,
        expires_ns: int,
        policy: BenchmarkExecutionPolicy | None = None,
    ) -> None:
        self.controller = (
            BenchmarkBudget1200RetryControllerPin.model_validate(controller.model_dump(mode="json"))
            if isinstance(controller, BenchmarkBudget1200RetryControllerPin)
            else BenchmarkFailedControllerPin.model_validate(controller.model_dump(mode="json"))
        )
        _require(
            re.fullmatch(r"[0-9a-f]{32}", execution_id) is not None
            and re.fullmatch(r"[0-9a-f]{32}", native_invocation_id) is not None
        )
        _require(
            type(owner_pid) is int
            and 0 < owner_pid <= 2**31 - 1
            and type(expires_ns) is int
            and 0 < expires_ns < 2**63
        )
        self.execution_id, self.native_invocation_id = execution_id, native_invocation_id
        self.owner_pid, self.expires_ns = owner_pid, expires_ns
        self._policy = policy
        family = benchmark_unit_family("CPU", policy)
        self._files = NumericalRuntimeFileSnapshots(_ROOT_UID)
        observed = _unit(self.controller.unit, _COMMON + _SERVICE + _CONTROLLER)
        command = re.findall(r"argv\[\]=([^;]+) ;", observed["ExecStart"])
        _require(len(command) == 1)
        arguments = command[0].split()
        _require(len(arguments) == 4 and arguments[:3] == [_PYTHON, "-I", "-B"])
        supervisor = Path(arguments[3])
        if isinstance(self.controller, BenchmarkBudget1200RetryControllerPin):
            # A new proof family recognizes the actual protected program; it cannot
            # reinterpret a legacy controller or substitute another source prefix.
            _require(
                policy is not None
                and policy.schema_version == "embedding-device-benchmark-policy/1.2"
                and family.timeout_seconds == 1200
                and supervisor
                == Path("/usr/local/libexec")
                / ("eom-benchmark-budget1200-retry-" + self.controller.source_commit[:8])
                / "series.py"
            )
        else:
            _require(
                re.fullmatch(
                    r"/var/lib/eom-gpu-benchmark-[A-Za-z0-9-]+/benchmark_(?:goal|recovery)_supervisor\.py",
                    str(supervisor),
                )
                is not None
            )
        self._protected = tuple(
            sorted(
                {
                    p
                    for path in (
                        supervisor,
                        Path("/etc/systemd/system") / family.service_template,
                        Path("/etc/systemd/system") / family.socket_template,
                    )
                    for p in (path, *path.parents)
                }
            )
        )
        _no_acl(self._protected)
        raw = self._files.read(
            supervisor, sha256=self.controller.supervisor_raw_sha256, maximum=128 * 1024
        )
        try:
            tree = ast.parse(raw.decode("utf-8"))
        except (UnicodeError, SyntaxError):
            raise ValueError("BENCHMARK_POSTSTART_MACHINE_UNAVAILABLE") from None
        sources = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SOURCE" for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        _require(sources == [self.controller.source_commit])
        for name, sha in (
            (family.service_template, family.service_sha256),
            (family.socket_template, family.socket_sha256),
        ):
            self._files.read(Path("/etc/systemd/system") / name, sha256=sha, maximum=65536)
        self._original_command = observed["ExecStart"]
        self.observe()

    def observe(self) -> BenchmarkPoststartMachineObservation:
        self._files.assert_unchanged()
        _no_acl(self._protected)
        _require(time.monotonic_ns() > self.expires_ns)
        try:
            os.stat(Path("/proc") / str(self.owner_pid), follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("BENCHMARK_POSTSTART_OWNER_STILL_PRESENT")
        with _BOOT.open("rb") as stream:
            raw = stream.read(128)
        _require(len(raw) == 37 and raw.endswith(b"\n"))
        boot = raw[:-1].decode("ascii")
        _require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot) is not None)
        controller = _unit(self.controller.unit, _COMMON + _SERVICE + _CONTROLLER)
        _dead(
            controller,
            name=self.controller.unit,
            fragment="/run/systemd/transient/" + self.controller.unit,
            controller=True,
        )
        _require(
            controller["InvocationID"] == self.controller.invocation_id
            and controller["ExecStart"] == self._original_command
            and all(
                controller[key] == "0"
                for key in ("MainPID", "ControlPID", "NFileDescriptorStore", "NRestarts")
            )
            and controller["Restart"] == "no"
            and controller["Result"] == "exit-code"
            and controller["ExecMainStatus"] == "1"
        )
        start, end = (
            controller[key]
            for key in ("ExecMainStartTimestampMonotonic", "ExecMainExitTimestampMonotonic")
        )
        _require(
            re.fullmatch(r"[1-9][0-9]{0,18}", start) is not None
            and re.fullmatch(r"[1-9][0-9]{0,18}", end) is not None
            and int(end) >= int(start)
        )
        family = benchmark_unit_family("CPU", self._policy)
        service = family.service_template.replace("@.service", "@" + self.execution_id + ".service")
        socket = family.socket_template.replace("@.socket", "@" + self.execution_id + ".socket")
        native, channel = _unit(service, _COMMON + _SERVICE), _unit(socket, _COMMON)
        _dead(
            native,
            name=service,
            fragment="/etc/systemd/system/" + family.service_template,
            controller=False,
        )
        _dead(
            channel,
            name=socket,
            fragment="/etc/systemd/system/" + family.socket_template,
            controller=False,
        )
        _require(
            native["InvocationID"] in {"", self.native_invocation_id}
            and all(
                native[key] == "0"
                for key in ("MainPID", "ControlPID", "NFileDescriptorStore", "NRestarts")
            )
            and native["Restart"] == "no"
            and native["Result"] == "success"
        )
        require_empty_native_cpu_cgroup(service)
        self._files.assert_unchanged()
        _no_acl(self._protected)
        return BenchmarkPoststartMachineObservation(
            boot,
            tuple(sorted(controller.items())),
            tuple(sorted(native.items())),
            tuple(sorted(channel.items())),
        )


@dataclass(frozen=True, slots=True)
class CapturedBenchmarkPoststartRetirement:
    native_invocation_id: str
    raw_sha256: str
    retirement: RootBenchmarkCpuRetirement
    files: NumericalRuntimeFileSnapshots
    paths: tuple[Path, ...]

    def assert_current(self) -> None:
        self.files.assert_unchanged()
        _no_acl(self.paths)


def read_root_poststart_retirement(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
) -> CapturedBenchmarkPoststartRetirement:
    """Root-only original saved record. Owner trusts its root-minted hash, not a fake reread."""
    _require(os.getresuid() == (_ROOT_UID,) * 3 and os.getresgid() == (_ROOT_GID,) * 3)
    template = benchmark_unit_family("CPU", request.execution_policy).service_template
    unit = template.replace("@.service", "@" + invocation.execution_id + ".service")
    root = BENCHMARK_LIFETIME_ROOT / unit
    names = os.listdir(root)
    _require(len(names) == 1 and re.fullmatch(r"[0-9a-f]{32}", names[0]) is not None)
    native_invocation = names[0]
    phase = root / native_invocation / "retirement"
    for directory in (BENCHMARK_LIFETIME_ROOT, root, phase.parent, phase):
        value = directory.lstat()
        _require(value.st_uid == _ROOT_UID and value.st_mode & 0o7777 == 0o700)
    _require(set(os.listdir(phase)) == {"intent.json", "result.json"})
    paths = tuple(
        sorted(
            {
                p
                for name in ("intent.json", "result.json")
                for p in (phase / name, *(phase / name).parents)
            }
        )
    )
    _no_acl(paths)
    files = NumericalRuntimeFileSnapshots(_ROOT_UID)
    observed = files.observe_protected_member_bytes(phase / "result.json", maximum=65536)
    document = parse_rootlocal_evidence_document(observed.raw, 65536)
    _require(
        set(document)
        == {
            "event",
            "execution_id",
            "job_id",
            "invocation_sha256",
            "observation",
            "admission_granted",
        }
    )
    _require(
        document["event"] == "BENCHMARK_CPU_RETIRED_NOT_ADMITTED"
        and document["execution_id"] == invocation.execution_id
        and document["job_id"] == invocation.job_id
        and document["invocation_sha256"] == invocation.invocation_sha256
        and document["admission_granted"] is False
        and invocation.owner_request_sha256 == request.request_sha256
    )
    retirement = TypeAdapter(RootBenchmarkCpuRetirement).validate_python(document["observation"])
    _require(
        observed.raw
        == canonical_json_bytes(
            document
            | {
                "observation": TypeAdapter(RootBenchmarkCpuRetirement).dump_python(
                    retirement, mode="json"
                )
            }
        )
    )
    original, stopped = retirement.original_terminal, retirement.stopped_unit
    if original.status.result == "exit-code":
        embedding_device_benchmark_bytes(request)
        embedding_device_benchmark_bytes(invocation)
    _require(
        original.invocation_id == native_invocation
        and original.fragment_path == "/etc/systemd/system/" + template
        and original.drop_in_paths == ""
        and not original.status.need_daemon_reload
        and original.status.load_state == "loaded"
        and (
            original.status.result == "timeout"
            # v1.2 can fail during an authenticated continuation, not only at
            # its compute deadline. Preserve the actual saved nonzero exit;
            # legacy retirement stays timeout-only and signals stay excluded.
            or (
                request.schema_version == "embedding-device-benchmark-request/1.2"
                and invocation.schema_version == "embedding-device-benchmark-invocation/1.2"
                and request.execution_policy.schema_version
                == "embedding-device-benchmark-policy/1.2"
                and request.execution_policy.timeout_seconds == 1200
                and invocation.execution_policy == request.execution_policy
                and invocation.device == "CPU"
                and invocation.launch_ordinal == 1
                and invocation.runtime == request.cpu
                and invocation.benchmark_id == request.benchmark_id
                and invocation.benchmark_revision_id == request.benchmark_revision_id
                and original.status.result == "exit-code"
                and original.status.exec_main_code == 1
                and 1 <= original.status.exec_main_status <= 255
            )
        )
        and gpu_unit_terminal_outcome(original) == "FAILED"
        and stopped.load_state == "loaded"
        and stopped.invocation_id in {"", native_invocation}
        and stopped.stored_descriptors == 0
    )
    TypeAdapter(UtcDatetime).validate_python(retirement.observed_at_utc)
    intent = files.observe_protected_member_bytes(phase / "intent.json", maximum=65536)
    expected = document | {
        "event": "BENCHMARK_CPU_RETIREMENT_INTENT",
        "observation": TypeAdapter(type(original)).dump_python(original, mode="json"),
    }
    _require(intent.raw == canonical_json_bytes(expected))
    for name in ("intent.json", "result.json"):
        value = (phase / name).lstat()
        _require(
            value.st_uid == _ROOT_UID
            and value.st_gid == _ROOT_GID
            and value.st_mode & 0o7777 == 0o400
        )
    result = CapturedBenchmarkPoststartRetirement(
        native_invocation, observed.sha256, retirement, files, paths
    )
    result.assert_current()
    return result
