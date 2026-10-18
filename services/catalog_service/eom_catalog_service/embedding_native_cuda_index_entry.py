"""Fixed external CUDA INDEX leaf; root ACK/lifetime/source ownership remain separate."""

from __future__ import annotations

import fcntl
import os
import re
import signal
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )
    from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingInput

    from eom_catalog_service.embedding_cuda_probe_resource_files import OpenedCudaProbeDeviceAccess

_READY_FD = 3
_READY_NAME = "cuda-index-ready"
_MAX_READY_BYTES = 8 * 1024
_MAX_LIFETIME_NS = 180 * 10**9  # This fixed CUDA INDEX target, not the general policy upper bound.


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_INDEX_ENTRY_INVALID")


@dataclass(frozen=True, slots=True)
class NativeCudaIndexLaunchPins:
    execution_id: str
    job_id: str
    association_sha256: str
    input_raw_sha256: str
    expires_ns: int
    configuration_id: str
    configuration_revision_id: str
    configuration_sha256: str
    configuration_raw_sha256: str
    receipt_raw_sha256: str


def parse_native_cuda_index_launch_pins(arguments: tuple[str, ...]) -> NativeCudaIndexLaunchPins:
    _require(type(arguments) is tuple and len(arguments) == 11)
    (
        purpose,
        execution,
        job,
        association,
        input_hash,
        expiry,
        config,
        revision,
        semantic,
        raw,
        receipt,
    ) = arguments
    _require(type(purpose) is str and purpose == "INDEX")
    for value, pattern in (
        (execution, r"[0-9a-f]{32}"),
        (job, r"job_[0-9a-f]{32}"),
        (expiry, r"[1-9][0-9]{0,18}"),
        (config, r"embeddingnativeconfig_[0-9a-f]{32}"),
        (revision, r"embeddingnativeconfigrev_[0-9a-f]{32}"),
        *(
            (value, r"sha256:[0-9a-f]{64}")
            for value in (association, input_hash, semantic, raw, receipt)
        ),
    ):
        _require(type(value) is str and re.fullmatch(pattern, value, re.ASCII) is not None)
    _require(int(expiry) <= 2**63 - 1)
    return NativeCudaIndexLaunchPins(
        execution,
        job,
        association,
        input_hash,
        int(expiry),
        config,
        revision,
        semantic,
        raw,
        receipt,
    )


def _before_deadline(pins: NativeCudaIndexLaunchPins) -> None:
    now = time.monotonic_ns()
    _require(now < pins.expires_ns <= now + _MAX_LIFETIME_NS)


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


def _descriptor(descriptor: int, *, access: int, mode: int, maximum: int) -> os.stat_result:
    value = os.fstat(descriptor)
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == 0
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == mode
        and flags & (os.O_ACCMODE | os.O_APPEND) == access
        and os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        and (value.st_size == 0 if maximum == 0 else 0 < value.st_size <= maximum)
    )
    return value


@contextmanager
def _result_channels() -> Iterator[tuple[int, int]]:
    owned: list[int] = []
    try:
        result = _descriptor(1, access=os.O_WRONLY, mode=0o640, maximum=0)
        vectors = _descriptor(2, access=os.O_WRONLY, mode=0o640, maximum=0)
        _require((result.st_dev, result.st_ino) != (vectors.st_dev, vectors.st_ino))
        for descriptor in (1, 2):
            owned.append(fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 4))
        yield owned[0], owned[1]
    finally:
        for descriptor in reversed(owned):
            os.close(descriptor)


def _read_input(
    pins: NativeCudaIndexLaunchPins,
) -> tuple[IncrementalEmbeddingInput, tuple[int, ...]]:
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        parse_rootlocal_evidence_document,
    )
    from eom_catalog_contracts.inference_transfer_embedding import (
        MAX_EMBEDDING_INPUT_BYTES,
        parse_incremental_embedding_input,
    )
    from eom_identifiers import canonical_json_bytes, sha256_bytes

    initial = _descriptor(0, access=os.O_RDONLY, mode=0o600, maximum=MAX_EMBEDDING_INPUT_BYTES)
    chunks: list[bytes] = []
    count = 0
    while count <= initial.st_size:
        chunk = os.read(0, min(65536, initial.st_size + 1 - count))
        if not chunk:
            break
        chunks.append(chunk)
        count += len(chunk)
    _require(count == initial.st_size and _epoch(initial) == _epoch(os.fstat(0)))
    raw = b"".join(chunks)
    _require(sha256_bytes(raw) == pins.input_raw_sha256)
    request = parse_incremental_embedding_input(
        parse_rootlocal_evidence_document(raw, MAX_EMBEDDING_INPUT_BYTES)
    )
    _require(
        raw == canonical_json_bytes(request.model_dump(mode="json"))
        and request.job_id == pins.job_id
        and request.space.runtime.device == "CUDA"
        and request.batch_size == request.threads == 4
    )
    _require(os.lseek(0, 0, os.SEEK_SET) == 0)
    return request, _epoch(initial)


def _assert_input_current(epoch: tuple[int, ...]) -> None:
    _require(_epoch(os.fstat(0)) == epoch and os.lseek(0, 0, os.SEEK_CUR) == 0)


def _ready_descriptor() -> os.stat_result:
    _require(
        os.environ.get("LISTEN_PID") == str(os.getpid())
        and os.environ.get("LISTEN_FDS") == "1"
        and os.environ.get("LISTEN_FDNAMES") == _READY_NAME
    )
    initial = _descriptor(_READY_FD, access=os.O_RDWR, mode=0o640, maximum=0)
    os.set_inheritable(_READY_FD, False)
    return initial


def _write_ready(raw: bytes, initial: os.stat_result) -> tuple[int, ...]:
    _require(0 < len(raw) <= _MAX_READY_BYTES)
    # The root reader takes a shared READY-file lock, never the physical GPU lease.
    fcntl.flock(_READY_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _require(
            _epoch(_descriptor(_READY_FD, access=os.O_RDWR, mode=0o640, maximum=0))
            == _epoch(initial)
        )
        remaining = memoryview(raw)
        while remaining:
            count = os.write(_READY_FD, remaining)
            _require(0 < count <= len(remaining))
            remaining = remaining[count:]
        os.fsync(_READY_FD)
        after = os.fstat(_READY_FD)
        _require(_epoch(after)[:6] == _epoch(initial)[:6] and after.st_size == len(raw))
        epoch = _epoch(after)
        _assert_ready_current(epoch)
        return epoch
    finally:
        fcntl.flock(_READY_FD, fcntl.LOCK_UN)


def _assert_ready_current(epoch: tuple[int, ...]) -> None:
    _require(
        _epoch(os.fstat(_READY_FD)) == epoch
        and os.lseek(_READY_FD, 0, os.SEEK_CUR) == epoch[6]
        and fcntl.fcntl(_READY_FD, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND) == os.O_RDWR
        and not os.get_inheritable(_READY_FD)
    )


def _wait_root_ack(expires_ns: int) -> None:
    now = time.monotonic_ns()
    deadline = min(expires_ns, now + 30 * 10**9)
    _require(now < deadline and signal.SIGUSR1 in signal.pthread_sigmask(signal.SIG_BLOCK, set()))
    received = None
    while time.monotonic_ns() < deadline:
        received = signal.sigtimedwait({signal.SIGUSR1}, 0)
        if received is not None:
            break
        time.sleep(min(0.05, max(0.0, (deadline - time.monotonic_ns()) / 10**9)))
    _require(
        received is not None
        and received.si_signo == signal.SIGUSR1
        and type(received.si_uid) is int
        and received.si_uid == 0
        and type(received.si_pid) is int
        and received.si_pid > 0
        and time.monotonic_ns() < deadline
    )


def _silence_diagnostics() -> None:
    sink = -1
    try:
        # Stdlib-only bootstrap must precede even imports of the sealed public library.
        sink = os.open("/dev/null", os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        value = os.fstat(sink)
        _require(
            stat.S_ISCHR(value.st_mode)
            and (os.major(value.st_rdev), os.minor(value.st_rdev)) == (1, 3)
        )
        os.dup2(sink, 1)
        os.dup2(sink, 2)
    except BaseException:
        # Even a broken /dev/null capture must never turn vector/result FDs into diagnostics.
        for descriptor in (1, 2):
            with suppress(BaseException):
                os.close(descriptor)
        raise ValueError("NATIVE_CUDA_INDEX_DIAGNOSTIC_SINK_INVALID") from None
    finally:
        if sink >= 0:
            with suppress(BaseException):
                os.close(sink)


def _require_identity() -> None:
    from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity

    require_native_embedding_identity("CUDA_INDEX_FP32")


def _run_numerical(
    configuration: RootLocalNativeConfigurationPin,
    receipt_raw_sha256: str,
    ownership: OpenedCudaProbeDeviceAccess,
    outputs: tuple[int, int],
) -> None:
    # Imports remain quiet and occur only after ACK; the sealed numerical entry owns outputs.
    from eom_catalog_service.embedding_native_cuda_backend import native_cuda_backend_scope
    from eom_catalog_service.embedding_native_entrypoint import run_native_embedding_index

    try:
        os.dup2(outputs[0], 1)
        os.dup2(outputs[1], 2)
        run_native_embedding_index(
            profile="CUDA_INDEX_FP32",
            backend_scope=lambda: native_cuda_backend_scope(
                configuration, receipt_raw_sha256=receipt_raw_sha256, ownership=ownership
            ),
        )
    finally:
        _silence_diagnostics()


def _run(pins: NativeCudaIndexLaunchPins, outputs: tuple[int, int]) -> int:
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )
    from eom_gpu_lease import acquire_shared_gpu_lease, request_unit_gpu_lease_retention
    from eom_identifiers import canonical_json_bytes, content_sha256

    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        capture_cuda_probe_resource_files,
        open_cuda_probe_device_access,
    )
    from eom_catalog_service.embedding_native_installation_admission import (
        read_pinned_cuda_admission_receipt,
    )
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    _before_deadline(pins)
    ready_initial = _ready_descriptor()
    request, input_epoch = _read_input(pins)
    _require(
        len(
            {
                (value.st_dev, value.st_ino)
                for value in (ready_initial, os.fstat(0), *(os.fstat(fd) for fd in outputs))
            }
        )
        == 4
    )
    configuration = RootLocalNativeConfigurationPin(
        configuration_id=pins.configuration_id,
        configuration_revision_id=pins.configuration_revision_id,
        configuration_sha256=pins.configuration_sha256,
        configuration_raw_sha256=pins.configuration_raw_sha256,
    )
    files = NumericalRuntimeFileSnapshots(0)
    receipt, _raw_receipt = read_pinned_cuda_admission_receipt(
        files, configuration, receipt_raw_sha256=pins.receipt_raw_sha256
    )
    device = receipt.device_capture
    _require(
        device.numeric_device.kind == "CUDA"
        and receipt.runtime_sha256 == request.space.runtime.execution_runtime_sha256
    )
    files.assert_unchanged()
    _before_deadline(pins)
    lease = acquire_shared_gpu_lease()
    try:
        with capture_cuda_probe_resource_files(device, lease) as resources:
            request_unit_gpu_lease_retention(lease)
            resources.assert_current()
            metadata = resources.shared_gpu_lease
            body = {
                "schema_version": "embedding-native-cuda-index-ready/1.0",
                "purpose": "INDEX",
                "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
                "execution_id": pins.execution_id,
                "job_id": request.job_id,
                "launch_association_sha256": pins.association_sha256,
                "input_raw_sha256": pins.input_raw_sha256,
                "request_sha256": request.request_sha256,
                "input_set_sha256": request.input_set_sha256,
                "configuration": configuration.model_dump(mode="json"),
                "receipt_raw_sha256": pins.receipt_raw_sha256,
                "fdstore_name": "eom-gpu0-lease",
                "pid": metadata.holder_pid,
                "start_time_ticks": metadata.holder_start_time_ticks,
                "worker_uid": os.geteuid(),
                "worker_gid": os.getegid(),
                "supplementary_gids": sorted(set(os.getgroups()) - {os.getegid()}),
                "resource_fds": resources.resource_descriptors.model_dump(mode="json"),
                "expected_device_capture": device.model_dump(mode="json"),
                "cuda_initialization_calls": 0,
                "cuda_synchronize_calls": 0,
                "model_constructor_calls": 0,
                "tokenizer_constructor_calls": 0,
                "forward_calls": 0,
            }
            ready_epoch = _write_ready(
                canonical_json_bytes(body | {"ready_sha256": content_sha256(body)}), ready_initial
            )
            _wait_root_ack(pins.expires_ns)
            _before_deadline(pins)
            _assert_input_current(input_epoch)
            _assert_ready_current(ready_epoch)
            files.assert_unchanged()
            resources.assert_current()
            with open_cuda_probe_device_access(resources) as ownership:
                _before_deadline(pins)
                _run_numerical(configuration, pins.receipt_raw_sha256, ownership, outputs)
                _before_deadline(pins)
    finally:
        # PID1 may already retain the open description: never unlock or remove that store.
        lease.close()
    return 0


def main() -> int:
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
        _require(signal.SIGUSR1 not in signal.sigpending())
        with _result_channels() as outputs:
            _silence_diagnostics()
            _require_identity()
            pins = parse_native_cuda_index_launch_pins(tuple(sys.argv[1:]))
            return _run(pins, outputs)
    except BaseException:
        # KeyboardInterrupt/SystemExit also belong to the binary output failure boundary.
        with suppress(BaseException):
            _silence_diagnostics()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
