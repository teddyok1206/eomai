"""Stdlib-first fixed finite GPU batch bootstrap; no source permission or publication."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import sys
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest

    from eom_catalog_service.embedding_gpu_batch_launch import NativeEmbeddingGpuBatchLaunchPins

_ROOT_UID = 0
_ALLOCATION_MAX_BYTES = 32 * 1024


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_ENTRY_INVALID")


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _silence() -> None:
    sink = -1
    try:
        sink = os.open("/dev/null", os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        value = os.fstat(sink)
        _require(
            stat.S_ISCHR(value.st_mode)
            and (os.major(value.st_rdev), os.minor(value.st_rdev)) == (1, 3)
        )
        os.dup2(sink, 1)
        os.dup2(sink, 2)
    finally:
        if sink >= 0:
            os.close(sink)


def _activation_descriptors() -> dict[str, int]:
    names = os.environ.get("LISTEN_FDNAMES", "").split(":")
    _require(
        os.environ.get("LISTEN_PID") == str(os.getpid())
        and os.environ.get("LISTEN_FDS") == "2"
        and len(names) == 2
        and set(names) == {"gpu-batch-control", "gpu-batch-allocation"}
    )
    result = dict(zip(names, (3, 4), strict=True))
    for descriptor in result.values():
        os.set_inheritable(descriptor, False)
    return result


def _read_allocation(
    descriptor: int,
    pins: NativeEmbeddingGpuBatchLaunchPins,
) -> EmbeddingGpuAllocationRequest:
    from eom_catalog_contracts.embedding_gpu_control import (
        EmbeddingGpuAllocationRequest,
        parse_embedding_gpu_control_bytes,
    )

    initial = os.fstat(descriptor)
    _require(
        stat.S_ISREG(initial.st_mode)
        and initial.st_uid == _ROOT_UID
        and initial.st_nlink == 1
        and stat.S_IMODE(initial.st_mode) == 0o600
        and 0 < initial.st_size <= _ALLOCATION_MAX_BYTES
        and os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        and fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND) == os.O_RDONLY
    )
    parts = []
    count = 0
    while count <= initial.st_size:
        part = os.read(descriptor, min(65536, initial.st_size + 1 - count))
        if not part:
            break
        parts.append(part)
        count += len(part)
    _require(count == initial.st_size and _epoch(os.fstat(descriptor)) == _epoch(initial))
    raw = b"".join(parts)
    _require("sha256:" + hashlib.sha256(raw).hexdigest() == pins.allocation_raw_sha256)
    value = parse_embedding_gpu_control_bytes(raw)
    _require(type(value) is EmbeddingGpuAllocationRequest)
    assert isinstance(value, EmbeddingGpuAllocationRequest)
    _require(value.allocation_attempt_id == "embeddingallocation_" + pins.attempt_hex)
    return value


def _run(arguments: tuple[str, ...], outputs: tuple[int, int]) -> int:
    from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity

    require_native_embedding_identity("CUDA_INDEX_FP32")
    from eom_catalog_service.embedding_gpu_batch_activation import (
        capture_embedding_gpu_batch_worker_channel,
    )
    from eom_catalog_service.embedding_gpu_batch_launch import (
        parse_native_embedding_gpu_batch_launch,
    )
    from eom_catalog_service.embedding_gpu_batch_worker import run_native_embedding_gpu_batch_worker
    from eom_catalog_service.embedding_native_stdio import NativeEmbeddingDescriptors
    from eom_catalog_service.embedding_work_batch_execution import (
        EmbeddingWorkBatchExecutionResources,
    )

    pins = parse_native_embedding_gpu_batch_launch(arguments)
    descriptors = _activation_descriptors()
    try:
        request = _read_allocation(descriptors["gpu-batch-allocation"], pins)
        _require(
            len(
                {
                    (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                    for fd in (0, *outputs, descriptors["gpu-batch-allocation"])
                }
            )
            == 4
        )
        channel = capture_embedding_gpu_batch_worker_channel(
            request,
            activation_fd=descriptors["gpu-batch-control"],
            expected_root_pid=pins.root_pid,
        )
        try:
            run_native_embedding_gpu_batch_worker(
                channel,
                NativeEmbeddingDescriptors(0, *outputs),
                expected_backend=pins.backend,
                resources=EmbeddingWorkBatchExecutionResources(
                    pins.resource_profile_sha256,
                    pins.timeout_seconds,
                    pins.vector_max_bytes,
                ),
                maximum_total_output_bytes=pins.total_output_max_bytes,
            )
        finally:
            channel.close()
        return 0
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)


def main() -> int:
    outputs = []
    result = 1
    try:
        # Numeric results must never receive import/traceback diagnostics. The
        # inherited descriptors3/4 are occupied; F_DUPFD selects unused CLOEXEC FDs.
        for descriptor in (1, 2):
            outputs.append(fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 3))
        _silence()
        result = _run(tuple(sys.argv[1:]), (outputs[0], outputs[1]))
    except BaseException:
        with suppress(BaseException):
            _silence()
        result = 1
    finally:
        for descriptor in outputs:
            try:
                os.close(descriptor)
            except OSError:
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
