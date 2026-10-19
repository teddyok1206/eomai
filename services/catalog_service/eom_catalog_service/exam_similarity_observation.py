"""Read-only C5 arithmetic over exact owner-resolved DOCUMENT rows, never QUERY."""

from __future__ import annotations

from itertools import combinations

from eom_catalog_contracts.embedding_vector_binary import EmbeddingVectorBinaryError
from eom_catalog_contracts.embedding_vector_validation import validate_unit_vector
from eom_catalog_contracts.exam_similarity_observation import (
    ExamObservationMember,
    ExamObservationRequest,
    ExamObservationRow,
    ExamPairObservation,
    ExamSimilarityObservation,
    ExamViewObservation,
    parse_exam_observation_request,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import ApprovedReferenceItemAnchor
from eom_identifiers import content_sha256

from eom_catalog_service.embedding_registry_ports import ResolvedPinnedEmbeddingIndex
from eom_catalog_service.inference_transfer_vectors import normalized_cosine_similarity
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)
from eom_catalog_service.similarity_document_read_validation import (
    validate_prepared_similarity_sources,
    validate_similarity_document_reads,
)


def compose_exam_similarity_observation(
    request: ExamObservationRequest,
    prepared: tuple[PreparedSimilaritySource, ...],
    reads: tuple[ResolvedPinnedEmbeddingIndex, ...],
) -> ExamSimilarityObservation:
    """Pure derived values; caller must retain the official read/end-authority fence."""
    request = parse_exam_observation_request(request)
    sources = validate_prepared_similarity_sources(
        prepared, source_classes=request.source_classes, maximum_sources=25
    )
    positions = {m.item_revision_id: m.position for m in request.cohort.members}
    if set(sources) != set(positions):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    resolved = validate_similarity_document_reads(
        request,
        sources,
        reads,
        {selection.view for selection in request.views if selection.index is not None},
    )
    members = []
    for member in request.cohort.members:
        source = sources[member.item_revision_id]
        if source.profile is not None and not isinstance(
            source.profile, InferenceTransferProfilePointer
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        members.append(
            ExamObservationMember(
                position=member.position,
                reference=ApprovedReferenceItemAnchor(
                    source=source.source,
                    profile=source.profile,
                    solution_evidence=source.solution_evidence,
                ),
            )
        )
    observations = []
    for selection in request.views:
        read = resolved.get(selection.view)
        if read is None:
            observations.append(
                ExamViewObservation(
                    view=selection.view, status="INDEX_NOT_PREPARED", rows=(), pairs=()
                )
            )
            continue
        if selection.index is None:
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        numeric = {r.row.encoding.encoding_sha256: r for r in read.numerical_rows}
        if set(numeric) != {b.encoding.encoding_sha256 for b in read.bindings}:
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        try:
            for row in numeric.values():
                validate_unit_vector(
                    row.values, selection.index.spaces.document.model_spec.dimension
                )
        except EmbeddingVectorBinaryError:
            raise SimilarityContextReadError("INDEX_POINTER_INVALID") from None
        ordered = sorted(read.bindings, key=lambda b: positions[b.source.item_revision_id])
        rows = tuple(
            ExamObservationRow(
                position=positions[binding.source.item_revision_id], document_row=binding.row_ref
            )
            for binding in ordered
        )
        vectors = {
            positions[b.source.item_revision_id]: numeric[b.encoding.encoding_sha256].values
            for b in ordered
        }
        pairs = tuple(
            ExamPairObservation(
                left_position=left.position,
                right_position=right.position,
                cosine_millionths=round(
                    normalized_cosine_similarity(vectors[left.position], vectors[right.position])
                    * 1000000
                ),
            )
            for left, right in combinations(rows, 2)
        )
        observations.append(
            ExamViewObservation(
                view=selection.view,
                status="COMPLETE" if len(rows) == 25 else "PARTIAL" if len(rows) >= 2 else "EMPTY",
                rows=rows,
                pairs=pairs,
            )
        )
    body = {
        "schema_version": "system-rag-exam-observation/1.0",
        "request": request.model_dump(mode="json"),
        "status": "READY"
        if all(member.reference.profile is not None for member in members)
        and all(view.status == "COMPLETE" for view in observations)
        else "PARTIAL"
        if any(view.pairs for view in observations)
        else "EMPTY",
        "members": [member.model_dump(mode="json") for member in members],
        "views": [view.model_dump(mode="json") for view in observations],
        "score_semantics": "ROUNDED_DISPLAY_ONLY_NOT_SOLUTION_EQUALITY_OR_APPROVAL",
    }
    return ExamSimilarityObservation.model_validate(body | {"result_sha256": content_sha256(body)})
