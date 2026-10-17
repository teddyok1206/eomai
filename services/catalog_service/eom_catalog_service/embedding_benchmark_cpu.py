"""Fixed CPU benchmark executable; PID1 supplies pins, owner retains all source authority."""

from __future__ import annotations

import fcntl
import hashlib
import os
import pwd
import re
import stat
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from eom_catalog_service.embedding_native_cpu_backend import (
    NativeCpuBackendPins,
    native_cpu_backend_scope,
)
from eom_catalog_service.embedding_native_entrypoint import (
    discard_native_embedding_diagnostics,
    require_native_embedding_identity,
)

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation


@dataclass(frozen=True, slots=True)
class _LaunchPins:
    execution_id: str
    invocation_raw_sha256: str
    owner_pid: int
    expires_ns: int
    backend: NativeCpuBackendPins


def _arguments(arguments: tuple[str, ...]) -> _LaunchPins:
    if type(arguments) is not tuple or len(arguments) != 9:
        raise ValueError("BENCHMARK_CPU_OWNER_PINS_INVALID")
    execution, raw_hash, pid, expires, *backend = arguments
    for value, pattern in (
        (execution, r"[0-9a-f]{32}"),
        (raw_hash, r"sha256:[0-9a-f]{64}"),
        (pid, r"[1-9][0-9]{0,9}"),
        (expires, r"[1-9][0-9]{0,18}"),
    ):
        if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
            raise ValueError("BENCHMARK_CPU_OWNER_PINS_INVALID")
    if int(pid) > 2**31 - 1:
        raise ValueError("BENCHMARK_CPU_OWNER_PINS_INVALID")
    return _LaunchPins(execution, raw_hash, int(pid), int(expires), NativeCpuBackendPins(*backend))


def _invocation(pins: _LaunchPins) -> BenchmarkWorkerInvocation:
    # Small envelope adaptation only. Worker file capture rechecks named/FD identity before
    # documents/model entry; it never trusts this preliminary parse as a filesystem grant.
    from eom_catalog_contracts.embedding_device_benchmark import (
        MAX_BENCHMARK_ENVELOPE_BYTES,
        BenchmarkWorkerInvocation,
        embedding_device_benchmark_bytes,
        parse_embedding_device_benchmark_bytes,
    )

    value = os.fstat(0)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != 0
        or value.st_gid != 0
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
        or not 0 < value.st_size <= MAX_BENCHMARK_ENVELOPE_BYTES
        or fcntl.fcntl(0, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
        or os.lseek(0, 0, os.SEEK_CUR) != 0
    ):
        raise ValueError("BENCHMARK_CPU_INVOCATION_INVALID")
    raw = os.pread(0, MAX_BENCHMARK_ENVELOPE_BYTES + 1, 0)
    if (
        len(raw) != value.st_size
        or "sha256:" + hashlib.sha256(raw).hexdigest() != pins.invocation_raw_sha256
    ):
        raise ValueError("BENCHMARK_CPU_INVOCATION_INVALID")
    result = parse_embedding_device_benchmark_bytes(raw)
    if not isinstance(result, BenchmarkWorkerInvocation) or (
        embedding_device_benchmark_bytes(result) != raw
        or result.execution_id != pins.execution_id
        or result.device != "CPU"
        or result.runtime.profile != "CPU_INDEX_FP32"
    ):
        raise ValueError("BENCHMARK_CPU_INVOCATION_INVALID")
    return result


def _execute(pins: _LaunchPins, started_ns: int) -> int:
    now = time.monotonic_ns()
    if not now < pins.expires_ns <= now + 180 * 10**9 or (
        os.environ.get("LISTEN_PID") != str(os.getpid())
        or os.environ.get("LISTEN_FDS") != "1"
        or os.environ.get("LISTEN_FDNAMES") != "benchmark-control"
    ):
        raise ValueError("BENCHMARK_CPU_ACTIVATION_INVALID")
    try:
        return _run(pins, started_ns)
    finally:
        # PID1 transferred this process's activation FD; close it even if header capture fails.
        os.close(3)


def _run(pins: _LaunchPins, started_ns: int) -> int:
    from eom_catalog_service.embedding_benchmark_activation import capture_benchmark_worker_channel
    from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
    from eom_catalog_service.embedding_benchmark_entrypoint import run_native_embedding_benchmark
    from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles

    owner = pwd.getpwnam("eom-workflow-runner")
    if owner.pw_uid <= 0 or owner.pw_gid <= 0:
        raise ValueError("BENCHMARK_CPU_OWNER_INVALID")
    peer = BenchmarkUnixPeer(pins.owner_pid, owner.pw_uid, owner.pw_gid)
    invocation = _invocation(pins)
    files = BenchmarkWorkerLocalFiles(
        0,
        profile="CPU_INDEX_FP32",
        execution_id=pins.execution_id,
        invocation_raw_sha256=pins.invocation_raw_sha256,
    )
    channel = None
    result = 1
    try:

        def fence(actual: BenchmarkUnixPeer) -> None:
            if actual != peer:
                raise ValueError("BENCHMARK_CPU_PEER_CHANGED")

        channel = capture_benchmark_worker_channel(
            invocation,
            activation_fd=3,
            expected_peer=peer,
            peer_fence=fence,
            expires_ns=pins.expires_ns,
        )
        completed = run_native_embedding_benchmark(
            files,
            lambda: native_cpu_backend_scope(pins.backend),
            channel,
            profile="CPU_INDEX_FP32",
            entry_started_ns=started_ns,
            expires_ns=pins.expires_ns,
        )
        result = 0 if completed.status == "COMPLETED" else 1
    finally:
        failed = False
        for resource in (files, channel):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    failed = True
        if failed:
            raise ValueError("BENCHMARK_CPU_CLEANUP_UNCERTAIN")
    return result


def main() -> int:
    started = time.perf_counter_ns()
    try:
        pins = _arguments(tuple(sys.argv[1:]))
        with discard_native_embedding_diagnostics():
            require_native_embedding_identity("CPU_INDEX_FP32")
            return _execute(pins, started)
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
