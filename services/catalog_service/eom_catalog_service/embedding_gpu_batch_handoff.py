"""Root-only original local input materialization; no unit start, source or Artifact grant."""

from __future__ import annotations

import fcntl
import os
import stat
import time
from dataclasses import dataclass

from eom_catalog_contracts.embedding_gpu_control import (
    MAX_EMBEDDING_GPU_ALLOCATION_SECONDS,
    EmbeddingGpuAllocationRequest,
    EmbeddingGpuComputeGrant,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
    validate_embedding_gpu_batch_grant,
)
from eom_catalog_contracts.embedding_work_batch import (
    SupportedEmbeddingWorkBatchInput,
    parse_supported_embedding_work_batch_input,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    create_native_late_bound_descriptor_handoff,
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)

from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_RUNTIME_ROOT,
    NativeEmbeddingGpuBatchLaunchPins,
    native_embedding_gpu_batch_environment,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_HANDOFF_INVALID")


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


@dataclass(frozen=True, slots=True)
class PreparedEmbeddingGpuBatch:
    """Root-local observations, not compute/source authorization or persistent success."""

    launch: NativeEmbeddingGpuBatchLaunchPins
    request: EmbeddingGpuAllocationRequest
    input_epoch: tuple[int, ...]


def validate_embedding_gpu_batch_original(
    launch: NativeEmbeddingGpuBatchLaunchPins, request: EmbeddingGpuAllocationRequest
) -> bytes:
    """Current original controller only; required before staging or binding compute input."""
    raw = validate_embedding_gpu_batch_reconciliation_pins(launch, request)
    _require(launch.root_pid == os.getpid())
    return raw


def validate_embedding_gpu_batch_reconciliation_pins(
    launch: NativeEmbeddingGpuBatchLaunchPins, request: EmbeddingGpuAllocationRequest
) -> bytes:
    """Validate immutable original root metadata only, never permission to resume compute."""
    _require(os.getresuid() == (0, 0, 0) and type(launch) is NativeEmbeddingGpuBatchLaunchPins)
    launch.__post_init__()
    checked = parse_embedding_gpu_control(request)
    _require(type(checked) is EmbeddingGpuAllocationRequest)
    assert isinstance(checked, EmbeddingGpuAllocationRequest)
    raw = embedding_gpu_control_bytes(checked)
    _require(
        checked.allocation_attempt_id == "embeddingallocation_" + launch.attempt_hex
        and sha256_bytes(raw) == launch.allocation_raw_sha256
        and checked.purpose in ("INDEX", "REFERENCE_QUERY")
        and launch.backend
        == NativeEmbeddingBackendPins(
            checked.configuration.configuration_id,
            checked.configuration.configuration_revision_id,
            checked.configuration.configuration_sha256,
            checked.configuration.configuration_raw_sha256,
            checked.receipt_raw_sha256,
        )
    )
    return raw


def prepare_embedding_gpu_batch_handoff(
    launch: NativeEmbeddingGpuBatchLaunchPins, request: EmbeddingGpuAllocationRequest
) -> PreparedEmbeddingGpuBatch:
    """Exclusive original files; preserve every partial/existing attempt for reconciliation."""
    raw = validate_embedding_gpu_batch_original(launch, request)
    now = time.monotonic_ns()
    _require(
        now < request.expires_monotonic_ns <= now + MAX_EMBEDDING_GPU_ALLOCATION_SECONDS * 10**9
    )
    owner = fixed_owner_identity()
    create_native_late_bound_descriptor_handoff(
        GPU_BATCH_RUNTIME_ROOT, launch.attempt_hex, owner=owner
    )
    with protected_cpu_handoff_directory(
        GPU_BATCH_RUNTIME_ROOT / launch.attempt_hex,
        owner=owner,
        uid=0,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        create_protected_cpu_handoff_member(
            directory, "allocation.json", raw, owner_gid=owner.owner_gid, mode=0o600
        )
        create_protected_cpu_handoff_member(
            directory,
            "launch.env",
            native_embedding_gpu_batch_environment(launch),
            owner_gid=owner.owner_gid,
            mode=0o600,
        )
        initial = os.stat("input.json", dir_fd=directory, follow_symlinks=False)
        _require(initial.st_size == 0)
        os.fsync(directory)
        return PreparedEmbeddingGpuBatch(launch, request, _epoch(initial))


def bind_embedding_gpu_batch_handoff(
    prepared: PreparedEmbeddingGpuBatch,
    grant: EmbeddingGpuComputeGrant,
    batch: SupportedEmbeddingWorkBatchInput,
) -> None:
    """Journal original intent, then bind the same inode once; never truncate or repair.

    The actual root controller first proves READY/FDSTORE/unit identity and obtains
    current source-owner admission. This file primitive is not that admission.
    An exact completed replay only reads; partial/unknown output is an explicit error.
    """
    _require(type(prepared) is PreparedEmbeddingGpuBatch)
    original = validate_embedding_gpu_batch_original(prepared.launch, prepared.request)
    batch = parse_supported_embedding_work_batch_input(batch)
    raw = canonical_json_bytes(batch.model_dump(mode="json"))
    _require(
        time.monotonic_ns() < prepared.request.expires_monotonic_ns
        and batch.resource_profile_sha256 == prepared.launch.resource_profile_sha256
        and batch.timeout_seconds <= prepared.launch.timeout_seconds
        and batch.vector_max_bytes <= prepared.launch.vector_max_bytes
    )
    validate_embedding_gpu_batch_grant(
        prepared.request,
        grant,
        batch,
        input_raw_sha256=sha256_bytes(raw),
        input_byte_count=len(raw),
    )
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        GPU_BATCH_RUNTIME_ROOT / prepared.launch.attempt_hex,
        owner=owner,
        uid=0,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        _require(
            read_protected_cpu_handoff_member(
                directory,
                "allocation.json",
                uid=0,
                gid=owner.owner_gid,
                mode=0o600,
                maximum_bytes=32 * 1024,
            )
            == original
        )
        _require(
            read_protected_cpu_handoff_member(
                directory, "launch.env", uid=0, gid=owner.owner_gid, mode=0o600, maximum_bytes=4096
            )
            == native_embedding_gpu_batch_environment(prepared.launch)
        )
        intent = embedding_gpu_control_bytes(grant)
        try:
            create_protected_cpu_handoff_member(
                directory, "input-grant.json", intent, owner_gid=owner.owner_gid, mode=0o600
            )
        except CpuHandoffError as error:
            if not isinstance(error.__cause__, FileExistsError):
                raise
            _require(
                read_protected_cpu_handoff_member(
                    directory,
                    "input-grant.json",
                    uid=0,
                    gid=owner.owner_gid,
                    mode=0o600,
                    maximum_bytes=32 * 1024,
                )
                == intent
            )
            current = os.stat("input.json", dir_fd=directory, follow_symlinks=False)
            _require(_epoch(current)[:6] == prepared.input_epoch[:6])
            _require(
                read_protected_cpu_handoff_member(
                    directory,
                    "input.json",
                    uid=0,
                    gid=owner.owner_gid,
                    mode=0o600,
                    maximum_bytes=64 * 1024**2,
                )
                == raw
            )
            return
        os.fsync(directory)
        descriptor = os.open(
            "input.json", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
        )
        try:
            initial = os.fstat(descriptor)
            _require(
                _epoch(initial) == prepared.input_epoch
                and initial.st_size == 0
                and stat.S_ISREG(initial.st_mode)
                and initial.st_uid == 0
                and initial.st_gid == owner.owner_gid
                and stat.S_IMODE(initial.st_mode) == 0o600
                and initial.st_nlink == 1
                and fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND)
                == os.O_WRONLY
            )
            remaining = memoryview(raw)
            while remaining:
                count = os.write(descriptor, remaining[: 1024**2])
                _require(0 < count <= min(len(remaining), 1024**2))
                remaining = remaining[count:]
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            _require(_epoch(final)[:6] == prepared.input_epoch[:6] and final.st_size == len(raw))
            _require(
                _epoch(os.stat("input.json", dir_fd=directory, follow_symlinks=False))
                == _epoch(final)
            )
        finally:
            os.close(descriptor)
        _require(
            read_protected_cpu_handoff_member(
                directory,
                "input.json",
                uid=0,
                gid=owner.owner_gid,
                mode=0o600,
                maximum_bytes=64 * 1024**2,
            )
            == raw
        )
