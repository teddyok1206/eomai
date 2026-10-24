"""One root observer thread: independent bounded sampling, never GPU/Job ownership."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from queue import Empty, Full, Queue

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkResourceEvidence

from eom_catalog_service.embedding_benchmark_gpu_observation import (
    MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS,
    BenchmarkGpuMemoryObserver,
    BenchmarkGpuObservedPeaks,
)

_PERIOD_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class _Finalization:
    local: BenchmarkResourceEvidence
    reply: Future[BenchmarkResourceEvidence]


class OwnedBenchmarkGpuSampler:
    """The observer is constructed, sampled and frozen on exactly one read-only thread."""

    def __init__(self, factory: Callable[[], BenchmarkGpuMemoryObserver]) -> None:
        self._lock = threading.Lock()
        self._ready, self._stop, self._done = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self._requests: Queue[_Finalization] = Queue(maxsize=1)
        self._peaks: BenchmarkGpuObservedPeaks | None = None
        self._error: BaseException | None = None
        self._closed = self._finalizing = False
        self._thread = threading.Thread(
            target=self._run, args=(factory,), name="eom-benchmark-gpu-observer", daemon=True
        )
        self._thread.start()
        try:
            if not self._ready.wait(timeout=20):
                raise ValueError("BENCHMARK_GPU_SAMPLER_INITIALIZATION_TIMEOUT")
            self.check_current()
        except BaseException:
            self.close()
            raise

    def _publish(self, observer: BenchmarkGpuMemoryObserver) -> None:
        value = observer.observed_peaks()
        with self._lock:
            self._peaks = value

    def _run(self, factory: Callable[[], BenchmarkGpuMemoryObserver]) -> None:
        pending: _Finalization | None = None
        try:
            observer = factory()  # Its constructor records the real pre-ACK baseline.
            self._publish(observer)
            self._ready.set()
            next_sample = time.monotonic() + _PERIOD_SECONDS
            while not self._stop.is_set():
                try:
                    pending = self._requests.get(timeout=max(0, next_sample - time.monotonic()))
                except Empty:
                    observer.sample()
                    self._publish(observer)
                    next_sample = time.monotonic() + _PERIOD_SECONDS
                    continue
                result = observer.finalize(pending.local)
                self._publish(observer)
                pending.reply.set_result(result)
                return
        except BaseException as error:
            with self._lock:
                self._error = error
            if pending is not None and not pending.reply.done():
                pending.reply.set_exception(error)
        finally:
            # A failed initialization/sample must also wake a finalization caller.
            try:
                queued = self._requests.get_nowait()
            except Empty:
                pass
            else:
                if not queued.reply.done():
                    queued.reply.set_exception(ValueError("BENCHMARK_GPU_SAMPLER_STOPPED"))
            self._ready.set()
            self._done.set()

    def observed_peaks(self) -> BenchmarkGpuObservedPeaks:
        with self._lock:
            error, peaks = self._error, self._peaks
        if error is not None:
            raise ValueError("BENCHMARK_GPU_SAMPLER_FAILED") from error
        if peaks is None:
            raise ValueError("BENCHMARK_GPU_SAMPLER_UNAVAILABLE")
        return peaks

    def check_current(self) -> None:
        with self._lock:
            closed = self._closed
        if closed:
            raise ValueError("BENCHMARK_GPU_SAMPLER_CLOSED")
        peaks = self.observed_peaks()
        if peaks.state != "OPEN" or self._done.is_set():
            raise ValueError("BENCHMARK_GPU_SAMPLER_NOT_OPEN")
        if (
            not 0
            <= time.monotonic_ns() - peaks.last_observed_ns
            <= MAX_BENCHMARK_GPU_OBSERVATION_GAP_NS
        ):
            raise ValueError("BENCHMARK_GPU_SAMPLER_STALE")

    def finalize(self, local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
        self.check_current()
        with self._lock:
            if self._finalizing or self._closed:
                raise ValueError("BENCHMARK_GPU_SAMPLER_ALREADY_FINALIZED")
            self._finalizing = True
        request = _Finalization(local, Future())
        try:
            self._requests.put_nowait(request)
        except Full:
            raise ValueError("BENCHMARK_GPU_SAMPLER_ALREADY_FINALIZED") from None
        if self._done.is_set():
            raise ValueError("BENCHMARK_GPU_SAMPLER_STOPPED")
        return request.reply.result(timeout=10)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._stop.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise ValueError("BENCHMARK_GPU_SAMPLER_TERMINATION_UNCERTAIN")
