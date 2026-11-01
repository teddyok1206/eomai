"""Shared pure proof of common document rows; no source authority or query anchor.

Item-to-Item and private-question consumers use the same validated document
closure. Authorization, committed Artifact reads and current lifecycle fences
belong to the existing Catalog owner before and after this pure composition.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_index_families import parse_supported_embedding_binding
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityView
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionProfilePointer,
    RegisteredPublicSolutionSourceBinding,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionReferenceV4,
    PublicSolutionSimilarityViewV4,
    public_solution_reference_for_entry,
)
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from pydantic import TypeAdapter

from eom_catalog_service.embedding_registry_ports import (
    MaterializedEmbeddingReadRow,
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_vector_ranking import validate_similarity_vectors

type PublicDocumentBinding = (
    PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding
)
type PublicDocumentProfile = PublicSolutionProfilePointer | RegisteredPublicSolutionProfilePointer


def _require(condition: bool, code: SimilarityFailureCode) -> None:
    if not condition:
        raise SimilarityContextReadError(code)


@dataclass(frozen=True, slots=True)
class PublicSolutionDocumentScope:
    """Small owner-local selection; a pinned read scope is never a permission grant."""

    view: PublicSolutionSimilarityView | PublicSolutionSimilarityViewV4
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str
    policy_sha256: str
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    maximum_sources: int


@dataclass(frozen=True, slots=True)
class ValidatedPublicSolutionDocument:
    """Read-only keyed references, not copies of reports or another persistent index."""

    references: Mapping[str, PublicSolutionReferenceV4]
    profiles: Mapping[str, PublicDocumentProfile]
    bindings: Mapping[str, PublicDocumentBinding]
    rows: Mapping[str, MaterializedEmbeddingReadRow]


def validated_public_solution_entries(
    scope: PublicSolutionDocumentScope,
    capture: ResolvedEmbeddingLookup,
) -> dict[str, PublicSolutionEncodingEntry]:
    """Validate bounded official-source capture without inventing a private self anchor."""
    view = scope.view
    _require(
        type(capture) is ResolvedEmbeddingLookup
        and type(capture.sources) is tuple
        and type(capture.entries) is tuple
        and type(capture.truncated) is bool
        and len(capture.sources) <= scope.maximum_sources
        and capture.space == view.index.spaces.document
        and capture.recipe == view.recipe,
        "SOURCE_POINTER_INVALID",
    )
    sources = {source.item_revision_id: source for source in capture.sources}
    bases = dict(capture.base_analysis_run_ids)
    _require(
        len(sources) == len(capture.sources)
        and len(bases) == len(capture.base_analysis_run_ids)
        and set(bases) == set(sources)
        and all(source.source_class in scope.source_classes for source in capture.sources),
        "SOURCE_POINTER_INVALID",
    )
    entries: dict[str, PublicSolutionEncodingEntry] = {}
    for original in capture.entries:
        entry = parse_public_solution_encoding_entry(original)
        key = entry.source.item_revision_id
        _require(
            key not in entries
            and entry.source == sources.get(key)
            and entry.base_analysis_run_id == bases.get(key)
            and entry.graph_snapshot == scope.graph_snapshot
            and entry.policy_revision_id == scope.policy_revision_id
            and entry.policy_sha256 == scope.policy_sha256
            and entry.recipe == view.recipe,
            "SOURCE_POINTER_INVALID",
        )
        entries[key] = entry
    return entries


def validate_public_solution_document(
    scope: PublicSolutionDocumentScope,
    capture: ResolvedEmbeddingLookup,
    entries: Mapping[str, PublicSolutionEncodingEntry],
    document: ResolvedPinnedEmbeddingIndex,
) -> ValidatedPublicSolutionDocument:
    """Close profiles/bindings/rows once in O(text bytes + N*D), using maps/sets.

    ``entries`` must come from ``validated_public_solution_entries`` for this
    capture/scope. Consumers retain their own anchor or private-turn association.
    Shared encoding rows are intentional; extra rows and dangling bindings fail.
    """
    view = scope.view
    _require(
        type(document) is ResolvedPinnedEmbeddingIndex
        and document.intent.selection == view
        and document.intent.scope.corpus_id == capture.corpus_id
        and document.intent.scope.graph_snapshot == scope.graph_snapshot
        and document.intent.scope.policy_revision_id == scope.policy_revision_id
        and document.intent.scope.policy_sha256 == scope.policy_sha256
        and document.intent.scope.maximum_sources == scope.maximum_sources
        and {source.item_revision_id: source for source in document.sources}
        == {source.item_revision_id: source for source in capture.sources}
        and len(document.sources) == len(capture.sources),
        "INDEX_POINTER_INVALID",
    )
    profile_reader: TypeAdapter[PublicDocumentProfile] = TypeAdapter(PublicDocumentProfile)
    references = {key: public_solution_reference_for_entry(entry) for key, entry in entries.items()}
    profiles = {
        row.source_item_revision_id: profile_reader.validate_python(
            raw_similarity_contract_value(row.profile)
        )
        for row in document.profiles
    }
    _require(
        len(profiles) == len(document.profiles)
        and profiles == {key: reference.profile for key, reference in references.items()},
        "INDEX_POINTER_INVALID",
    )
    rows = {row.row.encoding.encoding_sha256: row for row in document.numerical_rows}
    _require(len(rows) == len(document.numerical_rows), "INDEX_POINTER_INVALID")
    bindings: dict[str, PublicDocumentBinding] = {}
    for original in document.bindings:
        binding = parse_supported_embedding_binding(original)
        _require(
            isinstance(
                binding,
                PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding,
            ),
            "INDEX_POINTER_INVALID",
        )
        assert isinstance(
            binding, PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding
        )
        key = binding.source.item_revision_id
        entry = entries.get(key)
        _require(entry is not None and key not in bindings, "INDEX_POINTER_INVALID")
        assert entry is not None
        encoded = prepare_public_solution_encoding(
            entry,
            space=view.index.spaces.document,
            storage_partition=view.index.storage_partition,
        ).input
        row = rows.get(binding.encoding.encoding_sha256)
        _require(
            encoded is not None
            and binding.source == entry.source
            and binding.profile == profiles[key]
            and binding.evidence == entry.evidence
            and binding.base_analysis_run_id == entry.base_analysis_run_id
            and binding.graph_snapshot == entry.graph_snapshot
            and binding.policy_revision_id == entry.policy_revision_id
            and binding.policy_sha256 == entry.policy_sha256
            and binding.recipe == entry.recipe
            and binding.encoding == encoded.encoding
            and row is not None
            and row.row.encoding == binding.encoding
            and row.row.row_ref == binding.row_ref,
            "INDEX_POINTER_INVALID",
        )
        bindings[key] = binding
    _require(
        set(rows) == {binding.encoding.encoding_sha256 for binding in bindings.values()},
        "INDEX_POINTER_INVALID",
    )
    validate_similarity_vectors(
        tuple(row.values for row in rows.values()),
        dimension=view.index.spaces.document.model_spec.dimension,
    )
    return ValidatedPublicSolutionDocument(
        MappingProxyType(references),
        MappingProxyType(profiles),
        MappingProxyType(bindings),
        MappingProxyType(rows),
    )
