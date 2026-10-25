"""CUDA child output materialization at the existing canonical publication boundary."""

from __future__ import annotations

import os
from pathlib import Path

from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingResult,
    validate_incremental_embedding_result,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    write_protected_cpu_owner_member,
)
from eom_orchestrator.native_embedding_index_handoff import OWNER_ROOT

from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    OwnedDocumentEmbedding,
)

DOCUMENT_PUBLICATION_ROOT = OWNER_ROOT
_MEMBERS = frozenset({"input.json", "result.json", "vectors.f32", "shard.json"})


def stage_batch_document_publication(
    work: OwnedDocumentEmbedding, result: IncrementalEmbeddingResult, vectors: memoryview
) -> DocumentEmbeddingOutput:
    """No compute/SQL/NAS; exact replay does not overwrite partial or foreign files."""
    if type(work) is not OwnedDocumentEmbedding or work.request.space.runtime.device != "CUDA":
        raise ValueError("DOCUMENT_BATCH_MATERIAL_INVALID")
    validate_incremental_embedding_result(work.request, result)
    if not (
        type(vectors) is memoryview
        and vectors.readonly
        and vectors.ndim == 1
        and vectors.c_contiguous
        and vectors.format == "B"
    ):
        raise ValueError("DOCUMENT_BATCH_MATERIAL_INVALID")
    # The only copy is the explicit aggregate -> existing child commit workspace.
    binary = vectors.tobytes()
    read_unit_vectors(
        binary,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    owner = fixed_owner_identity()
    if not (os.getresuid() == (owner.owner_uid,) * 3 and os.getresgid() == (owner.owner_gid,) * 3):
        raise ValueError("DOCUMENT_BATCH_MATERIAL_INVALID")
    try:
        path = ensure_protected_cpu_owner_workspace(
            DOCUMENT_PUBLICATION_ROOT,
            work.association.intent.native_launch_job_id.removeprefix("job_"),
            owner=owner,
        )
        with protected_cpu_handoff_directory(
            path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            if not set(os.listdir(directory)).issubset(_MEMBERS):
                raise ValueError("DOCUMENT_BATCH_MATERIAL_INVALID")
            for name, raw in (
                ("input.json", canonical_json_bytes(work.request.model_dump(mode="json"))),
                ("result.json", canonical_json_bytes(result.model_dump(mode="json"))),
                ("vectors.f32", binary),
            ):
                write_protected_cpu_owner_member(directory, name, raw, owner=owner)
    except CpuHandoffError:
        raise ValueError("DOCUMENT_BATCH_MATERIAL_INVALID") from None
    return DocumentEmbeddingOutput(result, Path(path))
