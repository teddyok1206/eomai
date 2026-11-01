"""One protected owner-local file boundary for public/private GPU query publication."""

from __future__ import annotations

import os
from pathlib import Path

from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    ensure_protected_cpu_owner_workspace,
    protected_cpu_handoff_directory,
    write_protected_cpu_owner_member,
)
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryNativeInput,
    SupportedReferenceQueryNativeResult,
)

_MEMBERS = frozenset({"input.json", "result.json", "vectors.f32", "shard.json"})


class QueryBatchPublicationFilesError(ValueError):
    def __init__(self) -> None:
        super().__init__("QUERY_BATCH_PUBLICATION_FILES_INVALID")


def require_query_batch_publication_layout(root: Path, owner: CpuHandoffIdentity) -> None:
    """Fixed composition locations/identity only, never source or launch authority."""
    if os.getresuid() != (owner.owner_uid,) * 3 or os.getresgid() != (owner.owner_gid,) * 3:
        raise QueryBatchPublicationFilesError()
    try:
        with protected_cpu_handoff_directory(
            root, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ):
            pass
    except CpuHandoffError:
        raise QueryBatchPublicationFilesError() from None


def stage_query_batch_publication_files(
    root: Path,
    owner: CpuHandoffIdentity,
    request: SupportedReferenceQueryNativeInput,
    result: SupportedReferenceQueryNativeResult,
    vectors: memoryview,
) -> None:
    """Caller has validated the exact purpose/input/result; no NAS/DB/launch mutation."""
    require_query_batch_publication_layout(root, owner)
    if not (
        type(vectors) is memoryview
        and vectors.readonly
        and vectors.ndim == 1
        and vectors.c_contiguous
        and vectors.format == "B"
    ):
        raise QueryBatchPublicationFilesError()
    # One aggregate→child copy at the explicit publication boundary.
    binary = vectors.tobytes()
    read_unit_vectors(
        binary,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    try:
        path = ensure_protected_cpu_owner_workspace(
            root, request.job_id.removeprefix("job_"), owner=owner
        )
        with protected_cpu_handoff_directory(
            path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            if not set(os.listdir(directory)).issubset(_MEMBERS):
                raise QueryBatchPublicationFilesError()
            for name, raw in (
                ("input.json", canonical_json_bytes(request)),
                ("result.json", canonical_json_bytes(result)),
                ("vectors.f32", binary),
            ):
                write_protected_cpu_owner_member(directory, name, raw, owner=owner)
    except CpuHandoffError:
        raise QueryBatchPublicationFilesError() from None
