"""One native worker lifetime; no launch, source authority, CPU fallback or Artifact commit."""

from __future__ import annotations

import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import current_thread, main_thread
from typing import TYPE_CHECKING

from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationBusy
    from eom_catalog_contracts.embedding_work_batch_result import EmbeddingWorkBatchResult

    from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel
    from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
    from eom_catalog_service.embedding_native_stdio import NativeEmbeddingDescriptors
    from eom_catalog_service.embedding_work_batch_execution import (
        EmbeddingWorkBatchExecutionResources,
    )


@contextmanager
def _hard_compute_deadline(seconds: int) -> Iterator[None]:
    """Kernel default SIGALRM ends this dedicated worker even if native code holds the GIL.

    Arm only after the original compute grant. Never install a Python signal
    handler, overwrite an existing timer or use this in a shared service thread.
    Root owns original-unit retirement and retained-GPU-descriptor cleanup.
    """
    from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS

    if (
        type(seconds) is not int
        or not 1 <= seconds <= MAX_EMBEDDING_WORK_BATCH_SECONDS
        or current_thread() is not main_thread()
        or signal.getsignal(signal.SIGALRM) != signal.SIG_DFL
        or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)
        or signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK, ())
    ):
        raise ValueError("NATIVE_EMBEDDING_GPU_COMPUTE_DEADLINE_INVALID")
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)


def run_native_embedding_gpu_batch_worker(
    channel: EmbeddingGpuControlChannel,
    descriptors: NativeEmbeddingDescriptors,
    *,
    expected_backend: NativeEmbeddingBackendPins,
    resources: EmbeddingWorkBatchExecutionResources,
    maximum_total_output_bytes: int,
) -> EmbeddingGpuAllocationBusy | EmbeddingWorkBatchResult:
    """Consume one exact-peer channel after quiet bootstrap and original-unit admission.

    The caller independently constructs the channel with actual root peer/unit fences
    and fixed backend/resource pins. BUSY is only a claim requiring root nonexecution
    observation. Closing our lease does not release PID1's retained original description.
    """
    from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel

    try:
        require_native_embedding_identity("CUDA_INDEX_FP32")
        from eom_catalog_contracts.embedding_gpu_control import (
            EmbeddingGpuAllocationBusy,
            EmbeddingGpuAllocationReady,
        )
        from eom_gpu_lease import request_unit_gpu_lease_retention
        from eom_identifiers import content_sha256

        from eom_catalog_service.embedding_cuda_probe_resource_files import (
            capture_cuda_probe_resource_files,
            open_cuda_probe_device_access,
        )
        from eom_catalog_service.embedding_gpu_allocation import (
            hold_native_embedding_gpu_allocation,
        )
        from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
        from eom_catalog_service.embedding_native_cuda_backend import native_cuda_backend_scope
        from eom_catalog_service.embedding_native_installation_admission import (
            read_pinned_cuda_admission_receipt,
        )
        from eom_catalog_service.embedding_native_stdio import (
            run_granted_native_embedding_gpu_batch_descriptors,
        )
        from eom_catalog_service.embedding_runtime_files import (
            NumericalRuntimeFileSnapshots,
            read_live_runtime_os_file,
        )
        from eom_catalog_service.embedding_runtime_process_identity import (
            native_process_start_ticks,
        )

        if type(channel) is not EmbeddingGpuControlChannel:
            raise ValueError("NATIVE_EMBEDDING_GPU_BATCH_CHANNEL_INVALID")
        channel.receive_request()
        request = channel.request
        if (
            request.purpose not in ("INDEX", "REFERENCE_QUERY")
            or type(expected_backend) is not NativeEmbeddingBackendPins
        ):
            raise ValueError("NATIVE_EMBEDDING_GPU_BATCH_BINDING_INVALID")
        expected_backend.__post_init__()
        configuration = request.configuration
        if expected_backend != NativeEmbeddingBackendPins(
            configuration.configuration_id,
            configuration.configuration_revision_id,
            configuration.configuration_sha256,
            configuration.configuration_raw_sha256,
            request.receipt_raw_sha256,
        ):
            raise ValueError("NATIVE_EMBEDDING_GPU_BATCH_BINDING_INVALID")
        files = NumericalRuntimeFileSnapshots(0)
        receipt, _ = read_pinned_cuda_admission_receipt(
            files, configuration, receipt_raw_sha256=request.receipt_raw_sha256
        )
        device = receipt.device_capture
        if device.numeric_device.kind != "CUDA":
            raise ValueError("NATIVE_EMBEDDING_GPU_BATCH_BINDING_INVALID")
        files.assert_unchanged()
        base = {
            "schema_version": "embedding-gpu-allocation-control/1.0",
            "allocation_attempt_id": request.allocation_attempt_id,
            "allocation_request_sha256": request.message_sha256,
            "pid": os.getpid(),
            "worker_uid": os.geteuid(),
            "worker_gid": os.getegid(),
        }
        with hold_native_embedding_gpu_allocation() as lease:
            if lease is None:
                body = base | {
                    "message_type": "ALLOCATION_BUSY",
                    "evidence_state": "ALLOCATION_UNAVAILABLE_NOT_EXECUTED",
                    "start_time_ticks": native_process_start_ticks(
                        read_live_runtime_os_file(
                            Path("/proc") / str(os.getpid()) / "stat",
                            maximum=65536,
                            owner_uid=os.geteuid(),
                        ),
                        os.getpid(),
                    ),
                }
                busy = EmbeddingGpuAllocationBusy.model_validate(
                    body | {"message_sha256": content_sha256(body)}
                )
                channel.send_allocation(busy)
                return busy
            with capture_cuda_probe_resource_files(device, lease) as captured:
                request_unit_gpu_lease_retention(lease)
                captured.assert_current()
                body = base | {
                    "message_type": "ALLOCATION_READY",
                    "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
                    "start_time_ticks": captured.shared_gpu_lease.holder_start_time_ticks,
                    "supplementary_gids": sorted(set(os.getgroups()) - {os.getegid()}),
                    "resource_fds": captured.resource_descriptors.model_dump(mode="json"),
                    "expected_device_capture": device.model_dump(mode="json"),
                    "fdstore_name": "eom-gpu0-lease",
                }
                ready = EmbeddingGpuAllocationReady.model_validate(
                    body | {"message_sha256": content_sha256(body)}
                )
                channel.send_allocation(ready)
                channel.receive_grant()
                with _hard_compute_deadline(resources.timeout_seconds):
                    files.assert_unchanged()
                    captured.assert_current()
                    with open_cuda_probe_device_access(captured) as ownership:
                        return run_granted_native_embedding_gpu_batch_descriptors(
                            descriptors,
                            lambda: native_cuda_backend_scope(
                                configuration,
                                receipt_raw_sha256=request.receipt_raw_sha256,
                                ownership=ownership,
                            ),
                            resources=resources,
                            maximum_total_output_bytes=maximum_total_output_bytes,
                            channel=channel,
                        )
    finally:
        if type(channel) is EmbeddingGpuControlChannel:
            channel.close()
