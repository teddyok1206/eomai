"""One nonblocking physical claim for a separately admitted native worker lifetime."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_gpu_lease import SharedGpuLease


class NativeEmbeddingGpuAllocationError(ValueError):
    def __init__(self) -> None:
        super().__init__("NATIVE_EMBEDDING_GPU_ALLOCATION_INVALID")


@contextmanager
def hold_native_embedding_gpu_allocation() -> Iterator[SharedGpuLease | None]:
    """None means acquire-time BUSY only, never an execution failure or compute grant.

    The caller first checks its installed native identity/admission. An acquired lease
    stays held through the caller's READY/ACK/work lifetime; PID1 retention and root
    retirement are independently mandatory. There is no probe/release/reacquire gap.
    The package remains optional for ordinary CPU imports.
    """
    try:
        from eom_gpu_lease import SharedGpuLeaseError, acquire_shared_gpu_lease
    except ImportError:
        raise NativeEmbeddingGpuAllocationError() from None
    try:
        lease = acquire_shared_gpu_lease()
    except SharedGpuLeaseError as error:
        if error.code != "BUSY":
            raise NativeEmbeddingGpuAllocationError() from None
        yield None
        return
    try:
        yield lease
    finally:
        # Never explicitly unlock or remove PID1's possibly retained description.
        lease.close()
