"""Finite root capture of installed CUDA files; no native code, mount or GPU ownership."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchCompleted

from eom_catalog_service.embedding_benchmark_root_control import RootBenchmarkCudaRuntime
from eom_catalog_service.embedding_benchmark_series_control import (
    BenchmarkRootSeriesSelection,
    serve_root_benchmark_series,
)
from eom_catalog_service.embedding_benchmark_unit_control import require_root_benchmark_control
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_installation_admission import (
    ProtectedCudaInstallationFiles,
)


@contextmanager
def capture_root_benchmark_cuda_runtime(
    backend: NativeEmbeddingBackendPins,
) -> Iterator[RootBenchmarkCudaRuntime]:
    """Borrow the already prepared actual loader namespace; retain all captured FDs.

    No native interpreter or model import, namespace creation, device R/W access,
    physical lease acquisition, source authorization or execution occurs here.
    Only the enclosing root composition owns these temporary file observations.
    """
    require_root_benchmark_control()
    if type(backend) is not NativeEmbeddingBackendPins:
        raise ValueError("BENCHMARK_ROOT_BACKEND_INVALID")
    backend.__post_init__()
    configuration = RootLocalNativeConfigurationPin(
        configuration_id=backend.configuration_id,
        configuration_revision_id=backend.configuration_revision_id,
        configuration_raw_sha256=backend.configuration_raw_sha256,
        configuration_sha256=backend.configuration_sha256,
    )
    with ProtectedCudaInstallationFiles(
        configuration, expected_receipt_raw_sha256=backend.receipt_raw_sha256
    ) as capture:
        if capture.configuration_sha256 != backend.configuration_sha256:
            raise ValueError("BENCHMARK_ROOT_CUDA_CONFIGURATION_MISMATCH")
        runtime = RootBenchmarkCudaRuntime(capture.inventory, capture.host)
        try:
            require_root_benchmark_control()
            capture.assert_current()
            yield runtime
        finally:
            # Failure is not a cleanup grant. The capture's context still closes
            # both FD scopes when this identity/current-installation fence fails.
            require_root_benchmark_control()
            capture.assert_current()


def serve_installed_root_benchmark_series(
    selection: BenchmarkRootSeriesSelection,
) -> tuple[BenchmarkLaunchCompleted, ...]:
    """One actual root process/request; use the existing six-launch state machine."""
    require_root_benchmark_control()
    if type(selection) is not BenchmarkRootSeriesSelection:
        raise ValueError("BENCHMARK_SERIES_SELECTION_INVALID")
    selection.__post_init__()
    with capture_root_benchmark_cuda_runtime(selection.cuda) as cuda:
        return serve_root_benchmark_series(selection, cuda=cuda)
