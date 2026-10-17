"""Real owner resource finalization with synthetic root/kernel/driver ports, no GPU effect."""

import os
import subprocess
import sys
from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkResourceEvidence
from eom_catalog_service import embedding_benchmark_cuda_observation as ready_owner
from eom_catalog_service import embedding_benchmark_gpu_observation as owner
from eom_catalog_service.embedding_cuda_probe_gpu_clients import (
    CudaGpuMemorySnapshot,
    CudaProcessMemory,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_channel import local_resources
from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_observation import observe
from tests.unit.test_embedding_native_probe_observation import ledger as ledger

MIB = 1024**2


@pytest.fixture
def observation(benchmark, monkeypatch):
    state = benchmark
    ready = observe(state)
    state.observed_ready = ready
    state.now_ns = owner.time.monotonic_ns()
    state.memory = CudaGpuMemorySnapshot(3 * MIB - 1, 16304 * MIB - 1, ())
    state.memory_calls = 0

    def memory(device):
        assert device == ready.device
        state.memory_calls += 1
        if state.fault == "query":
            raise ValueError("synthetic uncertain memory query")
        if state.fault == "late_pid":
            state.start += 1
        return state.memory

    for name in (
        "inspect_cpu_unit",
        "read_live_runtime_os_file",
        "root_owned_unit_processes",
        "observe_gpu_unit_policy",
        "observe_benchmark_cuda_ready_resources",
        "benchmark_owner_start_ticks",
    ):
        monkeypatch.setattr(owner, name, getattr(ready_owner, name))
    monkeypatch.setattr(owner, "observe_cuda_gpu_memory", memory)
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: state.now_ns)
    state.monitor = owner.BenchmarkGpuMemoryObserver(
        ready,
        state.invocation,
        state.environment,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )
    body = local_resources(2).model_dump(mode="json", exclude={"resource_sha256"})
    body["invocation_sha256"] = state.invocation.invocation_sha256
    state.local = BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
    return state


def test_baseline_then_actual_peaks_and_overlap_finalize_only_owner_fields(observation):
    state = observation
    assert state.monitor.observed_peaks().observation_count == 1
    state.memory = CudaGpuMemorySnapshot(
        1001 * MIB - 1, 16304 * MIB - 1, (CudaProcessMemory(123, 901 * MIB - 1),)
    )
    state.now_ns += 200_000_000
    state.monitor.sample()
    state.memory = CudaGpuMemorySnapshot(
        801 * MIB - 1,
        16304 * MIB - 1,
        (CudaProcessMemory(123, 501 * MIB - 1), CudaProcessMemory(999, 101 * MIB - 1)),
    )
    state.now_ns += 200_000_000
    result = state.monitor.finalize(state.local)
    assert result.owner_observation_count == 3 and result.other_consumer_overlap_count == 1
    assert result.peak_whole_process_gpu_bytes == 901 * MIB - 1
    assert result.peak_whole_device_gpu_bytes == 1001 * MIB - 1
    assert result.peak_allocated_gpu_bytes == state.local.peak_allocated_gpu_bytes
    assert result.peak_reserved_gpu_bytes == state.local.peak_reserved_gpu_bytes
    assert result.peak_rss_bytes == state.local.peak_rss_bytes
    assert all(
        row.peak_whole_process_gpu_bytes == result.peak_whole_process_gpu_bytes
        for row in result.capacity_samples
    )
    report = state.monitor.observed_peaks()
    assert report.state == "FROZEN" and report.maximum_gap_ns == 200_000_000
    calls = state.memory_calls
    with pytest.raises(ValueError, match="NOT_OPEN"):
        state.monitor.finalize(state.local)
    assert state.memory_calls == calls and state.monitor.observed_peaks().state == "FROZEN"


@pytest.mark.parametrize(
    "fault",
    ("query", "late_pid", "owner", "files", "child", "unit", "resource", "gap", "expired", "root"),
)
def test_unknown_scope_or_missing_sample_poisons_without_retry_or_zero_success(
    observation, monkeypatch, fault
):
    state = observation
    if fault in {"query", "late_pid"}:
        state.fault = fault
    elif fault == "owner":
        state.owner_birth += 1
    elif fault == "files":
        state.drift = True
    elif fault == "child":
        state.pids = (123, 124)
    elif fault == "unit":
        state.unit = replace(state.unit, invocation_id="a" * 32)
    elif fault == "resource":
        state.fault = "late_resources"
    elif fault == "gap":
        state.now_ns += owner.MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS + 1
    elif fault == "expired":
        state.now_ns = state.environment.expires_ns
    else:
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError):
        state.monitor.sample()
    monkeypatch.setattr(owner.os, "getresuid", lambda: (0,) * 3)
    assert state.monitor.observed_peaks().state == "POISONED"
    state.fault, state.drift, state.pids, state.owner_birth = None, False, (123,), 4321
    state.unit, state.start = state.observed_ready.unit, state.observed_ready.start_time_ticks
    state.now_ns = state.environment.expires_ns - 1
    calls = state.memory_calls
    with pytest.raises(ValueError, match="NOT_OPEN"):
        state.monitor.finalize(state.local)
    assert state.memory_calls == calls


def test_above_policy_peaks_remain_evidence_not_clamped_to_eight_gib(observation):
    state = observation
    state.memory = CudaGpuMemorySnapshot(
        9001 * MIB - 1, 16304 * MIB - 1, (CudaProcessMemory(123, 8193 * MIB - 1),)
    )
    result = state.monitor.finalize(state.local)
    assert result.peak_whole_process_gpu_bytes > 8 * 1024**3
    assert result.peak_whole_device_gpu_bytes > 8 * 1024**3


def test_wrong_local_result_is_not_rewritten_or_observed_as_success(observation):
    state = observation
    body = state.local.model_dump(mode="json")
    body["invocation_sha256"] = "sha256:" + "a" * 64
    wrong = BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
    calls = state.memory_calls
    with pytest.raises(ValueError):
        state.monitor.finalize(wrong)
    assert state.memory_calls == calls and state.monitor.observed_peaks().state == "POISONED"


def test_fresh_nonroot_identity_cannot_start_sampler_or_query_gpu_memory():
    paths = os.environ["PYTHONPATH"].split(os.pathsep)
    code = """
import os,sys,subprocess
sys.path[:0]=sys.argv[1:]
from eom_catalog_service.embedding_benchmark_gpu_observation import BenchmarkGpuMemoryObserver
from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_gpu_memory
assert os.getresuid()!=(0,0,0)
def forbidden(*_a, **_kw): raise AssertionError('command before root guard')
subprocess.run=forbidden
for action,expected in (
 (lambda:BenchmarkGpuMemoryObserver(None,None,None,backend=None,inventory=None,host=None),
 'BENCHMARK_GPU_OBSERVATION_ROOT_REQUIRED'),
 (lambda:observe_cuda_gpu_memory(None),'CUDA_GPU_MEMORY_QUERY_UNAVAILABLE'),
):
 try:action()
 except ValueError as error: assert str(error)==expected,str(error)
 else:raise AssertionError('missing root refusal')
assert not {'torch','numpy','transformers','sentence_transformers'}.intersection(sys.modules)
"""
    result = subprocess.run(
        (sys.executable, "-I", "-B", "-c", code, *paths), capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode()
