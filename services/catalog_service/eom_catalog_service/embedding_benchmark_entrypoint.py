"""Fixed benchmark library composition; no production main, socket setup or owner admission."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Literal

from eom_catalog_service.embedding_native_entrypoint import (
    NativeEmbeddingEntrypointError,
    discard_native_embedding_diagnostics,
    require_native_embedding_identity,
)

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerResult

    from eom_catalog_service.embedding_benchmark_channel import BenchmarkWorkerChannel
    from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
    from eom_catalog_service.embedding_execution_ports import BenchmarkNativeEmbeddingBackend


def run_native_embedding_benchmark(
    files: BenchmarkWorkerLocalFiles,
    backend_scope: Callable[[], AbstractContextManager[BenchmarkNativeEmbeddingBackend]],
    channel: BenchmarkWorkerChannel,
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
    entry_started_ns: int,
    expires_ns: int,
) -> BenchmarkWorkerResult:
    """Own captured local resources and enforce identity before importing the worker.

    Owner composition must already admit/stage the exact invocation, installed backend,
    peer-fenced channel and physical device. No such grant or default is created here.
    A returned worker status is not numerical/performance/admission/cleanup acceptance.
    """
    try:
        with discard_native_embedding_diagnostics():
            require_native_embedding_identity(profile)
            from eom_catalog_service.embedding_benchmark_channel import BenchmarkWorkerChannel
            from eom_catalog_service.embedding_benchmark_host_memory import (
                OwnBenchmarkHostOomObserver,
            )
            from eom_catalog_service.embedding_device_benchmark_files import (
                BenchmarkWorkerLocalFiles,
            )
            from eom_catalog_service.embedding_device_benchmark_worker import (
                run_embedding_device_benchmark,
            )

            if (
                type(files) is not BenchmarkWorkerLocalFiles
                or files.profile != profile
                or type(channel) is not BenchmarkWorkerChannel
            ):
                raise NativeEmbeddingEntrypointError("NATIVE_BENCHMARK_CAPTURE_INVALID")
            host = OwnBenchmarkHostOomObserver(
                device="CPU" if profile == "CPU_INDEX_FP32" else "CUDA",
                execution_id=files.execution_id,
                policy=channel.execution_policy,
            )
            return run_embedding_device_benchmark(
                files,
                backend_scope,
                channel,
                entry_started_ns=entry_started_ns,
                expires_ns=expires_ns,
                host_oom_observer=host,
            )
    except Exception:
        raise NativeEmbeddingEntrypointError("NATIVE_BENCHMARK_EXECUTION_FAILED") from None
    finally:
        failed = False
        for resource in (files, channel):
            try:
                resource.close()
            except Exception:
                failed = True
        if failed:
            raise NativeEmbeddingEntrypointError("NATIVE_BENCHMARK_CLEANUP_UNCERTAIN")
