"""One original CPU benchmark lifecycle; no source/Job admission or Artifact publication."""

from __future__ import annotations

import os
import pwd
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.native_embedding_cpu_execution import require_empty_native_cpu_cgroup
from pydantic import TypeAdapter

from eom_catalog_service.embedding_benchmark_handoff import (
    PreparedBenchmarkEnvironment,
    benchmark_owner_start_ticks,
    capture_prepared_benchmark_environment,
)
from eom_catalog_service.embedding_benchmark_layout import (
    BENCHMARK_HANDOFF_ROOT,
    BENCHMARK_LIFETIME_ROOT,
)
from eom_catalog_service.embedding_benchmark_unit_control import (
    FixedRootBenchmarkUnits,
    require_root_benchmark_control,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    reserve_unit_effect_phase,
    write_unit_effect_record,
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_CPU_DRIVER_" + suffix)


@dataclass(frozen=True, slots=True)
class RootBenchmarkCpuRetirement:
    original_terminal: CpuUnitObservation
    stopped_unit: StoppedGpuUnit
    observed_at_utc: str


@dataclass(frozen=True, slots=True)
class RootBenchmarkCpuLaunch:
    """Local machine observations, not a worker result or source/cleanup grant."""

    execution_id: str
    job_id: str
    invocation_sha256: str
    started_ns: int
    completed_ns: int
    retirement: RootBenchmarkCpuRetirement

    @property
    def outcome(self) -> Literal["SUCCEEDED", "FAILED"]:
        # Existing classifier covers the same PID1 terminal fields on both devices.
        # It does not read a GPU or attest any physical ownership.
        return gpu_unit_terminal_outcome(self.retirement.original_terminal)


class FixedRootBenchmarkCpuDriver:
    """Trusted root composition must supply an admitted and root-prepared execution.

    CPU has no independent GPU resource socket. Its native model still waits for
    the actual workflow owner's peer-fenced checkpoint/authorization channel. Root
    success is not that authority, a complete numerical result or publication.
    """

    def __init__(
        self,
        invocation: BenchmarkWorkerInvocation,
        environment: PreparedBenchmarkEnvironment,
        *,
        backend: NativeEmbeddingBackendPins,
    ) -> None:
        require_root_benchmark_control()
        checked = parse_embedding_device_benchmark_bytes(
            embedding_device_benchmark_bytes(invocation)
        )
        _require(
            isinstance(checked, BenchmarkWorkerInvocation)
            and checked.device == "CPU"
            and type(environment) is PreparedBenchmarkEnvironment
            and environment.execution_id == checked.execution_id
            and environment.job_id == checked.job_id,
            "IDENTITY_INVALID",
        )
        assert isinstance(checked, BenchmarkWorkerInvocation)
        self._invocation, self._environment, self._backend = checked, environment, backend
        self._units = FixedRootBenchmarkUnits("CPU", checked.execution_id)
        owner = pwd.getpwnam("eom-workflow-runner")
        _require(owner.pw_uid > 0 and owner.pw_gid > 0, "OWNER_INVALID")
        self._owner = (owner.pw_uid, owner.pw_gid)
        self._used = False
        now = time.monotonic_ns()
        _require(now < environment.expires_ns <= now + 180 * 10**9, "EXPIRED")
        self._fence()

    def _fence(self) -> None:
        require_root_benchmark_control()
        _require(time.monotonic_ns() < self._environment.expires_ns, "EXPIRED")
        uid, gid = self._owner
        _require(
            benchmark_owner_start_ticks(self._environment.owner_pid, uid=uid, gid=gid)
            == self._environment.owner_start_ticks,
            "OWNER_CHANGED",
        )

    def _wait_terminal(self) -> CpuUnitObservation:
        original_invocation: str | None = None
        deadline = self._environment.expires_ns + 15 * 10**9
        while True:
            require_root_benchmark_control()
            _require(time.monotonic_ns() < deadline, "TERMINATION_UNCERTAIN")
            current = self._units.observe()
            if current.invocation_id:
                if original_invocation is None:
                    original_invocation = current.invocation_id
                _require(current.invocation_id == original_invocation, "UNIT_CHANGED")
            elif original_invocation is not None:
                raise ValueError("BENCHMARK_CPU_DRIVER_UNIT_CHANGED")
            try:
                gpu_unit_terminal_outcome(current)
            except ValueError:
                # Observe this exact handle; admission expiry/owner loss is never
                # permission to restart or to assume PID1/process cleanup happened.
                time.sleep(min(0.1, max(0.0, (deadline - time.monotonic_ns()) / 10**9)))
                continue
            return current

    def _save(
        self,
        directory: int,
        name: Literal["intent.json", "result.json"],
        observation: CpuUnitObservation | RootBenchmarkCpuRetirement,
    ) -> None:
        write_unit_effect_record(
            directory,
            name,
            canonical_json_bytes(
                {
                    "event": "BENCHMARK_CPU_RETIREMENT_INTENT"
                    if name == "intent.json"
                    else "BENCHMARK_CPU_RETIRED_NOT_ADMITTED",
                    "execution_id": self._invocation.execution_id,
                    "job_id": self._invocation.job_id,
                    "invocation_sha256": self._invocation.invocation_sha256,
                    "observation": TypeAdapter(type(observation)).dump_python(
                        observation, mode="json"
                    ),
                    "admission_granted": False,
                }
            ),
        )

    def _retire(self, original: CpuUnitObservation) -> RootBenchmarkCpuRetirement:
        require_root_benchmark_control()
        outcome = gpu_unit_terminal_outcome(original)
        captured = capture_prepared_benchmark_environment(
            self._invocation,
            self._environment,
            backend=self._backend,
        )
        installed = self._units.capture_installed()

        def recheck() -> None:
            _require(self._units.observe() == original, "UNIT_CHANGED")
            require_empty_native_cpu_cgroup(self._units.service)
            captured.assert_unchanged()
            installed.assert_unchanged()

        recheck()
        # An existing partial intent is uncertainty, never permission to stop/reset again.
        directory = reserve_unit_effect_phase(
            BENCHMARK_LIFETIME_ROOT, self._units.service, original.invocation_id, "retirement"
        )
        try:
            self._save(directory, "intent.json", original)
            recheck()
            self._units.retire_cpu_service(outcome)
            stopped = observe_stopped_gpu_unit(
                self._units.service,
                template=self._units.template,
                invocation=original.invocation_id,
            )
            _require(stopped.stored_descriptors == 0, "STORED_DESCRIPTORS_UNCERTAIN")
            require_empty_native_cpu_cgroup(self._units.service)
            captured.assert_unchanged()
            installed.assert_unchanged()
            _require(
                observe_stopped_gpu_unit(
                    self._units.service,
                    template=self._units.template,
                    invocation=original.invocation_id,
                )
                == stopped,
                "UNIT_CHANGED",
            )
            retirement = RootBenchmarkCpuRetirement(
                original,
                stopped,
                datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            )
            self._save(directory, "result.json", retirement)
            return retirement
        finally:
            os.close(directory)

    def run(self) -> RootBenchmarkCpuLaunch:
        _require(not self._used, "ALREADY_USED")
        self._used = True
        self._fence()
        captured = capture_prepared_benchmark_environment(
            self._invocation,
            self._environment,
            backend=self._backend,
        )
        installed = self._units.capture_installed()
        self._units.require_socket_state(active=False)
        _require(self._units.observe().fresh, "UNIT_NOT_FRESH")
        require_empty_native_cpu_cgroup(self._units.service)
        try:
            (BENCHMARK_HANDOFF_ROOT / self._invocation.execution_id / "control.sock").lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("BENCHMARK_CPU_DRIVER_SOCKET_ALREADY_EXISTS")
        captured.assert_unchanged()
        installed.assert_unchanged()
        self._fence()
        started_ns = time.monotonic_ns()
        self._units.start_socket()
        self._units.require_socket_state(active=True)
        self._fence()
        self._units.start_service()
        original = self._wait_terminal()
        retirement = self._retire(original)
        self._units.stop_socket()
        self._units.require_socket_state(active=False)
        require_empty_native_cpu_cgroup(self._units.service)
        return RootBenchmarkCpuLaunch(
            self._invocation.execution_id,
            self._invocation.job_id,
            self._invocation.invocation_sha256,
            started_ns,
            time.monotonic_ns(),
            retirement,
        )
