"""One finite model lifetime over existing encoders; never launch, fallback or commit."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
    EmbeddingWorkBatchChild,
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    validate_incremental_embedding_result,
)

from eom_catalog_service.embedding_encoder_adapter import (
    encode_incremental_batch,
    encode_reference_query_batch,
)
from eom_catalog_service.embedding_execution_ports import (
    EncodedEmbeddingBatch,
    EncodedReferenceQueryBatch,
    NativeEmbeddingBackend,
)


class EmbeddingWorkBatchExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EmbeddingWorkBatchFence(Protocol):
    """Owner-supplied current source/lease checks, not labels supplied by the model."""

    def assert_batch_current(self, batch: EmbeddingWorkBatchInput) -> None:
        """Verify actual owner, pinned policy/resources, lease and hard unit deadline."""
        ...

    def assert_child_current(
        self, batch: EmbeddingWorkBatchInput, child: EmbeddingWorkBatchChild
    ) -> None:
        """Resolve/reauthorize the exact child context and its source/hash/partition."""
        ...


@dataclass(frozen=True, slots=True)
class EmbeddingWorkBatchExecutionResources:
    """Owner-observed finite limits, not an execution capability.

    The vector allowance is not a profile's aggregate file-output allowance. The
    owner must separately reserve metadata/file overhead under that actual limit.
    """

    resource_profile_sha256: str
    timeout_seconds: int
    vector_output_max_bytes: int

    def __post_init__(self) -> None:
        if (
            type(self.resource_profile_sha256) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.resource_profile_sha256) is None
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= MAX_EMBEDDING_WORK_BATCH_SECONDS
            or type(self.vector_output_max_bytes) is not int
            or not 4 <= self.vector_output_max_bytes <= MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES
        ):
            raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_RESOURCES_INVALID")


@dataclass(frozen=True, slots=True)
class EncodedEmbeddingWorkBatch:
    """Temporary ordered child outputs, not an Artifact or persistent success receipt."""

    request_sha256: str
    children: tuple[EncodedEmbeddingBatch | EncodedReferenceQueryBatch, ...]


def execute_embedding_work_batch(
    batch: EmbeddingWorkBatchInput,
    *,
    resources: EmbeddingWorkBatchExecutionResources,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    fence: EmbeddingWorkBatchFence,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> EncodedEmbeddingWorkBatch:
    """Reuse one model without changing per-child microbatches or source semantics.

    Time checks are cooperative around load/encodes. The admitting native owner must
    independently enforce the hard process deadline and CUDA cleanup/physical lease.
    On error no aggregate result is returned and no child is committed here. This
    candidate library has atomic aggregate semantics, not persisted per-child
    checkpoints: production resume/partial-output publication needs the existing
    owner journal and staged output handoff before this can be activated.
    """
    batch = parse_embedding_work_batch_input(batch)
    if type(resources) is not EmbeddingWorkBatchExecutionResources:
        raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_RESOURCES_INVALID")
    resources.__post_init__()
    if (
        resources.resource_profile_sha256 != batch.resource_profile_sha256
        or batch.timeout_seconds > resources.timeout_seconds
        or batch.vector_max_bytes > resources.vector_output_max_bytes
    ):
        raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_RESOURCES_MISMATCH")
    previous = clock_ns()
    if type(previous) is not int or previous < 0:
        raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_CLOCK_INVALID")
    deadline = previous + batch.timeout_seconds * 10**9

    def check_time() -> None:
        nonlocal previous
        now = clock_ns()
        if type(now) is not int or now < previous:
            raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_CLOCK_INVALID")
        previous = now
        if now >= deadline:
            raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_DEADLINE_EXCEEDED")

    fence.assert_batch_current(batch)
    for child in batch.children:
        fence.assert_child_current(batch, child)
    check_time()
    outputs: list[EncodedEmbeddingBatch | EncodedReferenceQueryBatch] = []
    completed = False
    with backend_scope() as backend:
        for child in batch.children:
            check_time()
            fence.assert_batch_current(batch)
            fence.assert_child_current(batch, child)
            request = child.request
            output: EncodedEmbeddingBatch | EncodedReferenceQueryBatch
            if isinstance(request, EmbeddingReferenceQueryInputV11):
                output = encode_reference_query_batch(request, backend)
                validate_reference_query_result_v11(request, output.result)
            else:
                output = encode_incremental_batch(request, backend)
                validate_incremental_embedding_result(request, output.result)
            check_time()
            fence.assert_child_current(batch, child)
            outputs.append(output)
        fence.assert_batch_current(batch)
        check_time()
        completed = True
    check_time()
    if not completed or len(outputs) != len(batch.children):
        raise EmbeddingWorkBatchExecutionError("EMBEDDING_WORK_BATCH_INCOMPLETE")
    fence.assert_batch_current(batch)
    for child in batch.children:
        fence.assert_child_current(batch, child)
    check_time()
    return EncodedEmbeddingWorkBatch(batch.request_sha256, tuple(outputs))
