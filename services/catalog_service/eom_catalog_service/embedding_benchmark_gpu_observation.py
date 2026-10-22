"""Independent root GPU counters for one admitted benchmark, not a launcher or grant."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    validate_benchmark_local_resources,
    validate_benchmark_resource_finalization,
)
from eom_identifiers import content_sha256
from eom_orchestrator.inference_transfer_cpu_systemd import inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_benchmark_cuda_observation import (
    CUDA_BENCHMARK_TEMPLATE as CUDA_BENCHMARK_TEMPLATE,
)
from eom_catalog_service.embedding_benchmark_cuda_observation import (
    BenchmarkCudaReadyObservation,
    capture_benchmark_cuda_pinned_files,
    observe_benchmark_cuda_ready,
    require_benchmark_cuda_observation_basis,
)
from eom_catalog_service.embedding_benchmark_handoff import (
    PreparedBenchmarkEnvironment,
    benchmark_owner_start_ticks,
)
from eom_catalog_service.embedding_cuda_probe_gpu_clients import (
    CudaGpuMemorySnapshot,
    observe_cuda_gpu_memory,
)
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    observe_benchmark_cuda_ready_resources,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_native_cuda_process_status,
)
from eom_catalog_service.gpu_unit_policy_observation import observe_gpu_unit_policy

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS = 2 * 10**9


class _State(StrEnum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    POISONED = "POISONED"


@dataclass(frozen=True, slots=True)
class BenchmarkGpuObservedPeaks:
    """Small audit value; observed maxima are conservative display bounds, not exact peaks."""

    state: str
    observation_count: int
    first_observed_ns: int
    last_observed_ns: int
    maximum_gap_ns: int
    peak_whole_process_gpu_bytes: int
    peak_whole_device_gpu_bytes: int
    other_consumer_overlap_count: int
    source: str = "NVIDIA_SMI_XML_V13_MIB_UPPER_BOUND/1.0"


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_GPU_OBSERVATION_" + suffix)


class BenchmarkGpuMemoryObserver:
    """Single root control-thread accumulator; never owns/releases the physical GPU lease.

    The actual root lifecycle owner must call sample periodically while the worker runs
    and finalize only at the existing resource exchange. This is not a background service,
    source/Job authorization, whole-invocation sampling claim or cleanup confirmation.
    """

    def __init__(
        self,
        ready: BenchmarkCudaReadyObservation,
        invocation: BenchmarkWorkerInvocation,
        environment: PreparedBenchmarkEnvironment,
        *,
        backend: NativeEmbeddingBackendPins,
        inventory: PrefixRuntimeInventory,
        host: ProtectedCudaEmbeddingHostClosure,
    ) -> None:
        _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
        _require(type(ready) is BenchmarkCudaReadyObservation, "IDENTITY_INVALID")
        _require(
            observe_benchmark_cuda_ready(
                invocation, environment, backend=backend, inventory=inventory, host=host
            )
            == ready,
            "IDENTITY_CHANGED",
        )
        captured = capture_benchmark_cuda_pinned_files(
            invocation, environment, backend=backend, inventory=inventory
        )
        self._unit = require_benchmark_cuda_observation_basis(ready, captured)
        self._ready, self._invocation, self._capture = ready, invocation, captured
        self._environment = environment
        self._inventory, self._host, self._expires_ns = inventory, host, environment.expires_ns
        self._thread = threading.get_ident()
        self._state = _State.OPEN
        self._count = self._first_ns = self._last_ns = self._maximum_gap_ns = 0
        self._last_query_started_ns = 0
        self._process_peak = self._device_peak = self._overlap_count = 0
        self.sample()  # Establish a pre-compute baseline before the caller may send root ACK.

    def observed_peaks(self) -> BenchmarkGpuObservedPeaks:
        _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
        _require(threading.get_ident() == self._thread, "CONTROL_THREAD_CHANGED")
        return BenchmarkGpuObservedPeaks(
            self._state.value,
            self._count,
            self._first_ns,
            self._last_ns,
            self._maximum_gap_ns,
            self._process_peak,
            self._device_peak,
            self._overlap_count,
        )

    def _current(self) -> None:
        _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
        _require(threading.get_ident() == self._thread, "CONTROL_THREAD_CHANGED")
        _require(self._state == _State.OPEN, "NOT_OPEN")
        _require(time.monotonic_ns() < self._expires_ns, "EXPIRED")
        ready, report = self._ready, self._capture.ready
        _require(
            benchmark_owner_start_ticks(
                self._capture.pins.owner_pid,
                uid=self._capture.owner_uid,
                gid=self._capture.owner_gid,
            )
            == self._environment.owner_start_ticks,
            "OWNER_CHANGED",
        )
        actual = inspect_cpu_unit(self._unit, template=self._capture.service_template)
        _require(
            actual.invocation_id == ready.unit.invocation_id
            and actual.main_pid == ready.pid
            and actual.status.exec_main_started_monotonic
            == ready.unit.status.exec_main_started_monotonic
            and actual.status.active_state == "activating"
            and actual.status.sub_state == "start"
            and actual.exited_monotonic == 0,
            "PROCESS_CHANGED",
        )
        path = Path("/proc") / str(ready.pid)
        raw = read_live_runtime_os_file(path / "stat", maximum=65536, owner_uid=report.worker_uid)
        _require(
            native_process_start_ticks(raw, ready.pid) == ready.start_time_ticks, "PROCESS_CHANGED"
        )
        status = read_live_runtime_os_file(
            path / "status", maximum=128 * 1024, owner_uid=report.worker_uid
        )
        require_native_cuda_process_status(
            status,
            uid=report.worker_uid,
            gid=report.worker_gid,
            lease_gid=report.supplementary_gids[0],
        )
        _require(root_owned_unit_processes(self._unit) == (ready.pid,), "PROCESS_CHANGED")
        _require(
            observe_gpu_unit_policy(self._unit, worker_account="eom-embedding-cuda")
            == ready.effective_policy_sha256,
            "POLICY_CHANGED",
        )
        _require(
            observe_benchmark_cuda_ready_resources(
                report, unit=self._unit, lease_gid=report.supplementary_gids[0]
            )
            == ready.resources,
            "RESOURCE_CHANGED",
        )
        self._capture.assert_current()

    def sample(self) -> CudaGpuMemorySnapshot:
        try:
            self._current()
            _require(self._count < 4096, "SAMPLE_LIMIT")
            began_ns = time.monotonic_ns()
            if self._last_query_started_ns:
                _require(
                    began_ns - self._last_query_started_ns <= MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS,
                    "SAMPLING_GAP",
                )
            observed = observe_cuda_gpu_memory(self._ready.device)
            ended_ns = time.monotonic_ns()
            _require(type(observed) is CudaGpuMemorySnapshot, "QUERY_RESULT_INVALID")
            self._current()
            own, overlap = 0, False
            for row in observed.processes:
                if row.pid == self._ready.pid:
                    own = row.used_bytes_upper_bound
                else:
                    overlap = True
            _require(ended_ns >= began_ns, "CLOCK_CHANGED")
            if self._last_query_started_ns:
                _require(began_ns >= self._last_ns, "CLOCK_CHANGED")
                gap_upper_bound = ended_ns - self._last_query_started_ns
                _require(gap_upper_bound <= MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS, "SAMPLING_GAP")
                self._maximum_gap_ns = max(self._maximum_gap_ns, gap_upper_bound)
            else:
                self._first_ns = began_ns
            self._last_ns = ended_ns
            self._last_query_started_ns = began_ns
            self._count += 1
            self._process_peak = max(self._process_peak, own)
            self._device_peak = max(self._device_peak, observed.device_used_bytes_upper_bound)
            self._overlap_count += int(overlap)
            return observed
        except BaseException:
            if self._state == _State.OPEN:
                self._state = _State.POISONED
            raise

    def finalize(self, local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
        try:
            self._current()
            validate_benchmark_local_resources(self._invocation, local)
            self.sample()
            self._inventory.assert_unchanged()
            self._host.assert_current()
            self._current()
            body = local.model_dump(mode="json", exclude={"resource_sha256"})
            body.update(
                peak_whole_process_gpu_bytes=self._process_peak,
                peak_whole_device_gpu_bytes=self._device_peak,
                owner_observation_count=self._count,
                other_consumer_overlap_count=self._overlap_count,
            )
            for capacity in body["capacity_samples"]:
                capacity["peak_whole_process_gpu_bytes"] = self._process_peak
            finalized = BenchmarkResourceEvidence.model_validate(
                body | {"resource_sha256": content_sha256(body)}
            )
            validate_benchmark_resource_finalization(self._invocation, local, finalized)
            self._state = _State.FROZEN
            return finalized
        except BaseException:
            if self._state == _State.OPEN:
                self._state = _State.POISONED
            raise
