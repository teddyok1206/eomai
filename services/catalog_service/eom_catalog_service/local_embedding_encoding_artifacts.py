"""Exact owned-input/shared-result read through Catalog's committed Artifact boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_embedding_shard,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EMBEDDING_RESULT_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import OWNED_INPUT_ARTIFACT_TYPE
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingCompletedEvent,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingOwnedJob,
    validate_embedding_encoding_completions,
)
from sqlalchemy.orm import Session

from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class ResolvedLocalEncodingResult:
    request: IncrementalEmbeddingInput
    result: IncrementalEmbeddingResult


def _canonical_document(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError("LOCAL_EMBEDDING_ARTIFACT_NONCANONICAL")
    return value


class CatalogLocalEmbeddingEncodingArtifacts:
    """Each caller must admit its current explicit source/command scope before reading."""

    def __init__(self, session: Session, settings: CatalogSettings) -> None:
        self.reader = PinnedArtifactReadContext(session, settings)

    def resolve_input(
        self, association: LocalEmbeddingLaunchAssociation
    ) -> IncrementalEmbeddingInput:
        association = LocalEmbeddingLaunchAssociation.model_validate(association)
        pointer = association.owned_input
        self.reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        self.reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            ("input.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = self.reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(OWNED_INPUT_ARTIFACT_TYPE,),
            expected_primary_file="input.json",
            max_bytes=MAX_EMBEDDING_INPUT_BYTES,
        ).payload
        request = parse_incremental_embedding_input(_canonical_document(raw))
        if (
            request.job_id != association.intent.native_launch_job_id
            or request.request_sha256 != association.owned_input_request_sha256
            or request.input_set_sha256 != association.owned_input_set_sha256
            or tuple(row.encoding for row in request.rows)
            != tuple(job.request.encoding for job in association.owned_jobs)
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNED_INPUT_MISMATCH")
        return request

    def resolve_result(
        self,
        association: LocalEmbeddingLaunchAssociation,
        events: tuple[EmbeddingEncodingCompletedEvent, ...],
    ) -> ResolvedLocalEncodingResult:
        if type(events) is not tuple or not 1 <= len(events) <= 1024:
            raise ValueError("LOCAL_EMBEDDING_COMPLETION_BATCH_INVALID")
        checked = tuple(EmbeddingEncodingCompletedEvent.model_validate(e) for e in events)
        pointers = {
            (e.receipt.result_manifest, e.receipt.shard_manifest, e.receipt.binary_member)
            for e in checked
        }
        if len(pointers) != 1:
            raise ValueError("LOCAL_EMBEDDING_SHARED_FILE_SET_MISMATCH")
        request = self.resolve_input(association)
        result = self._resolve_file_set(*next(iter(pointers)))
        validate_incremental_embedding_result(request, result)
        validate_embedding_encoding_completions(checked, association, request, result)
        return ResolvedLocalEncodingResult(request, result)

    def verify_shared_rows(
        self, rows: tuple[tuple[LocalEmbeddingOwnedJob, EmbeddingEncodingCompletedEvent], ...]
    ) -> None:
        """Verify caller-selected rows without reading the winner's input/source plan.

        Group by exact file-set pointers: one bounded member read/decode per shared
        Artifact, never one full shard read per row. No vectors or winner count is
        returned; this internal read does not disclose a historical source scope.
        """
        self.resolve_shared_row_shards(rows)

    def resolve_shared_row_shards(
        self, rows: tuple[tuple[LocalEmbeddingOwnedJob, EmbeddingEncodingCompletedEvent], ...]
    ) -> tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]:
        """Trusted index assembly metadata, NEVER a public user/worker disclosure.

        Same exact selected-row proof as verify_shared_rows. No input/source plan or
        vector bytes are returned. Full internal shard metadata is for canonical
        reference assembly only, not a transferable grant or disclosed coverage.
        """
        if type(rows) is not tuple or not 1 <= len(rows) <= 1024:
            raise ValueError("LOCAL_EMBEDDING_SHARED_ROW_BATCH_INVALID")
        selected_keys: set[str] = set()
        groups: dict[
            tuple[ArtifactMemberPointer, ArtifactMemberPointer, ArtifactMemberPointer],
            list[tuple[LocalEmbeddingOwnedJob, EmbeddingEncodingCompletedEvent]],
        ] = {}
        for owned, completion in rows:
            owned = LocalEmbeddingOwnedJob.model_validate(owned)
            completion = EmbeddingEncodingCompletedEvent.model_validate(completion)
            if owned != completion.owned_job:
                raise ValueError("LOCAL_EMBEDDING_SHARED_ROW_IDENTITY_INVALID")
            key = owned.request.encoding.encoding_sha256
            if key in selected_keys:
                raise ValueError("LOCAL_EMBEDDING_SHARED_ROW_DUPLICATED")
            selected_keys.add(key)
            receipt = completion.receipt
            group = receipt.result_manifest, receipt.shard_manifest, receipt.binary_member
            groups.setdefault(group, []).append((owned, completion))
        self.reader.prefetch(
            tuple(sorted({(key[0].artifact_id, key[0].artifact_revision_id) for key in groups}))
        )
        resolved = []
        for (result_pointer, shard_pointer, binary_pointer), selected in groups.items():
            result = self._resolve_file_set(result_pointer, shard_pointer, binary_pointer)
            shard = result.shard
            for owned, completion in selected:
                receipt = completion.receipt
                ordinal = receipt.row_ref.row_index
                if (
                    ordinal >= len(shard.rows)
                    or shard.rows[ordinal] != owned.request.encoding
                    or shard.space != owned.request.space
                    or result.job_id != completion.intent.native_launch_job_id
                    or receipt.native_launch_job_id != result.job_id
                    or receipt.result_sha256 != result.result_sha256
                    or receipt.shard_sha256 != shard.shard_sha256
                ):
                    raise ValueError("LOCAL_EMBEDDING_SHARED_ROW_CLOSURE_INVALID")
            resolved.append((shard_pointer, shard))
        return tuple(
            sorted(
                resolved,
                key=lambda value: (
                    value[0].artifact_id,
                    value[0].artifact_revision_id,
                    value[0].member_path,
                    value[0].sha256,
                ),
            )
        )

    def _resolve_file_set(
        self,
        result_pointer: ArtifactMemberPointer,
        shard_pointer: ArtifactMemberPointer,
        binary_pointer: ArtifactMemberPointer,
    ) -> IncrementalEmbeddingResult:
        self.reader.prefetch(((result_pointer.artifact_id, result_pointer.artifact_revision_id),))
        self.reader.require_file_set(
            result_pointer.artifact_id,
            result_pointer.artifact_revision_id,
            ("result.json", "shard.json", "vectors.f32"),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )

        def read(pointer: ArtifactMemberPointer, limit: int) -> bytes:
            return self.reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(EMBEDDING_RESULT_ARTIFACT_TYPE,),
                expected_primary_file="result.json",
                max_bytes=limit,
            ).payload

        result = parse_incremental_embedding_result(
            _canonical_document(read(result_pointer, MAX_EMBEDDING_INPUT_BYTES))
        )
        shard = parse_embedding_shard(
            _canonical_document(read(shard_pointer, MAX_EMBEDDING_INPUT_BYTES))
        )
        if result.shard != shard:
            raise ValueError("LOCAL_EMBEDDING_SHARD_MISMATCH")
        binary = read(binary_pointer, 16 * 1024**2)
        if len(binary) != shard.binary.byte_count:
            raise ValueError("LOCAL_EMBEDDING_BINARY_SIZE_MISMATCH")
        read_unit_vectors(
            binary,
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=shard.binary.sha256,
        )
        return result
