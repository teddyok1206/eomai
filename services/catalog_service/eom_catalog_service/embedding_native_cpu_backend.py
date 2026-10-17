"""Shared fixed CPU backend composition; no process, source, Job or launch authority."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from eom_catalog_service.embedding_native_backend_pins import (
    NativeEmbeddingBackendPins as NativeCpuBackendPins,
)

__all__ = ("NativeCpuBackendPins", "native_cpu_backend_scope")

if TYPE_CHECKING:
    from eom_catalog_service.embedding_execution_ports import BenchmarkNativeEmbeddingBackend


@contextmanager
def native_cpu_backend_scope(
    pins: NativeCpuBackendPins,
) -> Iterator[BenchmarkNativeEmbeddingBackend]:
    """Called after the fixed identity/input guard; receipt parsing alone grants nothing."""
    if type(pins) is not NativeCpuBackendPins:
        raise ValueError("NATIVE_CPU_OWNER_PINS_INVALID")
    pins.__post_init__()
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
