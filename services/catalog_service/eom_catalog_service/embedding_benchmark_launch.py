"""Shared fixed CPU/CUDA CLI pins and PID1 listener ownership, never device selection."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchPins:
    execution_id: str
    invocation_raw_sha256: str
    owner_pid: int
    expires_ns: int
    backend: NativeEmbeddingBackendPins

    def __post_init__(self) -> None:
        if (
            type(self.execution_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", self.execution_id, re.ASCII) is None
            or type(self.invocation_raw_sha256) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.invocation_raw_sha256, re.ASCII) is None
            or type(self.owner_pid) is not int
            or not 0 < self.owner_pid <= 2**31 - 1
            or type(self.expires_ns) is not int
            or not 0 < self.expires_ns < 10**19
            or type(self.backend) is not NativeEmbeddingBackendPins
        ):
            raise ValueError("BENCHMARK_OWNER_PINS_INVALID")
        self.backend.__post_init__()


def parse_benchmark_launch_pins(arguments: tuple[str, ...]) -> BenchmarkLaunchPins:
    if type(arguments) is not tuple or len(arguments) != 9:
        raise ValueError("BENCHMARK_OWNER_PINS_INVALID")
    execution, raw_hash, pid, expires, *backend = arguments
    for value, pattern in (
        (execution, r"[0-9a-f]{32}"),
        (raw_hash, r"sha256:[0-9a-f]{64}"),
        (pid, r"[1-9][0-9]{0,9}"),
        (expires, r"[1-9][0-9]{0,18}"),
    ):
        if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
            raise ValueError("BENCHMARK_OWNER_PINS_INVALID")
    return BenchmarkLaunchPins(
        execution, raw_hash, int(pid), int(expires), NativeEmbeddingBackendPins(*backend)
    )


@contextmanager
def benchmark_socket_activation(pins: BenchmarkLaunchPins) -> Iterator[None]:
    if type(pins) is not BenchmarkLaunchPins:
        raise ValueError("BENCHMARK_ACTIVATION_INVALID")
    pins.__post_init__()
    now = time.monotonic_ns()
    if not now < pins.expires_ns <= now + 180 * 10**9 or (
        os.environ.get("LISTEN_PID") != str(os.getpid())
        or os.environ.get("LISTEN_FDS") != "1"
        or os.environ.get("LISTEN_FDNAMES") != "benchmark-control"
    ):
        raise ValueError("BENCHMARK_ACTIVATION_INVALID")
    try:
        yield
    finally:
        os.close(3)
