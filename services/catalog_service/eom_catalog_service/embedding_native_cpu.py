"""Fixed CPU leaf composition; PID1 pins installation, Orchestrator owns all authority."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from eom_catalog_service.embedding_native_entrypoint import (
    run_native_embedding_index,
    run_native_embedding_reference_query,
)

if TYPE_CHECKING:
    from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend


@dataclass(frozen=True, slots=True)
class _OwnerPins:
    configuration_id: str
    configuration_revision_id: str
    configuration_sha256: str
    configuration_raw_sha256: str
    receipt_raw_sha256: str


def _owner_arguments(arguments: tuple[str, ...]) -> tuple[Literal["INDEX", "QUERY"], _OwnerPins]:
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
    patterns = (
        r"embeddingnativeconfig_[0-9a-f]{32}",
        r"embeddingnativeconfigrev_[0-9a-f]{32}",
        r"sha256:[0-9a-f]{64}",
        r"sha256:[0-9a-f]{64}",
        r"sha256:[0-9a-f]{64}",
    )
    if any(
        type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None
        for value, pattern in zip(values, patterns, strict=True)
    ):
        raise ValueError("NATIVE_CPU_OWNER_PINS_INVALID")
    return selected, _OwnerPins(*values)


@contextmanager
def _backend_scope(pins: _OwnerPins) -> Iterator[NativeEmbeddingBackend]:
    # Called only after the stdlib identity guard and complete descriptor/input validation.
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )

    from eom_catalog_service.embedding_native_installation_admission import (
        ProtectedNativeEmbeddingInstallationAdmission,
    )

    configuration = RootLocalNativeConfigurationPin(
        configuration_id=pins.configuration_id,
        configuration_revision_id=pins.configuration_revision_id,
        configuration_sha256=pins.configuration_sha256,
        configuration_raw_sha256=pins.configuration_raw_sha256,
    )
    with ProtectedNativeEmbeddingInstallationAdmission(
        configuration, expected_receipt_raw_sha256=pins.receipt_raw_sha256
    ) as admission:
        from eom_catalog_service.embedding_native_factory import native_embedding_backend_scope

        scope = native_embedding_backend_scope(
            profile="CPU_INDEX_FP32",
            configuration_id=pins.configuration_id,
            configuration_revision_id=pins.configuration_revision_id,
            configuration_raw_sha256=pins.configuration_raw_sha256,
            admission=admission,
        )
        with scope() as backend:
            yield backend


def main() -> int:
    try:
        purpose, pins = _owner_arguments(tuple(sys.argv[1:]))
        run = (
            run_native_embedding_index
            if purpose == "INDEX"
            else run_native_embedding_reference_query
        )
        run(profile="CPU_INDEX_FP32", backend_scope=lambda: _backend_scope(pins))
        return 0
    except Exception:
        # PID1/owner observes the failed invocation; never corrupt JSON/binary with diagnostics.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
