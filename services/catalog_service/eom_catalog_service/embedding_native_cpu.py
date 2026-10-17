"""Fixed CPU leaf composition; PID1 pins installation, Orchestrator owns all authority."""

from __future__ import annotations

import sys
from typing import Literal

from eom_catalog_service.embedding_native_cpu_backend import (
    NativeCpuBackendPins,
    native_cpu_backend_scope,
)
from eom_catalog_service.embedding_native_entrypoint import (
    run_native_embedding_index,
    run_native_embedding_reference_query,
)


def _owner_arguments(
    arguments: tuple[str, ...],
) -> tuple[Literal["INDEX", "QUERY"], NativeCpuBackendPins]:
    """These arguments come from a protected fixed unit, never from worker request JSON."""
    if type(arguments) is not tuple or len(arguments) != 6:
        raise ValueError("NATIVE_CPU_OWNER_PINS_INVALID")
    purpose, *values = arguments
    if purpose == "INDEX":
        selected: Literal["INDEX", "QUERY"] = "INDEX"
    elif purpose == "QUERY":
        selected = "QUERY"
    else:
        raise ValueError("NATIVE_CPU_PURPOSE_INVALID")
    return selected, NativeCpuBackendPins(*values)


def main() -> int:
    try:
        purpose, pins = _owner_arguments(tuple(sys.argv[1:]))
        run = (
            run_native_embedding_index
            if purpose == "INDEX"
            else run_native_embedding_reference_query
        )
        run(profile="CPU_INDEX_FP32", backend_scope=lambda: native_cpu_backend_scope(pins))
        return 0
    except Exception:
        # PID1/owner observes the failed invocation; never corrupt JSON/binary with diagnostics.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
