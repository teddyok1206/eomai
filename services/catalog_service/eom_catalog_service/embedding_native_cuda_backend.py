"""Concrete CUDA receipt/device binding; no source, Job, root ACK or physical lease grant."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )

    from eom_catalog_service.embedding_cuda_probe_resource_files import OpenedCudaProbeDeviceAccess
    from eom_catalog_service.embedding_execution_ports import BenchmarkNativeEmbeddingBackend


@contextmanager
def native_cuda_backend_scope(
    configuration: RootLocalNativeConfigurationPin,
    *,
    receipt_raw_sha256: str,
    ownership: OpenedCudaProbeDeviceAccess,
) -> Iterator[BenchmarkNativeEmbeddingBackend]:
    """Borrow already root-ACKed physical ownership; never acquire/release or substitute it.

    The caller retains that ownership until after backend close and actual unit retirement.
    A successful installation probe is not a call to this compute composition.
    """
    require_native_embedding_identity("CUDA_INDEX_FP32")
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )

    from eom_catalog_service.embedding_cuda_probe_resource_files import OpenedCudaProbeDeviceAccess
    from eom_catalog_service.embedding_native_installation_admission import (
        ProtectedNativeCudaEmbeddingInstallationAdmission,
    )

    if (
        type(configuration) is not RootLocalNativeConfigurationPin
        or type(ownership) is not OpenedCudaProbeDeviceAccess
        or type(receipt_raw_sha256) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", receipt_raw_sha256, re.ASCII) is None
    ):
        raise ValueError("NATIVE_CUDA_BACKEND_CAPTURE_INVALID")
    configuration = RootLocalNativeConfigurationPin.model_validate(
        configuration.model_dump(mode="python")
    )
    ownership.assert_owned()
    try:
        with ProtectedNativeCudaEmbeddingInstallationAdmission(
            configuration, expected_receipt_raw_sha256=receipt_raw_sha256
        ) as admission:
            ownership.assert_owned()
            from eom_catalog_service.embedding_native_factory import native_embedding_backend_scope

            scope = native_embedding_backend_scope(
                profile="CUDA_INDEX_FP32",
                configuration_id=configuration.configuration_id,
                configuration_revision_id=configuration.configuration_revision_id,
                configuration_raw_sha256=configuration.configuration_raw_sha256,
                admission=admission,
                cuda_ownership=ownership,
            )
            with scope() as backend:
                ownership.assert_owned()
                yield backend
                ownership.assert_owned()
    finally:
        # The caller owns this scope; closing it here would release protection too early.
        ownership.assert_owned()
