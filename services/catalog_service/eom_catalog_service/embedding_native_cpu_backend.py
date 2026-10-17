"""Shared fixed CPU backend composition; no process, source, Job or launch authority."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_catalog_service.embedding_execution_ports import BenchmarkNativeEmbeddingBackend


@dataclass(frozen=True, slots=True)
class NativeCpuBackendPins:
    configuration_id: str
    configuration_revision_id: str
    configuration_sha256: str
    configuration_raw_sha256: str
    receipt_raw_sha256: str

    def __post_init__(self) -> None:
        for value, pattern in (
            (self.configuration_id, r"embeddingnativeconfig_[0-9a-f]{32}"),
            (self.configuration_revision_id, r"embeddingnativeconfigrev_[0-9a-f]{32}"),
            (self.configuration_sha256, r"sha256:[0-9a-f]{64}"),
            (self.configuration_raw_sha256, r"sha256:[0-9a-f]{64}"),
            (self.receipt_raw_sha256, r"sha256:[0-9a-f]{64}"),
        ):
            if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
                raise ValueError("NATIVE_CPU_OWNER_PINS_INVALID")


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
