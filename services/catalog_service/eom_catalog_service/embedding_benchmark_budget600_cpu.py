"""Dedicated released-policy1.1 CPU entry; no implicit change to the legacy entry."""

from __future__ import annotations

import sys
import time

from eom_catalog_service.embedding_benchmark_launch import parse_benchmark_launch_pins
from eom_catalog_service.embedding_native_entrypoint import (
    discard_native_embedding_diagnostics,
    require_native_embedding_identity,
)


def main() -> int:
    started = time.perf_counter_ns()
    try:
        pins = parse_benchmark_launch_pins(tuple(sys.argv[1:]))
        with discard_native_embedding_diagnostics():
            require_native_embedding_identity("CPU_INDEX_FP32")
            from eom_catalog_service.embedding_benchmark_budget_entrypoint import (
                execute_budget600_benchmark,
            )
            from eom_catalog_service.embedding_benchmark_cpu import _run

            return execute_budget600_benchmark(
                pins, started, profile="CPU_INDEX_FP32", execute=_run
            )
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
