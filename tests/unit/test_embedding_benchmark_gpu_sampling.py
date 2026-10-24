"""Real bounded scheduling with synthetic observations; no root/GPU/model acceptance."""

import threading
import time
from dataclasses import replace

import pytest
from eom_catalog_service import embedding_benchmark_gpu_sampling as module
from eom_catalog_service.embedding_benchmark_gpu_observation import BenchmarkGpuObservedPeaks

from tests.unit.embedding_device_benchmark_fixtures import resources
from tests.unit.test_embedding_benchmark_channel import local_resources


class SyntheticObserver:
    def __init__(self, *, fail=False):
        self.thread = threading.get_ident()
        self.fail = fail
        self.count = 1
        self.times = [time.monotonic_ns()]
        self.state = "OPEN"
        self.finalized = 0

    def sample(self):
        assert threading.get_ident() == self.thread
        if self.fail:
            raise ValueError("SYNTHETIC_SAMPLING_DENIED")
        self.count += 1
        self.times.append(time.monotonic_ns())

    def observed_peaks(self):
        assert threading.get_ident() == self.thread
        return BenchmarkGpuObservedPeaks(
            self.state,
            self.count,
            self.times[0],
            self.times[-1],
            max((b - a for a, b in zip(self.times, self.times[1:], strict=False)), default=0),
            123,
            456,
            0,
        )

    def finalize(self, local):
        assert threading.get_ident() == self.thread
        assert local == local_resources(2)
        self.sample()
        self.finalized += 1
        self.state = "FROZEN"
        return resources(2)


@pytest.fixture
def fast_period(monkeypatch):
    monkeypatch.setattr(module, "_PERIOD_SECONDS", 0.02)


def test_blocking_control_ack_work_does_not_block_original_sampling_window(fast_period):
    made = []

    def factory():
        observer = SyntheticObserver()
        made.append(observer)
        return observer

    sampler = module.OwnedBenchmarkGpuSampler(factory)
    try:
        baseline = sampler.observed_peaks()
        time.sleep(0.2)  # Simulates synchronous main-thread ACK/ready revalidation.
        sampler.check_current()
        peaks = sampler.observed_peaks()
        assert peaks.observation_count >= 5
        assert peaks.first_observed_ns == baseline.first_observed_ns
        assert peaks.maximum_gap_ns < 150_000_000
        assert made[0].thread != threading.get_ident()
        assert sampler.finalize(local_resources(2)) == resources(2)
        assert sampler.observed_peaks().state == "FROZEN"
        with pytest.raises(ValueError):
            sampler.finalize(local_resources(2))
        assert made[0].finalized == 1
    finally:
        sampler.close()
    assert not sampler._thread.is_alive()


def test_sampler_error_is_not_zero_or_retried_resource_success(fast_period):
    observer = []

    def factory():
        result = SyntheticObserver(fail=True)
        observer.append(result)
        return result

    sampler = module.OwnedBenchmarkGpuSampler(factory)
    try:
        assert sampler._done.wait(timeout=1)
        with pytest.raises(ValueError, match="SAMPLER_FAILED"):
            sampler.check_current()
        with pytest.raises(ValueError, match="SAMPLER_FAILED"):
            sampler.finalize(local_resources(2))
        assert observer[0].finalized == 0
    finally:
        sampler.close()


def test_initialization_failure_has_no_leaked_reader_thread():
    before = {t.ident for t in threading.enumerate()}

    def denied():
        raise ValueError("SYNTHETIC_BASELINE_DENIED")

    with pytest.raises(ValueError, match="SAMPLER_FAILED"):
        module.OwnedBenchmarkGpuSampler(denied)
    assert not [
        t
        for t in threading.enumerate()
        if t.name == "eom-benchmark-gpu-observer" and t.ident not in before
    ]


def test_stale_snapshot_and_close_remain_fail_closed():
    sampler = module.OwnedBenchmarkGpuSampler(SyntheticObserver)
    try:
        with sampler._lock:
            sampler._peaks = replace(sampler._peaks, last_observed_ns=1)
        with pytest.raises(ValueError, match="SAMPLER_STALE"):
            sampler.check_current()
    finally:
        sampler.close()
    sampler.close()  # Idempotent transport cleanup, not another GPU effect.
    with pytest.raises(ValueError, match="SAMPLER_CLOSED"):
        sampler.check_current()
