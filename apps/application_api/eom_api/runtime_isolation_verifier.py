"""Privileged verifier for the fixed Application API service execution boundary.

The parent verifier is a host-root metadata/process inspector. Filesystem access is decided only
by the fixed child probe after entering the pinned service mount namespace and dropping to the
validated service identity with no capabilities.
"""

from __future__ import annotations

import errno
import grp
import importlib.util
import json
import os
import pwd
import secrets
import socket
import stat
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from eom_api.runtime_isolation_pidfd import (
    PidfdAcquisitionError,
    PidfdBackend,
    PidfdFailure,
    PidfdProvider,
    inspect_pidfd_capability,
    pidfd_is_alive,
    pidfd_referenced_pid,
)

SERVICE: Final = "eom-api.service"
SERVICE_USER: Final = "eom-api"
SERVICE_GROUP: Final = "eom-api"
SERVICE_HOME: Final = Path("/var/lib/eom-api")
API_ENV_ROOT: Final = Path("/srv/eom/conda/envs/eom-api")
API_BIN: Final = API_ENV_ROOT / "bin"
API_PYTHON: Final = API_BIN / "python"
API_ENTRYPOINT: Final = API_BIN / "eom-api"
FIXED_CHILD_ARGUMENT: Final = "--fixed-service-probe"
CAPABILITIES_ARGUMENT: Final = "--capabilities"
MAX_PROCESS_FILE_BYTES: Final = 65_536
MAX_CHILD_OUTPUT_BYTES: Final = 65_536
PROBE_TIMEOUT_SECONDS: Final = 30


class AccessExpectation(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class ProbeOperation(StrEnum):
    READ_FILE = "READ_FILE"
    LIST_DIRECTORY = "LIST_DIRECTORY"
    WRITE_STATE_FILE = "WRITE_STATE_FILE"
    CONNECT_UNIX = "CONNECT_UNIX"
    IMPORT_INSTALLED = "IMPORT_INSTALLED"


class ResultCode(StrEnum):
    PASS_ALLOWED = "PASS_ALLOWED"
    PASS_DENIED = "PASS_DENIED"
    FAIL_UNEXPECTEDLY_ALLOWED = "FAIL_UNEXPECTEDLY_ALLOWED"
    FAIL_UNEXPECTEDLY_DENIED = "FAIL_UNEXPECTEDLY_DENIED"
    FAIL_SERVICE_CONTEXT_UNAVAILABLE = "FAIL_SERVICE_CONTEXT_UNAVAILABLE"
    FAIL_PIDFD_UNAVAILABLE = "FAIL_PIDFD_UNAVAILABLE"
    FAIL_PROCESS_IDENTITY_MISMATCH = "FAIL_PROCESS_IDENTITY_MISMATCH"
    FAIL_NAMESPACE_MISMATCH = "FAIL_NAMESPACE_MISMATCH"
    FAIL_IDENTITY_MISMATCH = "FAIL_IDENTITY_MISMATCH"
    FAIL_SERVICE_RESTART_RACE = "FAIL_SERVICE_RESTART_RACE"


@dataclass(frozen=True)
class ProbeSpec:
    logical_name: str
    expectation: AccessExpectation
    operation: ProbeOperation
    path: Path | None
    reason: str


PROBE_INVENTORY: Final = (
    ProbeSpec(
        "config_read",
        AccessExpectation.ALLOWED,
        ProbeOperation.READ_FILE,
        Path("/etc/eom-api/api.yaml"),
        "service configuration is required and read-only",
    ),
    ProbeSpec(
        "api_environment_read",
        AccessExpectation.DENIED,
        ProbeOperation.READ_FILE,
        Path("/etc/eom/secrets/api.env"),
        "systemd manager supplies the environment; the service cannot read the secret file",
    ),
    ProbeSpec(
        "state_write",
        AccessExpectation.ALLOWED,
        ProbeOperation.WRITE_STATE_FILE,
        SERVICE_HOME,
        "the service owns its fixed state directory",
    ),
    ProbeSpec(
        "installed_import",
        AccessExpectation.ALLOWED,
        ProbeOperation.IMPORT_INSTALLED,
        None,
        "runtime imports must resolve from the installed environment",
    ),
    ProbeSpec(
        "repository_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/home/eom/EOM"),
        "the service must not depend on or inspect the source checkout",
    ),
    ProbeSpec(
        "eomis_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/home/eom/EOMIS"),
        "the separate EOMIS repository is outside the API boundary",
    ),
    ProbeSpec(
        "root_codex_auth_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/root/.codex"),
        "root Codex authentication is outside the API boundary",
    ),
    ProbeSpec(
        "worker_home_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/srv/eom/worker-homes"),
        "worker HOME directories are isolated from the API",
    ),
    ProbeSpec(
        "worker_auth_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/srv/eom/worker-homes/eom-cdx-01/.codex"),
        "worker authentication is isolated from the API",
    ),
    ProbeSpec(
        "nas_read",
        AccessExpectation.DENIED,
        ProbeOperation.LIST_DIRECTORY,
        Path("/mnt/nas"),
        "NAS access belongs to validated orchestrator commit boundaries",
    ),
    ProbeSpec(
        "docker_socket_connect",
        AccessExpectation.DENIED,
        ProbeOperation.CONNECT_UNIX,
        Path("/var/run/docker.sock"),
        "the API must not control Docker",
    ),
    ProbeSpec(
        "postgres_secret_read",
        AccessExpectation.DENIED,
        ProbeOperation.READ_FILE,
        Path("/etc/eom/secrets/postgres.env"),
        "the platform database deployment secret is unrelated",
    ),
    ProbeSpec(
        "slack_secret_read",
        AccessExpectation.DENIED,
        ProbeOperation.READ_FILE,
        Path("/etc/eom/secrets/dev-slack.env"),
        "the optional development reporter secret is unrelated",
    ),
    ProbeSpec(
        "observe_secret_read",
        AccessExpectation.DENIED,
        ProbeOperation.READ_FILE,
        Path("/etc/eom/secrets/observe.env"),
        "the Observability secret is outside the API boundary",
    ),
)
PROBE_BY_NAME: Final = {probe.logical_name: probe for probe in PROBE_INVENTORY}


@dataclass(frozen=True)
class NamespaceIdentity:
    device: int
    inode: int


@dataclass(frozen=True)
class ServiceSnapshot:
    active_state: str
    sub_state: str
    main_pid: int
    start_time_ticks: int
    unit_user: str
    unit_group: str
    unit_supplementary_groups: tuple[str, ...]
    exec_start: str
    unit_working_directory: str
    unit_root_directory: str
    unit_root_image: str
    uid: tuple[int, int, int, int]
    gid: tuple[int, int, int, int]
    supplementary_gids: tuple[int, ...]
    command_line: tuple[str, ...]
    executable: str
    process_working_directory: str
    process_root: str
    mount_namespace: NamespaceIdentity
    host_mount_namespace: NamespaceIdentity
    user_namespace: NamespaceIdentity
    host_user_namespace: NamespaceIdentity
    no_new_privileges: bool
    capabilities: tuple[int, int, int, int, int]
    private_tmp: str
    private_users: str
    private_network: str
    protect_system: str
    protect_home: str
    capability_bounding_set: str
    read_only_paths: frozenset[str]
    read_write_paths: frozenset[str]
    inaccessible_paths: frozenset[str]
    restrict_address_families: frozenset[str]
    ip_address_deny: frozenset[str]
    ip_address_allow: frozenset[str]


@dataclass(frozen=True)
class ProbeContext:
    uid: int
    gid: int
    supplementary_gids: tuple[int, ...]
    mount_namespace: NamespaceIdentity
    no_new_privileges: bool
    capabilities: tuple[int, int, int, int, int]
    working_directory: str
    home: str
    user: str
    logname: str
    environment_sanitized: bool


@dataclass(frozen=True)
class ProbeResult:
    logical_name: str
    code: ResultCode
    detail_code: str


@dataclass(frozen=True)
class ProbeExecution:
    context: ProbeContext
    results: tuple[ProbeResult, ...]


@dataclass(frozen=True)
class StabilityObservation:
    active_state: str
    sub_state: str
    main_pid: int
    start_time_ticks: int
    mount_namespace: NamespaceIdentity
    process_alive: bool


@dataclass(frozen=True)
class VerificationReport:
    results: tuple[ProbeResult, ...]


class IsolationVerificationError(RuntimeError):
    def __init__(self, code: ResultCode, logical_name: str) -> None:
        super().__init__(f"{code.value} {logical_name}")
        self.code = code
        self.logical_name = logical_name


@dataclass
class ServiceProcessHandle:
    snapshot: ServiceSnapshot
    proc_fd: int
    pid_fd: int
    mount_namespace_fd: int
    pidfd_backend: PidfdBackend


class RuntimeIsolationAdapter(Protocol):
    def open_service(self) -> ServiceProcessHandle: ...

    def run_fixed_probe(self, process: ServiceProcessHandle) -> ProbeExecution: ...

    def observe_stability(self, process: ServiceProcessHandle) -> StabilityObservation: ...

    def close_service(self, process: ServiceProcessHandle) -> None: ...


EXPECTED_READ_ONLY_PATHS: Final = frozenset({"/etc/eom-api/api.yaml", "/etc/eom/secrets/api.env"})
EXPECTED_READ_WRITE_PATHS: Final = frozenset({str(SERVICE_HOME)})
EXPECTED_INACCESSIBLE_PATHS: Final = frozenset(
    str(probe.path)
    for probe in PROBE_INVENTORY
    if probe.expectation is AccessExpectation.DENIED
    # These are denied by the service identity or an inaccessible parent, not by
    # separate InaccessiblePaths entries in the unit.
    and probe.logical_name not in {"api_environment_read", "worker_auth_read"}
)


def validate_service_snapshot(snapshot: ServiceSnapshot) -> None:
    if snapshot.active_state != "active" or snapshot.sub_state != "running":
        raise IsolationVerificationError(
            ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "service_not_running"
        )
    if snapshot.main_pid <= 1:
        raise IsolationVerificationError(ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "main_pid")
    account = pwd.getpwnam(SERVICE_USER)
    group = grp.getgrnam(SERVICE_GROUP)
    expected_uid = account.pw_uid
    expected_gid = group.gr_gid
    if (
        snapshot.unit_user != SERVICE_USER
        or snapshot.unit_group != SERVICE_GROUP
        or snapshot.unit_supplementary_groups
        or any(value != expected_uid for value in snapshot.uid)
        or any(value != expected_gid for value in snapshot.gid)
        or snapshot.supplementary_gids != (expected_gid,)
    ):
        raise IsolationVerificationError(
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH, "service_identity"
        )
    expected_command = (str(API_PYTHON), str(API_ENTRYPOINT), "serve")
    executable = Path(snapshot.executable)
    if (
        f"path={API_ENTRYPOINT}" not in snapshot.exec_start
        or f"argv[]={API_ENTRYPOINT} serve" not in snapshot.exec_start
        or snapshot.command_line != expected_command
        or executable.parent != API_BIN
        or not executable.name.startswith("python")
        or snapshot.unit_working_directory != str(SERVICE_HOME)
        or snapshot.process_working_directory != str(SERVICE_HOME)
        or snapshot.unit_root_directory
        or snapshot.unit_root_image
        or snapshot.process_root != "/"
    ):
        raise IsolationVerificationError(
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH, "service_process"
        )
    if (
        snapshot.mount_namespace == snapshot.host_mount_namespace
        or snapshot.user_namespace != snapshot.host_user_namespace
    ):
        raise IsolationVerificationError(ResultCode.FAIL_NAMESPACE_MISMATCH, "service_namespace")
    if not snapshot.no_new_privileges or any(snapshot.capabilities):
        raise IsolationVerificationError(ResultCode.FAIL_IDENTITY_MISMATCH, "service_privileges")
    hardening_matches = (
        snapshot.private_tmp == "yes"
        and snapshot.private_users == "no"
        and snapshot.private_network == "no"
        and snapshot.protect_system == "strict"
        and snapshot.protect_home == "yes"
        and snapshot.capability_bounding_set == ""
        and snapshot.read_only_paths == EXPECTED_READ_ONLY_PATHS
        and snapshot.read_write_paths == EXPECTED_READ_WRITE_PATHS
        and snapshot.inaccessible_paths >= EXPECTED_INACCESSIBLE_PATHS
        and snapshot.restrict_address_families == frozenset({"AF_INET", "AF_INET6", "AF_UNIX"})
        and snapshot.ip_address_deny == frozenset({"0.0.0.0/0", "::/0"})
        and snapshot.ip_address_allow == frozenset({"127.0.0.0/8", "::1/128"})
    )
    if not hardening_matches:
        raise IsolationVerificationError(ResultCode.FAIL_NAMESPACE_MISMATCH, "unit_sandbox")


def validate_probe_execution(
    snapshot: ServiceSnapshot, execution: ProbeExecution
) -> tuple[ProbeResult, ...]:
    context = execution.context
    expected_uid = pwd.getpwnam(SERVICE_USER).pw_uid
    expected_gid = grp.getgrnam(SERVICE_GROUP).gr_gid
    if (
        context.uid != expected_uid
        or context.gid != expected_gid
        or context.supplementary_gids != (expected_gid,)
        or not context.no_new_privileges
        or any(context.capabilities)
        or context.working_directory != str(SERVICE_HOME)
        or context.home != str(SERVICE_HOME)
        or context.user != SERVICE_USER
        or context.logname != SERVICE_USER
        or not context.environment_sanitized
    ):
        raise IsolationVerificationError(ResultCode.FAIL_IDENTITY_MISMATCH, "probe_identity")
    if context.mount_namespace != snapshot.mount_namespace:
        raise IsolationVerificationError(ResultCode.FAIL_NAMESPACE_MISMATCH, "probe_namespace")

    by_name: dict[str, ProbeResult] = {}
    for result in execution.results:
        if result.logical_name in by_name or result.logical_name not in PROBE_BY_NAME:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "probe_inventory"
            )
        by_name[result.logical_name] = result
    if set(by_name) != set(PROBE_BY_NAME):
        raise IsolationVerificationError(
            ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "probe_inventory"
        )

    for spec in PROBE_INVENTORY:
        result = by_name[spec.logical_name]
        expected_code = (
            ResultCode.PASS_ALLOWED
            if spec.expectation is AccessExpectation.ALLOWED
            else ResultCode.PASS_DENIED
        )
        if result.code is not expected_code:
            failure = (
                ResultCode.FAIL_UNEXPECTEDLY_DENIED
                if spec.expectation is AccessExpectation.ALLOWED
                else ResultCode.FAIL_UNEXPECTEDLY_ALLOWED
            )
            raise IsolationVerificationError(failure, spec.logical_name)
    return tuple(by_name[spec.logical_name] for spec in PROBE_INVENTORY)


def validate_stability(snapshot: ServiceSnapshot, observation: StabilityObservation) -> None:
    if (
        not observation.process_alive
        or observation.active_state != "active"
        or observation.sub_state != "running"
        or observation.main_pid != snapshot.main_pid
        or observation.start_time_ticks != snapshot.start_time_ticks
        or observation.mount_namespace != snapshot.mount_namespace
    ):
        raise IsolationVerificationError(ResultCode.FAIL_SERVICE_RESTART_RACE, "service_process")


def verify_runtime_isolation(
    adapter: RuntimeIsolationAdapter | None = None,
) -> VerificationReport:
    runtime_adapter = adapter or LinuxRuntimeIsolationAdapter()
    process = runtime_adapter.open_service()
    try:
        validate_service_snapshot(process.snapshot)
        execution = runtime_adapter.run_fixed_probe(process)
        results = validate_probe_execution(process.snapshot, execution)
        validate_stability(process.snapshot, runtime_adapter.observe_stability(process))
        return VerificationReport(results)
    finally:
        runtime_adapter.close_service(process)


class LinuxRuntimeIsolationAdapter:
    _systemctl_properties: Final = (
        "ActiveState",
        "SubState",
        "MainPID",
        "User",
        "Group",
        "SupplementaryGroups",
        "ExecStart",
        "WorkingDirectory",
        "RootDirectory",
        "RootImage",
        "PrivateTmp",
        "PrivateUsers",
        "PrivateNetwork",
        "ProtectSystem",
        "ProtectHome",
        "NoNewPrivileges",
        "CapabilityBoundingSet",
        "ReadOnlyPaths",
        "ReadWritePaths",
        "InaccessiblePaths",
        "RestrictAddressFamilies",
        "IPAddressDeny",
        "IPAddressAllow",
    )

    def __init__(self, pidfd_provider: PidfdProvider | None = None) -> None:
        self._pidfd_provider = pidfd_provider or PidfdProvider.from_system()

    def open_service(self) -> ServiceProcessHandle:
        if os.geteuid() != 0:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "root_operator_required"
            )
        properties = self._read_systemd_properties()
        try:
            main_pid = int(properties["MainPID"])
        except (KeyError, ValueError) as error:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "main_pid"
            ) from error
        if main_pid <= 1:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "main_pid"
            )
        if properties.get("ActiveState") != "active" or properties.get("SubState") != "running":
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "service_not_running"
            )

        opened: list[int] = []
        try:
            acquired_pidfd = self._pidfd_provider.open(main_pid)
            pid_fd = acquired_pidfd.descriptor
            opened.append(pid_fd)
            referenced_pid = self._pidfd_referenced_pid(pid_fd)
            if referenced_pid == -1 or not self._pidfd_is_alive(pid_fd):
                raise IsolationVerificationError(
                    ResultCode.FAIL_SERVICE_RESTART_RACE, "pidfd_identity"
                )
            if referenced_pid != main_pid:
                raise IsolationVerificationError(
                    ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH, "pidfd_identity"
                )
            proc_fd = self._open_process_directory(main_pid)
            opened.append(proc_fd)
            mount_fd = self._open_mount_namespace(proc_fd)
            opened.append(mount_fd)
            snapshot = self._snapshot(properties, main_pid, proc_fd, mount_fd)
            current = self._read_systemd_properties()
            referenced_pid = self._pidfd_referenced_pid(pid_fd)
            if (
                current.get("ActiveState") != "active"
                or current.get("SubState") != "running"
                or current.get("MainPID") != str(main_pid)
                or referenced_pid == -1
                or not self._pidfd_is_alive(pid_fd)
            ):
                raise IsolationVerificationError(ResultCode.FAIL_SERVICE_RESTART_RACE, "main_pid")
            if referenced_pid != main_pid:
                raise IsolationVerificationError(
                    ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH, "pidfd_identity"
                )
            return ServiceProcessHandle(snapshot, proc_fd, pid_fd, mount_fd, acquired_pidfd.backend)
        except PidfdAcquisitionError as error:
            for descriptor in reversed(opened):
                os.close(descriptor)
            code = (
                ResultCode.FAIL_SERVICE_RESTART_RACE
                if error.failure is PidfdFailure.PROCESS_EXITED
                else ResultCode.FAIL_PIDFD_UNAVAILABLE
            )
            raise IsolationVerificationError(code, error.failure.value.casefold()) from None
        except IsolationVerificationError:
            for descriptor in reversed(opened):
                os.close(descriptor)
            raise
        except (OSError, KeyError, ValueError) as error:
            for descriptor in reversed(opened):
                os.close(descriptor)
            if isinstance(error, OSError) and error.errno in {errno.ENOENT, errno.ESRCH}:
                raise IsolationVerificationError(
                    ResultCode.FAIL_SERVICE_RESTART_RACE, "process_exited"
                ) from None
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "process_snapshot"
            ) from error

    def run_fixed_probe(self, process: ServiceProcessHandle) -> ProbeExecution:
        uid = pwd.getpwnam(SERVICE_USER).pw_uid
        gid = grp.getgrnam(SERVICE_GROUP).gr_gid
        mount_reference = f"/proc/self/fd/{process.mount_namespace_fd}"
        command = (
            "/usr/bin/nsenter",
            f"--mount={mount_reference}",
            f"--wd={SERVICE_HOME}",
            "--",
            "/usr/bin/setpriv",
            f"--regid={gid}",
            f"--groups={gid}",
            f"--reuid={uid}",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
            "--nnp",
            "--reset-env",
            str(API_PYTHON),
            "-I",
            "-m",
            "eom_api.runtime_isolation_verifier",
            FIXED_CHILD_ARGUMENT,
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd="/",
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
                pass_fds=(process.mount_namespace_fd,),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "fixed_probe"
            ) from error
        if (
            completed.returncode != 0
            or completed.stderr
            or len(completed.stdout.encode("utf-8")) > MAX_CHILD_OUTPUT_BYTES
        ):
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "fixed_probe"
            )
        return _parse_probe_execution(completed.stdout)

    def observe_stability(self, process: ServiceProcessHandle) -> StabilityObservation:
        process_alive = self._pidfd_is_alive(process.pid_fd)
        try:
            properties = self._read_systemd_properties()
            start_time = _process_start_time(process.proc_fd)
            namespace = _namespace_identity_from_fd(process.mount_namespace_fd)
            main_pid = int(properties["MainPID"])
        except (OSError, KeyError, ValueError):
            return StabilityObservation("unknown", "unknown", 0, 0, NamespaceIdentity(0, 0), False)
        return StabilityObservation(
            properties["ActiveState"],
            properties["SubState"],
            main_pid,
            start_time,
            namespace,
            process_alive,
        )

    def close_service(self, process: ServiceProcessHandle) -> None:
        for descriptor in (
            process.mount_namespace_fd,
            process.pid_fd,
            process.proc_fd,
        ):
            os.close(descriptor)

    def _open_process_directory(self, main_pid: int) -> int:
        return os.open(
            f"/proc/{main_pid}", os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )

    def _open_mount_namespace(self, proc_fd: int) -> int:
        return os.open("ns/mnt", os.O_RDONLY | os.O_CLOEXEC, dir_fd=proc_fd)

    def _pidfd_referenced_pid(self, pid_fd: int) -> int:
        return pidfd_referenced_pid(pid_fd)

    def _pidfd_is_alive(self, pid_fd: int) -> bool:
        return pidfd_is_alive(pid_fd)

    def _read_systemd_properties(self) -> dict[str, str]:
        command = ["/usr/bin/systemctl", "show", SERVICE, "--no-pager"]
        command.extend(f"--property={name}" for name in self._systemctl_properties)
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "systemd_properties"
            ) from error
        properties: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in self._systemctl_properties or key in properties:
                raise IsolationVerificationError(
                    ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "systemd_properties"
                )
            properties[key] = value
        if set(properties) != set(self._systemctl_properties):
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "systemd_properties"
            )
        return properties

    def _snapshot(
        self,
        properties: dict[str, str],
        main_pid: int,
        proc_fd: int,
        mount_fd: int,
    ) -> ServiceSnapshot:
        status = _process_status(proc_fd)
        user_fd = os.open("ns/user", os.O_RDONLY | os.O_CLOEXEC, dir_fd=proc_fd)
        try:
            user_namespace = _namespace_identity_from_fd(user_fd)
        finally:
            os.close(user_fd)
        return ServiceSnapshot(
            active_state=properties["ActiveState"],
            sub_state=properties["SubState"],
            main_pid=main_pid,
            start_time_ticks=_process_start_time(proc_fd),
            unit_user=properties["User"],
            unit_group=properties["Group"],
            unit_supplementary_groups=tuple(properties["SupplementaryGroups"].split()),
            exec_start=properties["ExecStart"],
            unit_working_directory=properties["WorkingDirectory"],
            unit_root_directory=properties["RootDirectory"],
            unit_root_image=properties["RootImage"],
            uid=status.uid,
            gid=status.gid,
            supplementary_gids=status.supplementary_gids,
            command_line=_process_command_line(proc_fd),
            executable=os.readlink("exe", dir_fd=proc_fd),
            process_working_directory=os.readlink("cwd", dir_fd=proc_fd),
            process_root=os.readlink("root", dir_fd=proc_fd),
            mount_namespace=_namespace_identity_from_fd(mount_fd),
            host_mount_namespace=_namespace_identity(Path("/proc/self/ns/mnt")),
            user_namespace=user_namespace,
            host_user_namespace=_namespace_identity(Path("/proc/self/ns/user")),
            no_new_privileges=status.no_new_privileges,
            capabilities=status.capabilities,
            private_tmp=properties["PrivateTmp"],
            private_users=properties["PrivateUsers"],
            private_network=properties["PrivateNetwork"],
            protect_system=properties["ProtectSystem"],
            protect_home=properties["ProtectHome"],
            capability_bounding_set=properties["CapabilityBoundingSet"],
            read_only_paths=frozenset(properties["ReadOnlyPaths"].split()),
            read_write_paths=frozenset(properties["ReadWritePaths"].split()),
            inaccessible_paths=frozenset(properties["InaccessiblePaths"].split()),
            restrict_address_families=frozenset(properties["RestrictAddressFamilies"].split()),
            ip_address_deny=frozenset(properties["IPAddressDeny"].split()),
            ip_address_allow=frozenset(properties["IPAddressAllow"].split()),
        )


@dataclass(frozen=True)
class _ProcessStatus:
    uid: tuple[int, int, int, int]
    gid: tuple[int, int, int, int]
    supplementary_gids: tuple[int, ...]
    no_new_privileges: bool
    capabilities: tuple[int, int, int, int, int]


def _read_proc_file(proc_fd: int, name: str) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=proc_fd)
    try:
        content = os.read(descriptor, MAX_PROCESS_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(content) > MAX_PROCESS_FILE_BYTES:
        raise OSError(errno.EFBIG, "process metadata exceeds fixed limit")
    return content


def _process_status(proc_fd: int) -> _ProcessStatus:
    values: dict[str, str] = {}
    for line in _read_proc_file(proc_fd, "status").decode("ascii", "strict").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key] = value.strip()
    uid = tuple(int(value) for value in values["Uid"].split())
    gid = tuple(int(value) for value in values["Gid"].split())
    capabilities = tuple(
        int(values[name], 16) for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    )
    if len(uid) != 4 or len(gid) != 4 or len(capabilities) != 5:
        raise OSError(errno.EINVAL, "invalid process identity metadata")
    return _ProcessStatus(
        (uid[0], uid[1], uid[2], uid[3]),
        (gid[0], gid[1], gid[2], gid[3]),
        tuple(int(value) for value in values.get("Groups", "").split()),
        values["NoNewPrivs"] == "1",
        (
            capabilities[0],
            capabilities[1],
            capabilities[2],
            capabilities[3],
            capabilities[4],
        ),
    )


def _process_start_time(proc_fd: int) -> int:
    content = _read_proc_file(proc_fd, "stat").decode("ascii", "strict")
    closing = content.rfind(")")
    if closing < 0:
        raise OSError(errno.EINVAL, "invalid process stat metadata")
    fields = content[closing + 2 :].split()
    return int(fields[19])


def _process_command_line(proc_fd: int) -> tuple[str, ...]:
    content = _read_proc_file(proc_fd, "cmdline")
    return tuple(value.decode("utf-8", "strict") for value in content.split(b"\0") if value)


def _namespace_identity(path: Path) -> NamespaceIdentity:
    metadata = path.stat()
    return NamespaceIdentity(metadata.st_dev, metadata.st_ino)


def _namespace_identity_from_fd(descriptor: int) -> NamespaceIdentity:
    metadata = os.fstat(descriptor)
    return NamespaceIdentity(metadata.st_dev, metadata.st_ino)


def _parse_probe_execution(source: str) -> ProbeExecution:
    try:
        payload: Any = json.loads(source)
        if not isinstance(payload, dict) or set(payload) != {"context", "results"}:
            raise ValueError
        raw_context = payload["context"]
        raw_results = payload["results"]
        context_keys = {
            "uid",
            "gid",
            "supplementary_gids",
            "mount_namespace",
            "no_new_privileges",
            "capabilities",
            "working_directory",
            "home",
            "user",
            "logname",
            "environment_sanitized",
        }
        if (
            not isinstance(raw_context, dict)
            or set(raw_context) != context_keys
            or not isinstance(raw_results, list)
        ):
            raise ValueError
        namespace = raw_context["mount_namespace"]
        supplementary_gids = raw_context["supplementary_gids"]
        capabilities = raw_context["capabilities"]
        if (
            not isinstance(namespace, dict)
            or set(namespace) != {"device", "inode"}
            or not isinstance(supplementary_gids, list)
            or not all(type(value) is int for value in supplementary_gids)
            or not isinstance(capabilities, list)
            or len(capabilities) != 5
            or not all(type(value) is int for value in capabilities)
            or type(raw_context["uid"]) is not int
            or type(raw_context["gid"]) is not int
            or type(namespace["device"]) is not int
            or type(namespace["inode"]) is not int
            or type(raw_context["no_new_privileges"]) is not bool
            or type(raw_context["environment_sanitized"]) is not bool
            or not all(
                isinstance(raw_context[key], str)
                for key in ("working_directory", "home", "user", "logname")
            )
        ):
            raise ValueError
        context = ProbeContext(
            uid=raw_context["uid"],
            gid=raw_context["gid"],
            supplementary_gids=tuple(supplementary_gids),
            mount_namespace=NamespaceIdentity(namespace["device"], namespace["inode"]),
            no_new_privileges=raw_context["no_new_privileges"],
            capabilities=(
                capabilities[0],
                capabilities[1],
                capabilities[2],
                capabilities[3],
                capabilities[4],
            ),
            working_directory=raw_context["working_directory"],
            home=raw_context["home"],
            user=raw_context["user"],
            logname=raw_context["logname"],
            environment_sanitized=raw_context["environment_sanitized"],
        )
        results_list: list[ProbeResult] = []
        for value in raw_results:
            if (
                not isinstance(value, dict)
                or set(value) != {"logical_name", "code", "detail_code"}
                or not all(isinstance(item, str) for item in value.values())
                or value["detail_code"]
                not in {"ACCESSIBLE", "ACCESS_DENIED", "NOT_VISIBLE", "OS_ERROR"}
            ):
                raise ValueError
            results_list.append(
                ProbeResult(
                    logical_name=value["logical_name"],
                    code=ResultCode(value["code"]),
                    detail_code=value["detail_code"],
                )
            )
        results = tuple(results_list)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise IsolationVerificationError(
            ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "probe_protocol"
        ) from error
    return ProbeExecution(context, results)


def _fixed_service_probe() -> ProbeExecution:
    proc_fd = os.open("/proc/self", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        status = _process_status(proc_fd)
    finally:
        os.close(proc_fd)
    namespace = _namespace_identity(Path("/proc/self/ns/mnt"))
    account = pwd.getpwnam(SERVICE_USER)
    environment_sanitized = (
        "PYTHONPATH" not in os.environ
        and os.environ.get("HOME") == str(SERVICE_HOME)
        and os.environ.get("USER") == SERVICE_USER
        and os.environ.get("LOGNAME") == SERVICE_USER
    )
    context = ProbeContext(
        uid=os.getuid(),
        gid=os.getgid(),
        supplementary_gids=tuple(os.getgroups()),
        mount_namespace=namespace,
        no_new_privileges=status.no_new_privileges,
        capabilities=status.capabilities,
        working_directory=os.getcwd(),
        home=os.environ.get("HOME", ""),
        user=os.environ.get("USER", ""),
        logname=os.environ.get("LOGNAME", ""),
        environment_sanitized=environment_sanitized and account.pw_dir == str(SERVICE_HOME),
    )
    results = tuple(_execute_probe(spec) for spec in PROBE_INVENTORY)
    return ProbeExecution(context, results)


def _execute_probe(spec: ProbeSpec) -> ProbeResult:
    try:
        if spec.operation is ProbeOperation.READ_FILE:
            _read_one_byte(_required_probe_path(spec))
        elif spec.operation is ProbeOperation.LIST_DIRECTORY:
            _list_directory(_required_probe_path(spec))
        elif spec.operation is ProbeOperation.WRITE_STATE_FILE:
            _write_temporary_state_probe(_required_probe_path(spec))
        elif spec.operation is ProbeOperation.CONNECT_UNIX:
            _connect_unix(_required_probe_path(spec))
        elif spec.operation is ProbeOperation.IMPORT_INSTALLED:
            _verify_installed_imports()
        else:
            raise OSError(errno.EINVAL, "unknown fixed probe operation")
    except OSError as error:
        if spec.expectation is AccessExpectation.DENIED and error.errno in {
            errno.EACCES,
            errno.EPERM,
            errno.ENOENT,
            errno.ENOTDIR,
        }:
            detail = (
                "ACCESS_DENIED" if error.errno in {errno.EACCES, errno.EPERM} else "NOT_VISIBLE"
            )
            return ProbeResult(spec.logical_name, ResultCode.PASS_DENIED, detail)
        failure = (
            ResultCode.FAIL_UNEXPECTEDLY_ALLOWED
            if spec.expectation is AccessExpectation.DENIED
            else ResultCode.FAIL_UNEXPECTEDLY_DENIED
        )
        return ProbeResult(spec.logical_name, failure, "OS_ERROR")
    if spec.expectation is AccessExpectation.DENIED:
        return ProbeResult(spec.logical_name, ResultCode.FAIL_UNEXPECTEDLY_ALLOWED, "ACCESSIBLE")
    return ProbeResult(spec.logical_name, ResultCode.PASS_ALLOWED, "ACCESSIBLE")


def _required_probe_path(spec: ProbeSpec) -> Path:
    if spec.path is None:
        raise OSError(errno.EINVAL, "fixed path is unavailable")
    return spec.path


def _read_one_byte(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.read(descriptor, 1)
    finally:
        os.close(descriptor)


def _list_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.listdir(descriptor)
    finally:
        os.close(descriptor)


def _connect_unix(path: Path) -> None:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(1)
        connection.connect(str(path))
    finally:
        connection.close()


def _write_temporary_state_probe(directory: Path) -> None:
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    name = ".runtime-isolation-probe-" + secrets.token_hex(16)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        created = True
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise OSError(errno.EPERM, "temporary probe metadata mismatch")
        os.write(descriptor, b"runtime-isolation-probe\n")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            os.unlink(name, dir_fd=directory_fd)
        os.close(directory_fd)


def _verify_installed_imports() -> None:
    site_root = API_ENV_ROOT / "lib" / "python3.12" / "site-packages"
    for module in ("eom_api", "eom_api_contracts", "eom_operator_identity"):
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise OSError(errno.ENOENT, "installed module is unavailable")
        origin = Path(spec.origin).resolve()
        if not origin.is_relative_to(site_root) or origin.is_relative_to(Path("/home/eom/EOM")):
            raise OSError(errno.EPERM, "module origin is outside the installed environment")


def _execution_payload(execution: ProbeExecution) -> dict[str, object]:
    return {
        "context": {
            "uid": execution.context.uid,
            "gid": execution.context.gid,
            "supplementary_gids": list(execution.context.supplementary_gids),
            "mount_namespace": {
                "device": execution.context.mount_namespace.device,
                "inode": execution.context.mount_namespace.inode,
            },
            "no_new_privileges": execution.context.no_new_privileges,
            "capabilities": list(execution.context.capabilities),
            "working_directory": execution.context.working_directory,
            "home": execution.context.home,
            "user": execution.context.user,
            "logname": execution.context.logname,
            "environment_sanitized": execution.context.environment_sanitized,
        },
        "results": [
            {
                "logical_name": result.logical_name,
                "code": result.code.value,
                "detail_code": result.detail_code,
            }
            for result in execution.results
        ],
    }


def _print_pidfd_capabilities() -> bool:
    capability = inspect_pidfd_capability()
    print("runtime_isolation_verifier_capability=" + ("READY" if capability.ready else "BLOCKED"))
    print(f"selected_pidfd_backend={capability.selected_backend.value}")
    print(
        "python_os_pidfd=" + ("AVAILABLE" if capability.python_binding_available else "UNAVAILABLE")
    )
    print("libc_pidfd=" + ("AVAILABLE" if capability.libc_backend_available else "UNAVAILABLE"))
    print("pidfd_policy=FAIL_CLOSED")
    print(f"pidfd_detail={capability.detail_code}")
    return capability.ready


def main() -> None:
    arguments = tuple(sys.argv[1:])
    try:
        if arguments == (CAPABILITIES_ARGUMENT,):
            if not _print_pidfd_capabilities():
                raise SystemExit(1)
            return
        if arguments == (FIXED_CHILD_ARGUMENT,):
            execution = _fixed_service_probe()
            print(json.dumps(_execution_payload(execution), sort_keys=True, separators=(",", ":")))
            return
        if arguments:
            print(
                f"{ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE.value} fixed_arguments",
                file=sys.stderr,
            )
            raise SystemExit(2)
        report = verify_runtime_isolation()
    except IsolationVerificationError as error:
        print(f"{error.code.value} {error.logical_name}", file=sys.stderr)
        raise SystemExit(1) from None
    except SystemExit:
        raise
    except Exception:
        print(
            f"{ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE.value} internal_error",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    for result in report.results:
        print(f"{result.code.value} {result.logical_name}")


if __name__ == "__main__":
    main()
