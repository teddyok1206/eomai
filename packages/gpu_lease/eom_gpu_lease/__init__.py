"""Public shared physical-GPU mutex; no scheduling, runtime or authority grant."""

from eom_gpu_lease.lease import (
    SHARED_GPU_LOCK_PATH,
    SharedGpuLease,
    SharedGpuLeaseError,
    acquire_shared_gpu_lease,
    shared_gpu_lease,
)

__all__ = [
    "SHARED_GPU_LOCK_PATH",
    "SharedGpuLease",
    "SharedGpuLeaseError",
    "acquire_shared_gpu_lease",
    "shared_gpu_lease",
]
