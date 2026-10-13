"""Fixed nonprivileged CPU installation probe, with no model/forward or runtime authority."""

from __future__ import annotations

import errno
import fcntl
import os
import re
import signal
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_native_cpu_probe import (
        NativeCpuProbeInput,
        NativeCpuProbeResult,
    )

PROBE_ROOT = Path("/run/eom-embedding-native-probe")
MODEL_ROOT = Path("/opt/eom/embedding-models")
PROFILE: Final = "CPU_INDEX_FP32"
_MAX_BYTES = 64 * 1024
_OWNER_RELEASE_SECONDS = 30


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


def _descriptors(input_fd: int, result_fd: int) -> tuple[os.stat_result, os.stat_result]:
    values = os.fstat(input_fd), os.fstat(result_fd)
    if (
        any(
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != 0
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) != 0o600
            for value in values
        )
        or (values[0].st_dev, values[0].st_ino) == (values[1].st_dev, values[1].st_ino)
        or not 0 < values[0].st_size <= _MAX_BYTES
        or values[1].st_size != 0
    ):
        raise ValueError("NATIVE_CPU_PROBE_DESCRIPTORS_INVALID")
    for descriptor, mode in ((input_fd, os.O_RDONLY), (result_fd, os.O_WRONLY)):
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        if (
            flags & os.O_ACCMODE != mode
            or flags & (os.O_APPEND | os.O_NONBLOCK)
            or os.lseek(descriptor, 0, os.SEEK_CUR) != 0
        ):
            raise ValueError("NATIVE_CPU_PROBE_DESCRIPTORS_INVALID")
    return values


def _denied_write(path: Path) -> None:
    """Open only: never create, truncate or change even an unexpectedly writable target."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return
        raise ValueError("NATIVE_CPU_PROBE_WRITE_CHECK_INVALID") from None
    os.close(descriptor)
    raise ValueError("NATIVE_CPU_PROBE_WRITE_ALLOWED")


@contextmanager
def observe_native_cpu_probe(
    request: NativeCpuProbeInput, request_raw: bytes
) -> Iterator[NativeCpuProbeResult]:
    """Retain the actual proof/payload observations through the owner's live-process check."""
    require_native_embedding_identity(PROFILE)
    from eom_catalog_contracts.embedding_native_cpu_probe import (
        NativeCpuProbeResult,
        parse_native_cpu_probe_input,
        validate_native_cpu_probe_association,
    )
    from eom_catalog_contracts.embedding_runtime_bundle import embedding_payload_file_set_sha256
    from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
    from eom_identifiers import sha256_bytes

    from eom_catalog_service.embedding_installed_runtime_observer import (
        ConfiguredInstalledRuntimeProof,
        ProtectedInstalledEmbeddingRuntimeObserver,
    )
    from eom_catalog_service.embedding_offline_backend import observe_native_runtime_without_model
    from eom_catalog_service.inference_transfer_cpu_verifier import (
        DENIED_FILES,
        DENIED_SOCKETS,
        denied_file,
        denied_socket,
        verify_no_network,
    )
    from eom_catalog_service.local_embedding_adapter import (
        read_protected_embedding_manifest,
        resolve_local_embedding_payload,
    )

    if parse_native_cpu_probe_input(request_raw) != request:
        raise ValueError("NATIVE_CPU_PROBE_INPUT_CHANGED")
    observer = ProtectedInstalledEmbeddingRuntimeObserver(
        ConfiguredInstalledRuntimeProof(request.installed_proof)
    )
    installed = observer.observe()
    pointer = request.payload
    root = MODEL_ROOT / pointer.model_id / pointer.model_revision_id
    manifest = read_protected_embedding_manifest(root / "manifest.json")
    if manifest.sha256 != pointer.manifest_raw_sha256:
        raise ValueError("NATIVE_CPU_PROBE_PAYLOAD_MISMATCH")
    spec = LocalEmbeddingModelSpec.model_validate_json(manifest.raw)
    if (
        spec.model_id != pointer.model_id
        or spec.model_revision_id != pointer.model_revision_id
        or spec.manifest_sha256 != pointer.manifest_sha256
        or embedding_payload_file_set_sha256(spec) != pointer.file_set_sha256
    ):
        raise ValueError("NATIVE_CPU_PROBE_PAYLOAD_MISMATCH")
    payload = resolve_local_embedding_payload(MODEL_ROOT, spec)
    if payload.manifest.raw != manifest.raw:
        raise ValueError("NATIVE_CPU_PROBE_PAYLOAD_MISMATCH")
    verify_no_network()
    reads = (
        *(
            ("legacy_handoff" if name == "handoff_workspace" else name, path)
            for name, path in DENIED_FILES
        ),
        ("legacy_repository", Path("/home/eom/EOMIS")),
        ("probe_workspace", PROBE_ROOT),
    )
    denials = {name: denied_file(path) for name, path in reads}
    denials.update((name, denied_socket(path)) for name, path in DENIED_SOCKETS)
    _denied_write(Path(__file__).absolute())
    denials["prefix_write"] = "DENIED"
    for path in (root / "manifest.json", *(root / member.member_path for member in spec.files)):
        _denied_write(path)
    denials["model_write"] = "DENIED"
    runtime = observe_native_runtime_without_model(profile=PROFILE, runtime_observer=observer)
    result = NativeCpuProbeResult.model_validate(
        {
            "schema_version": "embedding-native-cpu-probe-result/1.0",
            "evidence_state": "OBSERVED_NOT_ADMITTED",
            "recipe": "NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
            "execution_id": request.execution_id,
            "input_raw_sha256": sha256_bytes(request_raw),
            "pid": os.getpid(),
            "worker_uid": os.geteuid(),
            "worker_gid": os.getegid(),
            "supplementary_gids": sorted(set(os.getgroups()) - {os.getegid()}),
            "checked_model_members": len(spec.files) + 1,
            "payload_file_set_sha256": pointer.file_set_sha256,
            "denials": denials,
            "numerical_runtime": runtime.model_dump(mode="json"),
        }
    )
    validate_native_cpu_probe_association(request, request_raw, result)
    try:
        yield result
    finally:
        require_native_embedding_identity(PROFILE)
        manifest.assert_unchanged()
        payload.assert_unchanged()
        if observer.observe() != installed:
            raise ValueError("NATIVE_CPU_PROBE_RUNTIME_CHANGED")


def _write_report(descriptor: int, raw: bytes, initial: os.stat_result) -> None:
    if not 0 < len(raw) <= _MAX_BYTES or _epoch(os.fstat(descriptor)) != _epoch(initial):
        raise ValueError("NATIVE_CPU_PROBE_OUTPUT_CHANGED")
    remaining = memoryview(raw)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise ValueError("NATIVE_CPU_PROBE_OUTPUT_FAILED")
        remaining = remaining[written:]
    os.fsync(descriptor)
    final = os.fstat(descriptor)
    if (
        _epoch(final)[:6] != _epoch(initial)[:6]
        or final.st_size != len(raw)
        or os.lseek(descriptor, 0, os.SEEK_CUR) != len(raw)
    ):
        raise ValueError("NATIVE_CPU_PROBE_OUTPUT_CHANGED")


def _wait_owner_release() -> None:
    received = signal.sigtimedwait({signal.SIGUSR1}, _OWNER_RELEASE_SECONDS)
    if received is None or received.si_signo != signal.SIGUSR1 or received.si_uid != 0:
        raise ValueError("NATIVE_CPU_PROBE_OWNER_OBSERVATION_MISSING")


def run_native_cpu_probe(execution_id: str, *, input_fd: int, result_fd: int) -> None:
    require_native_embedding_identity(PROFILE)
    if re.fullmatch(r"[0-9a-f]{32}", execution_id) is None:
        raise ValueError("NATIVE_CPU_PROBE_EXECUTION_INVALID")
    # New library threads inherit this mask. The root owner acknowledges only after
    # independently observing the exact running unit, process start time and ELF maps.
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    initial, output = _descriptors(input_fd, result_fd)
    raw = os.read(input_fd, initial.st_size + 1)
    if len(raw) != initial.st_size or _epoch(os.fstat(input_fd)) != _epoch(initial):
        raise ValueError("NATIVE_CPU_PROBE_INPUT_CHANGED")
    from eom_catalog_contracts.embedding_native_cpu_probe import parse_native_cpu_probe_input
    from eom_identifiers import canonical_json_bytes

    request = parse_native_cpu_probe_input(raw)
    if request.execution_id != execution_id:
        raise ValueError("NATIVE_CPU_PROBE_EXECUTION_MISMATCH")
    with observe_native_cpu_probe(request, raw) as result:
        _write_report(result_fd, canonical_json_bytes(result.model_dump(mode="json")), output)
        _wait_owner_release()
        if _epoch(os.fstat(input_fd)) != _epoch(initial):
            raise ValueError("NATIVE_CPU_PROBE_INPUT_CHANGED")


def main() -> int:
    result_fd: int | None = None
    try:
        if len(sys.argv) != 2:
            return 2
        result_fd = fcntl.fcntl(1, fcntl.F_DUPFD_CLOEXEC, 3)
        sink = os.open("/dev/null", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.dup2(sink, 1)
            os.dup2(sink, 2)
        finally:
            os.close(sink)
        run_native_cpu_probe(sys.argv[1], input_fd=0, result_fd=result_fd)
        return 0
    except Exception:
        # Exit status and retained partial result are enough; no raw exception, input,
        # library diagnostic, credentials or model content may enter the result/journal.
        return 1
    finally:
        if result_fd is not None:
            os.close(result_fd)


if __name__ == "__main__":
    raise SystemExit(main())
