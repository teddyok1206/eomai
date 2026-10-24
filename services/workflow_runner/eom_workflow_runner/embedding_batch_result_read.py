"""Actual owner verifies one original CUDA batch output; no launch, SQL writes or NAS commit."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts.embedding_gpu_control import validate_embedding_gpu_batch_grant
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    EmbeddingWorkBatchResult,
    parse_embedding_work_batch_result,
)
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_workspace import StagedOwnerEmbeddingBatch
from eom_catalog_service.embedding_gpu_batch_launch import GPU_BATCH_RUNTIME_ROOT
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from eom_workflow.embedding_batch_owner_control import (
    EmbeddingBatchRootCompleted,
    EmbeddingBatchRootReady,
    validate_embedding_batch_owner_completion,
)

from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_RESULT_READ_INVALID")


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


def _owner() -> None:
    identity = fixed_owner_identity()
    _require(
        os.getresuid() == (identity.owner_uid,) * 3 and os.getresgid() == (identity.owner_gid,) * 3
    )


def _authorize(source: CatalogEmbeddingBatchSourceAuthorization) -> None:
    callback: Callable[[], object] = source.authorize_batch
    _require(callback() is None)


@dataclass(frozen=True, slots=True)
class VerifiedLocalEmbeddingBatchResult:
    """Root-local verification result, not a durable permission or child publication.

    Child memoryviews share the one bounded local binary materialization. The
    producing application must retain current source/lease checks at publication.
    """

    staged: StagedOwnerEmbeddingBatch
    ready: EmbeddingBatchRootReady
    completed: EmbeddingBatchRootCompleted
    result: EmbeddingWorkBatchResult
    child_vectors: tuple[memoryview, ...]
    result_epoch: tuple[int, ...]
    vectors_epoch: tuple[int, ...]

    def assert_current(self) -> None:
        _owner()
        self.staged.assert_current()
        identity = fixed_owner_identity()
        instance = self.completed.allocation_attempt_id.removeprefix("embeddingallocation_")
        with protected_cpu_handoff_directory(
            GPU_BATCH_RUNTIME_ROOT / instance,
            owner=identity,
            uid=0,
            gid=identity.owner_gid,
            mode=0o750,
        ) as directory:
            _require(
                _epoch(os.stat("result.json", dir_fd=directory, follow_symlinks=False))
                == self.result_epoch
                and _epoch(os.stat("vectors.f32", dir_fd=directory, follow_symlinks=False))
                == self.vectors_epoch
            )

    def receipt(
        self, parent_plan_job_id: str, channel: EmbeddingBatchOwnerChannel
    ) -> EmbeddingBatchExecutionReceipt:
        """Build small verified metadata only; caller separately validates parent history."""
        self.assert_current()
        _require(
            channel.acknowledged_completion == self.completed
            and channel.request.parent_request_sha256 == self.staged.notice.binding.request_sha256
        )
        children: list[dict[str, Any]] = []
        for ordinal, (source, child) in enumerate(
            zip(self.staged.batch.children, self.result.children, strict=True)
        ):
            output, shard = child.result, child.result.shard
            children.append(
                dict(
                    ordinal=ordinal,
                    native_job_id=output.job_id,
                    input_sha256=source.request.request_sha256,
                    result_sha256=output.result_sha256,
                    shard_sha256=shard.shard_sha256,
                    binary_sha256=shard.binary.sha256,
                    vector_offset=child.vector_offset,
                    vector_byte_count=shard.binary.byte_count,
                    row_count=shard.row_count,
                    dimension=shard.dimension,
                )
            )
        body = dict(
            schema_version="embedding-batch-execution-receipt/1.0",
            purpose=channel.request.purpose,
            device="CUDA",
            parent_plan_job_id=parent_plan_job_id,
            scope=self.staged.batch.scope.model_dump(mode="json"),
            allocation=channel.request.model_dump(mode="json"),
            ready=self.ready.model_dump(mode="json"),
            bound=self.staged.notice.model_dump(mode="json"),
            completed=self.completed.model_dump(mode="json"),
            children=children,
        )
        return EmbeddingBatchExecutionReceipt.model_validate(
            body | {"receipt_sha256": content_sha256(body)}
        )


def read_verified_embedding_batch_result(
    channel: EmbeddingBatchOwnerChannel,
    ready: EmbeddingBatchRootReady,
    staged: StagedOwnerEmbeddingBatch,
    *,
    authorization: CatalogEmbeddingBatchSourceAuthorization,
) -> VerifiedLocalEmbeddingBatchResult:
    """Original OWNER channel + current actual Catalog source/lease authority are required."""
    _owner()
    _require(type(channel) is EmbeddingBatchOwnerChannel and channel.side == "OWNER")
    _require(
        type(staged) is StagedOwnerEmbeddingBatch
        and type(authorization) is CatalogEmbeddingBatchSourceAuthorization
    )
    _require(authorization.batch_request_sha256 == staged.batch.request_sha256)
    peer = channel.require_direct_peer()
    _require((peer.uid, peer.gid) == (0, 0))
    completed = channel.received_completion
    validate_embedding_batch_owner_completion(channel.request, ready, staged.notice, completed)
    validate_embedding_gpu_batch_grant(
        channel.request,
        completed.grant,
        staged.batch,
        input_raw_sha256=staged.notice.input_raw_sha256,
        input_byte_count=staged.notice.input_byte_count,
    )
    _authorize(authorization)
    staged.assert_current()
    identity = fixed_owner_identity()
    instance = completed.allocation_attempt_id.removeprefix("embeddingallocation_")
    with protected_cpu_handoff_directory(
        GPU_BATCH_RUNTIME_ROOT / instance, owner=identity, uid=0, gid=identity.owner_gid, mode=0o750
    ) as directory:
        raw_epoch = _epoch(os.stat("result.json", dir_fd=directory, follow_symlinks=False))
        vector_epoch = _epoch(os.stat("vectors.f32", dir_fd=directory, follow_symlinks=False))
        raw = read_protected_cpu_handoff_member(
            directory,
            "result.json",
            uid=0,
            gid=identity.owner_gid,
            mode=0o640,
            maximum_bytes=completed.result_byte_count,
        )
        vectors = read_protected_cpu_handoff_member(
            directory,
            "vectors.f32",
            uid=0,
            gid=identity.owner_gid,
            mode=0o640,
            maximum_bytes=completed.vectors_byte_count,
        )
        _require(
            len(raw) == completed.result_byte_count
            and sha256_bytes(raw) == completed.result_raw_sha256
        )
        result = parse_embedding_work_batch_result(
            parse_rootlocal_evidence_document(raw, completed.result_byte_count)
        )
        _require(
            canonical_json_bytes(result.model_dump(mode="json")) == raw
            and result.result_sha256 == completed.result_sha256
        )
        _require(
            len(vectors) == completed.vectors_byte_count
            and result.vectors.sha256 == completed.vectors_sha256
        )
        ranges = validate_embedding_work_batch_binary(staged.batch, result, vectors)
    _authorize(authorization)
    verified = VerifiedLocalEmbeddingBatchResult(
        staged, ready, completed, result, ranges, raw_epoch, vector_epoch
    )
    verified.assert_current()
    return verified
