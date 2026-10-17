"""One fixed root CUDA lifecycle; no source admission, model code or Artifact commit."""

from __future__ import annotations

import os
import pwd
import socket
import stat
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_orchestrator.inference_transfer_cpu_systemd import inspect_cpu_unit

from eom_catalog_service.embedding_benchmark_cuda_lifetime import (
    BenchmarkCudaRetirement,
    acknowledge_benchmark_cuda_ready,
    retire_benchmark_cuda_unit,
)
from eom_catalog_service.embedding_benchmark_cuda_observation import (
    CUDA_BENCHMARK_SOCKET,
    CUDA_BENCHMARK_TEMPLATE,
    BenchmarkCudaReadyObservation,
    capture_benchmark_cuda_launch_files,
    observe_benchmark_cuda_ready,
    verify_benchmark_cuda_terminal,
)
from eom_catalog_service.embedding_benchmark_cuda_unacknowledged import (
    require_empty_benchmark_cuda_cgroup,
)
from eom_catalog_service.embedding_benchmark_handoff import (
    PreparedBenchmarkEnvironment,
    benchmark_owner_start_ticks,
)
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_resource_relay import RootBenchmarkGpuResourceRelay
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_CREDENTIALS = struct.Struct("=iII")
_SOCKET_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "NeedDaemonReload",
    "FragmentPath",
    "DropInPaths",
    "Job",
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_CUDA_DRIVER_" + suffix)


@dataclass(frozen=True, slots=True)
class RootBenchmarkCudaLaunch:
    """Actual local lifecycle observations, not a transferable cleanup/source grant."""

    execution_id: str
    job_id: str
    invocation_sha256: str
    started_ns: int
    completed_ns: int
    resources: BenchmarkResourceEvidence
    retirement: BenchmarkCudaRetirement

    @property
    def outcome(self) -> Literal["SUCCEEDED", "FAILED"]:
        return self.retirement.original_terminal.original_outcome


class FixedRootBenchmarkCudaDriver:
    """Trusted root composition supplies an already admitted/prepared original execution.

    Own the transferred resource socket, not the GPU lease. No retry is performed,
    including after a failed start or ACK. Only actual terminal retirement may release
    retained ownership. Source/Job authorization and output publication stay with the
    actual workflow owner; this object is not a public privileged command endpoint.
    """

    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        environment: PreparedBenchmarkEnvironment,
        *,
        backend: NativeEmbeddingBackendPins,
        inventory: PrefixRuntimeInventory,
        host: ProtectedCudaEmbeddingHostClosure,
    ) -> None:
        try:
            _require(
                os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0),
                "ROOT_REQUIRED",
            )
            raw = embedding_device_benchmark_bytes(invocation)
            checked = parse_embedding_device_benchmark_bytes(raw)
            _require(
                isinstance(checked, BenchmarkWorkerInvocation)
                and checked.device == "CUDA"
                and type(environment) is PreparedBenchmarkEnvironment
                and environment.execution_id == checked.execution_id
                and environment.job_id == checked.job_id,
                "IDENTITY_INVALID",
            )
            assert isinstance(checked, BenchmarkWorkerInvocation)
            self._invocation, self._environment = checked, environment
            self._backend, self._inventory, self._host = backend, inventory, host
            owner = pwd.getpwnam("eom-workflow-runner")
            _require(owner.pw_uid > 0 and owner.pw_gid > 0, "OWNER_INVALID")
            self._owner = (environment.owner_pid, owner.pw_uid, owner.pw_gid)
            self._connection = connection
            _require(
                isinstance(connection, socket.socket)
                and connection.family == socket.AF_UNIX
                and connection.type == socket.SOCK_STREAM
                and not connection.get_inheritable()
                and connection.gettimeout() in (None, 0.0),
                "SOCKET_INVALID",
            )
            descriptor = connection.fileno()
            metadata = os.fstat(descriptor)
            _require(stat.S_ISSOCK(metadata.st_mode), "SOCKET_INVALID")
            self._socket_epoch = (descriptor, metadata.st_dev, metadata.st_ino)
            self._unit = CUDA_BENCHMARK_TEMPLATE.replace(
                "@.service", f"@{checked.execution_id}.service"
            )
            self._socket_unit = CUDA_BENCHMARK_SOCKET.replace(
                "@.socket", f"@{checked.execution_id}.socket"
            )
            self._used = False
            now = time.monotonic_ns()
            _require(now < environment.expires_ns <= now + 180 * 10**9, "EXPIRED")
            self._fence()
        except BaseException:
            if isinstance(connection, socket.socket):
                connection.close()
            raise

    def _fence(self) -> None:
        _require(
            os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0),
            "ROOT_REQUIRED",
        )
        _require(time.monotonic_ns() < self._environment.expires_ns, "EXPIRED")
        descriptor = self._connection.fileno()
        metadata = os.fstat(descriptor)
        _require(
            (descriptor, metadata.st_dev, metadata.st_ino) == self._socket_epoch
            and not self._connection.get_inheritable()
            and self._connection.gettimeout() in (None, 0.0)
            and _CREDENTIALS.unpack(
                self._connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, _CREDENTIALS.size
                )
            )
            == self._owner,
            "PEER_CHANGED",
        )
        pid, uid, gid = self._owner
        _require(
            benchmark_owner_start_ticks(pid, uid=uid, gid=gid)
            == self._environment.owner_start_ticks,
            "OWNER_CHANGED",
        )

    def _command(self, arguments: tuple[str, ...]) -> bytes:
        # Late retirement remains possible after compute admission expires. Every
        # start/ACK is separately fenced; expiry must not prevent stopping a retired
        # unit's socket. This helper never admits another numerical execution.
        _require(
            os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0),
            "ROOT_REQUIRED",
        )
        try:
            result = subprocess.run(
                ("/usr/bin/systemctl", *arguments),
                capture_output=True,
                check=False,
                timeout=10,
                env=_ENV,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("BENCHMARK_CUDA_DRIVER_EFFECT_UNCERTAIN") from None
        _require(
            result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
            "EFFECT_UNCERTAIN",
        )
        return result.stdout

    def _socket_state(self, *, active: bool) -> None:
        raw = self._command(
            ("show", self._socket_unit, *("--property=" + key for key in _SOCKET_PROPERTIES))
        )
        fields: dict[str, str] = {}
        for line in raw.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            _require(
                bool(separator) and key in _SOCKET_PROPERTIES and key not in fields,
                "SOCKET_STATE_UNCERTAIN",
            )
            fields[key] = value
        _require(
            set(fields) == set(_SOCKET_PROPERTIES)
            and fields["LoadState"] == "loaded"
            and fields["ActiveState"] == ("active" if active else "inactive")
            # Accept=no may already activate this same fresh service when the
            # admitted owner connects; systemd then reports running, not listening.
            and fields["SubState"] in ({"listening", "running"} if active else {"dead"})
            and fields["NeedDaemonReload"] == "no"
            and fields["FragmentPath"] == "/etc/systemd/system/" + CUDA_BENCHMARK_SOCKET
            and fields["DropInPaths"] == ""
            and fields["Job"] in {"", "0"},
            "SOCKET_STATE_UNCERTAIN",
        )

    def _wait_ready(self) -> BenchmarkCudaReadyObservation:
        original_unit_invocation: str | None = None
        while True:
            self._fence()
            current = inspect_cpu_unit(self._unit, template=CUDA_BENCHMARK_TEMPLATE)
            if current.invocation_id:
                if original_unit_invocation is None:
                    original_unit_invocation = current.invocation_id
                _require(current.invocation_id == original_unit_invocation, "UNIT_CHANGED")
            elif original_unit_invocation is not None:
                raise ValueError("BENCHMARK_CUDA_DRIVER_UNIT_CHANGED")
            try:
                gpu_unit_terminal_outcome(current)
            except ValueError:
                pass  # Still observe the same original handle; never restart it.
            else:
                raise ValueError("BENCHMARK_CUDA_DRIVER_TERMINAL_BEFORE_READY")
            try:
                ready = observe_benchmark_cuda_ready(
                    self._invocation,
                    self._environment,
                    backend=self._backend,
                    inventory=self._inventory,
                    host=self._host,
                )
                _require(
                    original_unit_invocation in (None, ready.unit.invocation_id),
                    "UNIT_CHANGED",
                )
                return ready
            except ValueError as error:
                if str(error) != "BENCHMARK_CUDA_OBSERVATION_NOT_READY":
                    raise
            time.sleep(
                min(0.1, max(0.0, (self._environment.expires_ns - time.monotonic_ns()) / 10**9))
            )

    def _wait_terminal(self, ready: BenchmarkCudaReadyObservation) -> BenchmarkCudaRetirement:
        # The resource relay closes only its socket after finalization. Process/GPU
        # cleanup uses pinned root observations, not the now-closed transport fence.
        # Compute never gains an extension. PID1 has its frozen180s execution and
        # 5s stop bounds; allow15s observation/cleanup grace for an actual timeout
        # terminal. Existing late-retirement verifiers independently prove emptiness.
        terminal_deadline = self._environment.expires_ns + 15 * 10**9
        while True:
            _require(
                os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0),
                "ROOT_REQUIRED",
            )
            _require(time.monotonic_ns() < terminal_deadline, "TERMINATION_UNCERTAIN")
            current = inspect_cpu_unit(self._unit, template=CUDA_BENCHMARK_TEMPLATE)
            _require(
                current.invocation_id == ready.unit.invocation_id
                and current.status.exec_main_started_monotonic
                == ready.unit.status.exec_main_started_monotonic,
                "UNIT_CHANGED",
            )
            try:
                gpu_unit_terminal_outcome(current)
            except ValueError:
                time.sleep(min(0.1, max(0.0, (terminal_deadline - time.monotonic_ns()) / 10**9)))
                continue
            terminal = verify_benchmark_cuda_terminal(
                ready,
                self._invocation,
                self._environment,
                backend=self._backend,
                inventory=self._inventory,
                host=self._host,
            )
            return retire_benchmark_cuda_unit(
                terminal,
                self._invocation,
                self._environment,
                backend=self._backend,
                inventory=self._inventory,
                host=self._host,
            )

    def run(self) -> RootBenchmarkCudaLaunch:
        _require(not self._used, "ALREADY_USED")
        self._used = True
        relay: RootBenchmarkGpuResourceRelay | None = None
        try:
            self._fence()
            captured = capture_benchmark_cuda_launch_files(
                self._invocation,
                self._environment,
                backend=self._backend,
                inventory=self._inventory,
            )
            self._host.assert_current()
            self._socket_state(active=False)
            _require(
                inspect_cpu_unit(self._unit, template=CUDA_BENCHMARK_TEMPLATE).fresh,
                "UNIT_NOT_FRESH",
            )
            require_empty_benchmark_cuda_cgroup(self._unit)
            try:
                (BENCHMARK_HANDOFF_ROOT / self._invocation.execution_id / "control.sock").lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError("BENCHMARK_CUDA_DRIVER_SOCKET_ALREADY_EXISTS")
            captured.assert_current()
            self._inventory.assert_unchanged()
            self._fence()
            started_ns = time.monotonic_ns()
            self._command(("start", self._socket_unit))
            self._socket_state(active=True)
            self._fence()
            self._command(("--no-block", "start", self._unit))
            ready = self._wait_ready()
            relay = RootBenchmarkGpuResourceRelay(
                self._connection,
                self._invocation,
                self._environment,
                backend=self._backend,
                inventory=self._inventory,
                host=self._host,
            )
            relay.sample()
            acknowledge_benchmark_cuda_ready(
                ready,
                self._invocation,
                self._environment,
                backend=self._backend,
                inventory=self._inventory,
                host=self._host,
            )
            relay.sample()
            resources = relay.serve()
            retirement = self._wait_terminal(ready)
            self._command(("stop", self._socket_unit))
            self._socket_state(active=False)
            require_empty_benchmark_cuda_cgroup(self._unit)
            return RootBenchmarkCudaLaunch(
                self._invocation.execution_id,
                self._invocation.job_id,
                self._invocation.invocation_sha256,
                started_ns,
                time.monotonic_ns(),
                resources,
                retirement,
            )
        finally:
            if relay is not None:
                relay.close()
            self._connection.close()
