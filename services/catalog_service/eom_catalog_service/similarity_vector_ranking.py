"""Shared exact scalar/tie rule over owner-validated rows, independent of source families."""

from eom_catalog_contracts.embedding_index_families import SupportedEmbeddingProfilePointer
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors

from eom_catalog_service.inference_transfer_vectors import normalized_cosine_similarity


def validate_similarity_vectors(vectors: tuple[tuple[float, ...], ...], *, dimension: int) -> None:
    """Validate local rows with the canonical codec, without repair or retaining binary copies.

    Only a 64-row validation slab is materialized at once. Nothing is persisted
    or sent across a component boundary; the original float32-derived tuples rank.
    """
    for offset in range(0, len(vectors), 64):
        pack_unit_vectors(vectors[offset : offset + 64], dimension=dimension)


def rank_similarity_profiles[P: SupportedEmbeddingProfilePointer](
    query: tuple[float, ...],
    candidates: tuple[tuple[P, tuple[float, ...]], ...],
    *,
    top_k: int,
) -> tuple[tuple[P, float], ...]:
    """Reuse the frozen float64 cosine and exact ref ties, not rounded display scores."""
    scores = tuple(
        (pointer, normalized_cosine_similarity(query, vector)) for pointer, vector in candidates
    )
    return tuple(
        sorted(
            scores,
            key=lambda row: (
                -row[1],
                row[0].profile_id,
                row[0].profile_revision_id,
                row[0].profile_sha256,
            ),
        )[:top_k]
    )
