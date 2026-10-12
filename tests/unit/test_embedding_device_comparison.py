"""Synthetic integer timing values only; no benchmark, model, CUDA or activation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest
from eom_catalog_service.embedding_device_comparison import (
    EmbeddingDeviceTimings,
    compare_embedding_device_performance,
)


def timings(device: Any, **changes: Any) -> EmbeddingDeviceTimings:
    values: dict[str, Any] = {
        "device": device,
        "cold_end_to_end_us": (100, 100, 100),
        "warm_batch_encode_us": (100, 100, 100, 100, 100),
        "query_encode_us": ((100,) * 5, (100,) * 5),
        "query_end_to_end_us": ((100,) * 5, (100,) * 5),
    }
    return EmbeddingDeviceTimings(**(values | changes))


def superior(**changes: Any) -> EmbeddingDeviceTimings:
    return timings(
        "CUDA",
        **(
            {
                "cold_end_to_end_us": (90, 90, 120),
                "warm_batch_encode_us": (80,) * 5,
                "query_encode_us": ((110,) * 5, (110,) * 5),
                "query_end_to_end_us": ((110,) * 5, (110,) * 5),
            }
            | changes
        ),
    )


def test_exact_inclusive_boundaries_and_actual_maxima_are_preserved() -> None:
    result = compare_embedding_device_performance(timings("CPU"), superior())
    assert result.verdict == "CUDA_PERFORMANCE_SUPERIOR" and result.reasons == ()
    assert result.cuda.cold_median_us == 90 and result.cuda.cold_max_us == 120
    assert result.cuda.warm_median_us == result.cuda.warm_max_us == 80
    assert result.cuda.query_encode_median_us == result.cuda.query_encode_max_us == (110, 110)


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ({"warm_batch_encode_us": (81,) * 5}, "WARM_MEDIAN_NOT_SUPERIOR"),
        ({"cold_end_to_end_us": (91, 91, 100)}, "COLD_MEDIAN_NOT_SUPERIOR"),
        ({"cold_end_to_end_us": (80, 80, 121)}, "COLD_MAX_REGRESSION"),
        ({"query_encode_us": ((111,) * 5, (10,) * 5)}, "QUERY_1_ENCODE_REGRESSION"),
        ({"query_encode_us": ((10,) * 5, (111,) * 5)}, "QUERY_2_ENCODE_REGRESSION"),
        (
            {"query_end_to_end_us": ((111,) * 5, (10,) * 5)},
            "QUERY_1_END_TO_END_REGRESSION",
        ),
        (
            {"query_end_to_end_us": ((10,) * 5, (111,) * 5)},
            "QUERY_2_END_TO_END_REGRESSION",
        ),
    ),
)
def test_each_gate_fails_without_masking_another_query(change: dict[str, Any], reason: str) -> None:
    result = compare_embedding_device_performance(timings("CPU"), superior(**change))
    assert result.verdict == "KEEP_CPU" and result.reasons == (reason,)


def test_warm_improvement_does_not_hide_cold_query_and_tail_failures() -> None:
    result = compare_embedding_device_performance(
        timings("CPU"),
        superior(
            cold_end_to_end_us=(101, 101, 200),
            query_encode_us=((111,) * 5, (111,) * 5),
            query_end_to_end_us=((111,) * 5, (111,) * 5),
        ),
    )
    assert result.verdict == "KEEP_CPU"
    assert result.reasons == (
        "COLD_MEDIAN_NOT_SUPERIOR",
        "COLD_MAX_REGRESSION",
        "QUERY_1_ENCODE_REGRESSION",
        "QUERY_1_END_TO_END_REGRESSION",
        "QUERY_2_ENCODE_REGRESSION",
        "QUERY_2_END_TO_END_REGRESSION",
    )


def test_no_float_ratio_rounding_can_turn_a_tiny_regression_into_pass() -> None:
    cpu = timings("CPU", warm_batch_encode_us=(999_999_995,) * 5)
    cuda = superior(warm_batch_encode_us=(799_999_997,) * 5)
    assert compare_embedding_device_performance(cpu, cuda).reasons == ("WARM_MEDIAN_NOT_SUPERIOR",)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1", None, 10**12 + 1])
def test_wrong_integer_and_time_bounds_are_rejected(value: Any) -> None:
    with pytest.raises(ValueError, match="TIMING_INVALID"):
        timings("CPU", cold_end_to_end_us=(value, 100, 100))


@pytest.mark.parametrize(
    "change",
    [
        {"cold_end_to_end_us": (100, 100)},
        {"warm_batch_encode_us": (100,) * 4},
        {"warm_batch_encode_us": [100] * 5},
        {"query_encode_us": ((100,) * 5,)},
        {"query_encode_us": [(100,) * 5, (100,) * 5]},
        {"query_end_to_end_us": ((100,) * 5, (100,) * 4)},
    ],
)
def test_recipe_counts_are_fixed_not_caller_selected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="TIMING_INVALID"):
        timings("CPU", **change)


def test_cpu_cuda_labels_cannot_be_swapped_or_implicitly_defaulted() -> None:
    with pytest.raises(ValueError, match="DEVICE_INVALID"):
        timings("AUTO")
    with pytest.raises(ValueError, match="DEVICE_INVALID"):
        compare_embedding_device_performance(timings("CUDA"), timings("CPU"))


def test_frozen_values_and_bypass_revalidation() -> None:
    cpu, cuda = timings("CPU"), superior()
    with pytest.raises(FrozenInstanceError):
        cpu.device = "CUDA"  # type: ignore[misc]
    changed = replace(cpu)
    object.__setattr__(changed, "warm_batch_encode_us", (True,) * 5)
    with pytest.raises(ValueError, match="TIMING_INVALID"):
        compare_embedding_device_performance(changed, cuda)
