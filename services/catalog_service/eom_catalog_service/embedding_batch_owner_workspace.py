"""Fixed owner input materialization for one original allocation; no SQL, launch or NAS."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_BYTES,
    SupportedEmbeddingWorkBatchInput,
    parse_supported_embedding_work_batch_input,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from eom_workflow.embedding_batch_owner_control import (
    MAX_BATCH_OWNER_CONTROL_BYTES,
    EmbeddingBatchOwnerBound,
    EmbeddingBatchRootReady,
    embedding_batch_owner_control_bytes,
    validate_embedding_batch_owner_context,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchBound

from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks

BATCH_OWNER_ROOT = Path("/var/lib/eom-workflow-runner/embedding-work-batches")
_INPUT = "batch-input.json"
_BOUND = "batch-bound.json"


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_OWNER_WORKSPACE_INVALID")


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


def validate_embedding_owner_bound_input(
    request: EmbeddingGpuAllocationRequest,
    notice: EmbeddingBatchOwnerBound,
    batch: SupportedEmbeddingWorkBatchInput,
) -> None:
    """Pure ordered input/reference closure, not current source or physical admission."""
    request = EmbeddingGpuAllocationRequest.model_validate(request)
    notice = EmbeddingBatchOwnerBound.model_validate(notice)
    batch = parse_supported_embedding_work_batch_input(batch)
    _validate_checked_binding(request, notice, batch)


def _validate_checked_binding(
    request: EmbeddingGpuAllocationRequest,
    notice: EmbeddingBatchOwnerBound,
    batch: SupportedEmbeddingWorkBatchInput,
) -> None:
    binding = notice.binding
    _require(
        binding.request_sha256 == request.parent_request_sha256
        and binding.batch_request_sha256 == batch.request_sha256
        and binding.resource_profile_sha256 == batch.resource_profile_sha256
        and batch.purpose
        == {"INDEX": "DOCUMENT", "REFERENCE_QUERY": "REFERENCE_QUERY"}.get(request.purpose)
        and tuple(child.native_job_id for child in binding.children)
        == tuple(child.request.job_id for child in batch.children)
        and tuple(child.native_input_sha256 for child in binding.children)
        == tuple(child.request.request_sha256 for child in batch.children)
    )


@dataclass(frozen=True, slots=True)
class StagedOwnerEmbeddingBatch:
    """Original checked local inputs only; never canonical source or a compute grant."""

    notice: EmbeddingBatchOwnerBound
    batch: SupportedEmbeddingWorkBatchInput
    input_epoch: tuple[int, ...]
    bound_epoch: tuple[int, ...]

    def assert_current(self) -> None:
        owner = fixed_owner_identity()
        _require(os.geteuid() in (0, owner.owner_uid))
        instance = self.notice.allocation_attempt_id.removeprefix("embeddingallocation_")
        with protected_cpu_handoff_directory(
            BATCH_OWNER_ROOT / instance,
            owner=owner,
            uid=owner.owner_uid,
            gid=owner.owner_gid,
            mode=0o700,
        ) as directory:
            _require(
                set(os.listdir(directory)) == {_INPUT, _BOUND}
                and _epoch(os.stat(_INPUT, dir_fd=directory, follow_symlinks=False))
                == self.input_epoch
                and _epoch(os.stat(_BOUND, dir_fd=directory, follow_symlinks=False))
                == self.bound_epoch
            )


def stage_owner_embedding_batch(
    request: EmbeddingGpuAllocationRequest,
    ready: EmbeddingBatchRootReady,
    binding: EmbeddingBatchBound,
    batch: SupportedEmbeddingWorkBatchInput,
) -> StagedOwnerEmbeddingBatch:
    """Call after real owner BOUND/source checks; exact replay never truncates a partial file."""
    owner = fixed_owner_identity()
    _require(os.getresuid() == (owner.owner_uid,) * 3 and os.getresgid() == (owner.owner_gid,) * 3)
    request = EmbeddingGpuAllocationRequest.model_validate(request)
    ready = EmbeddingBatchRootReady.model_validate(ready)
    _require(time.monotonic_ns() < request.expires_monotonic_ns)
    validate_embedding_batch_owner_context(request, ready.controller_release, ready)
    binding = EmbeddingBatchBound.model_validate(binding)
    batch = parse_supported_embedding_work_batch_input(batch)
    raw = canonical_json_bytes(batch.model_dump(mode="json"))
    _require(0 < len(raw) <= MAX_EMBEDDING_WORK_BATCH_BYTES)
    pid = os.getpid()
    birth = embedding_batch_owner_start_ticks(pid, uid=owner.owner_uid, gid=owner.owner_gid)
    body = dict(
        schema_version="embedding-batch-owner-control/1.0",
        message_type="OWNER_BOUND",
        allocation_attempt_id=request.allocation_attempt_id,
        allocation_request_sha256=request.message_sha256,
        controller_release=ready.controller_release,
        binding=binding.model_dump(mode="json"),
        ready_message_sha256=ready.message_sha256,
        input_raw_sha256=sha256_bytes(raw),
        input_byte_count=len(raw),
        owner_pid=pid,
        owner_start_ticks=birth,
    )
    notice = EmbeddingBatchOwnerBound.model_validate(
        body | {"message_sha256": content_sha256(body)}
    )
    _validate_checked_binding(request, notice, batch)
    workspace = ensure_protected_cpu_owner_workspace(
        BATCH_OWNER_ROOT,
        request.allocation_attempt_id.removeprefix("embeddingallocation_"),
        owner=owner,
    )
    with protected_cpu_handoff_directory(
        workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _require(set(os.listdir(directory)).issubset({_INPUT, _BOUND}))
        write_protected_cpu_owner_member(directory, _INPUT, raw, owner=owner)
        write_protected_cpu_owner_member(
            directory, _BOUND, embedding_batch_owner_control_bytes(notice), owner=owner
        )
        staged = StagedOwnerEmbeddingBatch(
            notice,
            batch,
            _epoch(os.stat(_INPUT, dir_fd=directory, follow_symlinks=False)),
            _epoch(os.stat(_BOUND, dir_fd=directory, follow_symlinks=False)),
        )
    _require(
        embedding_batch_owner_start_ticks(pid, uid=owner.owner_uid, gid=owner.owner_gid) == birth
        and time.monotonic_ns() < request.expires_monotonic_ns
    )
    staged.assert_current()
    return staged


def read_owner_embedding_batch(
    request: EmbeddingGpuAllocationRequest, notice: EmbeddingBatchOwnerBound
) -> StagedOwnerEmbeddingBatch:
    """Actual root/owner reads one fixed original attempt; arbitrary paths are not accepted."""
    owner = fixed_owner_identity()
    _require(os.geteuid() in (0, owner.owner_uid))
    request = EmbeddingGpuAllocationRequest.model_validate(request)
    notice = EmbeddingBatchOwnerBound.model_validate(notice)
    validate_embedding_batch_owner_context(request, notice.controller_release, notice)
    _require(
        embedding_batch_owner_start_ticks(
            notice.owner_pid, uid=owner.owner_uid, gid=owner.owner_gid
        )
        == notice.owner_start_ticks
    )
    return _read_original_owner_batch(request, notice)


def read_completed_owner_embedding_batch(
    receipt: EmbeddingBatchExecutionReceipt,
) -> StagedOwnerEmbeddingBatch:
    """Read a retired original input, not a live owner's PID or a new compute grant.

    The caller resolves this receipt canonically and independently holds current
    source authority. No arbitrary path, latest attempt or expired PID is used.
    """
    owner = fixed_owner_identity()
    _require(os.getresuid() == (owner.owner_uid,) * 3)
    _require(os.getresgid() == (owner.owner_gid,) * 3)
    receipt = EmbeddingBatchExecutionReceipt.model_validate(receipt)
    return _read_original_owner_batch(receipt.allocation, receipt.bound)


def _read_original_owner_batch(
    request: EmbeddingGpuAllocationRequest, notice: EmbeddingBatchOwnerBound
) -> StagedOwnerEmbeddingBatch:
    owner = fixed_owner_identity()
    instance = notice.allocation_attempt_id.removeprefix("embeddingallocation_")
    with protected_cpu_handoff_directory(
        BATCH_OWNER_ROOT / instance,
        owner=owner,
        uid=owner.owner_uid,
        gid=owner.owner_gid,
        mode=0o700,
    ) as directory:
        _require(set(os.listdir(directory)) == {_INPUT, _BOUND})
        raw_bound = read_protected_cpu_handoff_member(
            directory,
            _BOUND,
            uid=owner.owner_uid,
            gid=owner.owner_gid,
            mode=0o600,
            maximum_bytes=MAX_BATCH_OWNER_CONTROL_BYTES,
        )
        _require(raw_bound == embedding_batch_owner_control_bytes(notice))
        before = _epoch(os.stat(_INPUT, dir_fd=directory, follow_symlinks=False))
        raw = read_protected_cpu_handoff_member(
            directory,
            _INPUT,
            uid=owner.owner_uid,
            gid=owner.owner_gid,
            mode=0o600,
            maximum_bytes=MAX_EMBEDDING_WORK_BATCH_BYTES,
        )
        _require(
            len(raw) == notice.input_byte_count and sha256_bytes(raw) == notice.input_raw_sha256
        )
        batch = parse_supported_embedding_work_batch_input(
            parse_rootlocal_evidence_document(raw, MAX_EMBEDDING_WORK_BATCH_BYTES)
        )
        _require(canonical_json_bytes(batch.model_dump(mode="json")) == raw)
        _validate_checked_binding(request, notice, batch)
        _require(before == _epoch(os.stat(_INPUT, dir_fd=directory, follow_symlinks=False)))
        staged = StagedOwnerEmbeddingBatch(
            notice, batch, before, _epoch(os.stat(_BOUND, dir_fd=directory, follow_symlinks=False))
        )
    staged.assert_current()
    return staged
