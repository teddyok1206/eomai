"""Synthetic numerical/root metadata only; never actual source, GPU or root authority."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from eom_catalog_contracts.embedding_work_batch_result import build_embedding_work_batch_result
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from eom_workflow.embedding_batch_owner_control import EmbeddingBatchRootCompleted

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import control_frames
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_work_batch import Fence


def execution_case(*, planned=None):
    frames = control_frames(
        **(
            {}
            if planned is None
            else dict(
                request=planned.allocation.control_request,
                batch=planned.batch,
                binding=planned.bound,
            )
        )
    )
    batch = frames.batch
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    backend.threads = batch.children[0].request.threads

    @contextmanager
    def scope():
        yield backend

    encoded = execute_embedding_work_batch(
        batch,
        resources=EmbeddingWorkBatchExecutionResources(
            batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
        ),
        backend_scope=scope,
        fence=Fence(),
    )
    vectors = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        batch, tuple(child.result for child in encoded.children), sha256_bytes(vectors)
    )
    raw = canonical_json_bytes(result.model_dump(mode="json"))
    completed = EmbeddingBatchRootCompleted.model_validate(
        seal(
            frames.completed.model_dump(mode="json")
            | dict(
                result_raw_sha256=sha256_bytes(raw),
                result_sha256=result.result_sha256,
                result_byte_count=len(raw),
                vectors_sha256=sha256_bytes(vectors),
                vectors_byte_count=len(vectors),
            ),
            "message_sha256",
        )
    )
    children = [
        dict(
            ordinal=ordinal,
            native_job_id=child.result.job_id,
            input_sha256=source.request.request_sha256,
            result_sha256=child.result.result_sha256,
            shard_sha256=child.result.shard.shard_sha256,
            binary_sha256=child.result.shard.binary.sha256,
            vector_offset=child.vector_offset,
            vector_byte_count=child.result.shard.binary.byte_count,
            row_count=child.result.shard.row_count,
            dimension=child.result.shard.dimension,
        )
        for ordinal, (source, child) in enumerate(zip(batch.children, result.children, strict=True))
    ]
    receipt = EmbeddingBatchExecutionReceipt.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-execution-receipt/1.0",
                purpose=frames.request.purpose,
                device="CUDA",
                parent_plan_job_id="job_" + "9" * 32,
                scope=batch.scope.model_dump(mode="json"),
                allocation=frames.request.model_dump(mode="json"),
                ready=frames.ready.model_dump(mode="json"),
                bound=frames.bound.model_dump(mode="json"),
                completed=completed.model_dump(mode="json"),
                children=children,
            ),
            "receipt_sha256",
        )
    )
    return SimpleNamespace(
        frames=frames,
        batch=batch,
        result=result,
        vectors=vectors,
        raw=raw,
        completed=completed,
        receipt=receipt,
    )
