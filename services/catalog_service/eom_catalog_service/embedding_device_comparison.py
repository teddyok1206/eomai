"""Pure fixed-recipe performance gate, not benchmark execution or device activation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Literal


def _checked_times(values: tuple[int, ...], count: int) -> None:
    if (
        not isinstance(values, tuple)
        or len(values) != count
        or any(type(value) is not int or not 1 <= value <= 10**12 for value in values)
    ):
        raise ValueError("EMBEDDING_BENCHMARK_TIMING_INVALID")


@dataclass(frozen=True, slots=True)
class EmbeddingDeviceTimings:
    """Owner-observed microseconds for the exact internal recipe; no authority or hashes."""

    device: Literal["CPU", "CUDA"]
    cold_end_to_end_us: tuple[int, ...]
    warm_batch_encode_us: tuple[int, ...]
    query_encode_us: tuple[tuple[int, ...], tuple[int, ...]]
    query_end_to_end_us: tuple[tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        if self.device not in ("CPU", "CUDA"):
            raise ValueError("EMBEDDING_BENCHMARK_DEVICE_INVALID")
        _checked_times(self.cold_end_to_end_us, 3)
        _checked_times(self.warm_batch_encode_us, 5)
        for groups in (self.query_encode_us, self.query_end_to_end_us):
            if not isinstance(groups, tuple) or len(groups) != 2:
                raise ValueError("EMBEDDING_BENCHMARK_TIMING_INVALID")
            for times in groups:
                _checked_times(times, 5)


@dataclass(frozen=True, slots=True)
class EmbeddingDeviceTimingSummary:
    cold_median_us: int
    cold_max_us: int
    warm_median_us: int
    warm_max_us: int
    query_encode_median_us: tuple[int, int]
    query_encode_max_us: tuple[int, int]
    query_end_to_end_median_us: tuple[int, int]
    query_end_to_end_max_us: tuple[int, int]


@dataclass(frozen=True, slots=True)
class EmbeddingPerformanceDecision:
    """Performance only: correctness, payload, lease, isolation and activation are separate."""

    verdict: Literal["CUDA_PERFORMANCE_SUPERIOR", "KEEP_CPU"]
    reasons: tuple[str, ...]
    cpu: EmbeddingDeviceTimingSummary
    cuda: EmbeddingDeviceTimingSummary


def _summary(value: EmbeddingDeviceTimings) -> EmbeddingDeviceTimingSummary:
    # Odd bounded counts preserve integer microseconds without average/ratio rounding.
    return EmbeddingDeviceTimingSummary(
        cold_median_us=int(median(value.cold_end_to_end_us)),
        cold_max_us=max(value.cold_end_to_end_us),
        warm_median_us=int(median(value.warm_batch_encode_us)),
        warm_max_us=max(value.warm_batch_encode_us),
        query_encode_median_us=(
            int(median(value.query_encode_us[0])),
            int(median(value.query_encode_us[1])),
        ),
        query_encode_max_us=(max(value.query_encode_us[0]), max(value.query_encode_us[1])),
        query_end_to_end_median_us=(
            int(median(value.query_end_to_end_us[0])),
            int(median(value.query_end_to_end_us[1])),
        ),
        query_end_to_end_max_us=(
            max(value.query_end_to_end_us[0]),
            max(value.query_end_to_end_us[1]),
        ),
    )


def compare_embedding_device_performance(
    cpu: EmbeddingDeviceTimings, cuda: EmbeddingDeviceTimings
) -> EmbeddingPerformanceDecision:
    """Evaluate every predeclared gate; never choose runtime, change policy or retry work."""
    if not isinstance(cpu, EmbeddingDeviceTimings) or not isinstance(cuda, EmbeddingDeviceTimings):
        raise ValueError("EMBEDDING_BENCHMARK_TIMING_INVALID")
    # Revalidate caller values even after an unsafe dataclass construction/mutation bypass.
    cpu.__post_init__()
    cuda.__post_init__()
    if cpu.device != "CPU" or cuda.device != "CUDA":
        raise ValueError("EMBEDDING_BENCHMARK_DEVICE_INVALID")
    first, second = _summary(cpu), _summary(cuda)
    reasons: list[str] = []
    if second.warm_median_us * 100 > first.warm_median_us * 80:
        reasons.append("WARM_MEDIAN_NOT_SUPERIOR")
    if second.cold_median_us * 100 > first.cold_median_us * 90:
        reasons.append("COLD_MEDIAN_NOT_SUPERIOR")
    if second.cold_max_us * 100 > first.cold_max_us * 120:
        reasons.append("COLD_MAX_REGRESSION")
    for ordinal in range(2):
        if second.query_encode_median_us[ordinal] * 100 > (
            first.query_encode_median_us[ordinal] * 110
        ):
            reasons.append(f"QUERY_{ordinal + 1}_ENCODE_REGRESSION")
        if second.query_end_to_end_median_us[ordinal] * 100 > (
            first.query_end_to_end_median_us[ordinal] * 110
        ):
            reasons.append(f"QUERY_{ordinal + 1}_END_TO_END_REGRESSION")
    return EmbeddingPerformanceDecision(
        verdict="KEEP_CPU" if reasons else "CUDA_PERFORMANCE_SUPERIOR",
        reasons=tuple(reasons),
        cpu=first,
        cuda=second,
    )
