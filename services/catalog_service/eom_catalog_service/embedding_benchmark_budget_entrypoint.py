"""Explicit bounded benchmark entry selection; numerical execution stays unchanged."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import benchmark_timeout_seconds

from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_socket_activation,
)
from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file


def execute_budget_benchmark(
    pins: BenchmarkLaunchPins,
    started_ns: int,
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
    timeout_seconds: Literal[600, 1200],
    execute: Callable[[BenchmarkLaunchPins, int], int],
) -> int:
    """Read and bind real protected invocation/unit before any model or GPU acquisition."""
    with BenchmarkWorkerLocalFiles(
        0,
        profile=profile,
        execution_id=pins.execution_id,
        invocation_raw_sha256=pins.invocation_raw_sha256,
    ) as files:
        invocation = files.read_invocation()
    expected_version = "embedding-device-benchmark-invocation/1.1"
    if timeout_seconds == 1200:
        expected_version = "embedding-device-benchmark-invocation/1.2"
    if invocation.schema_version != expected_version or (
        invocation.execution_id != pins.execution_id
        or benchmark_timeout_seconds(invocation.execution_policy) != timeout_seconds
    ):
        raise ValueError("BENCHMARK_BUDGET_ENTRY_SELECTION_INVALID")
    family = benchmark_unit_family(invocation.device, invocation.execution_policy)
    expected = family.service_template.replace("@.service", f"@{pins.execution_id}.service")
    cgroup = read_live_runtime_os_file(
        Path("/proc") / str(os.getpid()) / "cgroup", maximum=64 * 1024, owner_uid=os.geteuid()
    )
    if cgroup != f"0::/system.slice/{expected}\n".encode("ascii"):
        raise ValueError("BENCHMARK_BUDGET_ENTRY_UNIT_MISMATCH")
    with benchmark_socket_activation(pins, policy=invocation.execution_policy):
        return execute(pins, started_ns)


def execute_budget600_benchmark(
    pins: BenchmarkLaunchPins,
    started_ns: int,
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
    execute: Callable[[BenchmarkLaunchPins, int], int],
) -> int:
    """Preserve the released v1.1/600-second entry unchanged."""
    return execute_budget_benchmark(
        pins, started_ns, profile=profile, timeout_seconds=600, execute=execute
    )
