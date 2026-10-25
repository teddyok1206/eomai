"""Fixed owner allocation metadata for the root rendezvous; never source or compute authority."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_gpu_control import (
    MAX_EMBEDDING_GPU_ALLOCATION_SECONDS,
    MAX_EMBEDDING_GPU_CONTROL_BYTES,
    EmbeddingGpuAllocationRequest,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control_bytes,
)
from eom_orchestrator.inference_transfer_cpu_handoff import (
    claim_native_cpu_dispatch,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)

from eom_catalog_service.embedding_gpu_batch_launch import native_embedding_gpu_batch_unit

BATCH_CONTROL_ROOT = Path("/var/lib/eom-workflow-runner/embedding-batch-control")
BATCH_CONTROL_TEMPLATE = "eom-embedding-native-gpu-batch-owner@.service"
_MEMBERS = frozenset({"allocation.json", ".launch-started", ".dispatch-attempted", "control.sock"})


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_CONTROL_WORKSPACE_INVALID")


def embedding_batch_control_unit(attempt_hex: str) -> str:
    native_embedding_gpu_batch_unit(attempt_hex)
    return BATCH_CONTROL_TEMPLATE.replace("@.service", "@" + attempt_hex + ".service")


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


def _deadline(request: EmbeddingGpuAllocationRequest) -> None:
    now = time.monotonic_ns()
    _require(
        now < request.expires_monotonic_ns <= now + MAX_EMBEDDING_GPU_ALLOCATION_SECONDS * 10**9
    )


def _markers(directory: int, request: EmbeddingGpuAllocationRequest, *, dispatched: bool) -> None:
    owner = fixed_owner_identity()
    payload = request.message_sha256.encode("ascii")
    names = (".launch-started", ".dispatch-attempted") if dispatched else (".launch-started",)
    for name in names:
        _require(
            read_protected_cpu_handoff_member(
                directory,
                name,
                uid=owner.owner_uid,
                gid=owner.owner_gid,
                mode=0o600,
                maximum_bytes=71,
            )
            == payload
        )


@dataclass(frozen=True, slots=True)
class StagedEmbeddingBatchControl:
    request: EmbeddingGpuAllocationRequest
    allocation_epoch: tuple[int, ...]

    @property
    def attempt_hex(self) -> str:
        return self.request.allocation_attempt_id.removeprefix("embeddingallocation_")

    @property
    def path(self) -> Path:
        return BATCH_CONTROL_ROOT / self.attempt_hex

    def assert_current(self) -> None:
        owner = fixed_owner_identity()
        _require(os.geteuid() in (0, owner.owner_uid))
        _deadline(self.request)
        with protected_cpu_handoff_directory(
            self.path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            members = set(os.listdir(directory))
            _require(
                members.issubset(_MEMBERS)
                and _epoch(os.stat("allocation.json", dir_fd=directory, follow_symlinks=False))
                == self.allocation_epoch
            )
            _markers(directory, self.request, dispatched=".dispatch-attempted" in members)


def stage_embedding_batch_control(
    request: EmbeddingGpuAllocationRequest,
) -> StagedEmbeddingBatchControl:
    """Metadata only, after official parent admission; never restarts an existing attempt."""
    owner = fixed_owner_identity()
    _require(os.getresuid() == (owner.owner_uid,) * 3 and os.getresgid() == (owner.owner_gid,) * 3)
    request = EmbeddingGpuAllocationRequest.model_validate(request)
    _deadline(request)
    attempt = request.allocation_attempt_id.removeprefix("embeddingallocation_")
    embedding_batch_control_unit(attempt)
    path = ensure_protected_cpu_owner_workspace(BATCH_CONTROL_ROOT, attempt, owner=owner)
    with protected_cpu_handoff_directory(
        path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _require(set(os.listdir(directory)).issubset(_MEMBERS))
        write_protected_cpu_owner_member(
            directory, "allocation.json", embedding_gpu_control_bytes(request), owner=owner
        )
        write_protected_cpu_owner_member(
            directory, ".launch-started", request.message_sha256.encode("ascii"), owner=owner
        )
        result = StagedEmbeddingBatchControl(
            request, _epoch(os.stat("allocation.json", dir_fd=directory, follow_symlinks=False))
        )
    result.assert_current()
    return result


def claim_embedding_batch_control_dispatch(staged: StagedEmbeddingBatchControl) -> None:
    """No-clobber marker before the one permitted systemctl effect; no failure→retry reset."""
    staged.assert_current()
    owner = fixed_owner_identity()
    _require(os.getresuid() == (owner.owner_uid,) * 3 and os.getresgid() == (owner.owner_gid,) * 3)
    claim_native_cpu_dispatch(staged.path, staged.request.message_sha256, owner=owner)
    staged.assert_current()


def read_embedding_batch_control(attempt_hex: str) -> StagedEmbeddingBatchControl:
    """Root reads the fixed original metadata only; no supplied path or actor is accepted."""
    _require(os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0))
    embedding_batch_control_unit(attempt_hex)
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        BATCH_CONTROL_ROOT / attempt_hex,
        owner=owner,
        uid=owner.owner_uid,
        gid=owner.owner_gid,
        mode=0o700,
    ) as directory:
        _require(set(os.listdir(directory)).issubset(_MEMBERS))
        raw = read_protected_cpu_handoff_member(
            directory,
            "allocation.json",
            uid=owner.owner_uid,
            gid=owner.owner_gid,
            mode=0o600,
            maximum_bytes=MAX_EMBEDDING_GPU_CONTROL_BYTES,
        )
        request = parse_embedding_gpu_control_bytes(raw)
        _require(type(request) is EmbeddingGpuAllocationRequest)
        assert isinstance(request, EmbeddingGpuAllocationRequest)
        _require(request.allocation_attempt_id == "embeddingallocation_" + attempt_hex)
        _markers(directory, request, dispatched=True)
        result = StagedEmbeddingBatchControl(
            request, _epoch(os.stat("allocation.json", dir_fd=directory, follow_symlinks=False))
        )
    result.assert_current()
    return result
