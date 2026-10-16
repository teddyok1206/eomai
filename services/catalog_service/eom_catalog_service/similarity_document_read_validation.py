"""Exact source/binding/index closure for reference, private-query and exam consumers."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingVectorRowRef,
    parse_embedding_binding,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, PopulationSource
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.similarity_context import SimilarityViewSelection
from pydantic import TypeAdapter

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)


class SimilarityDocumentReadScope(Protocol):
    """Immutable parsed request fields only; this value grants no read authority."""

    @property
    def graph_snapshot(self) -> KnowledgeGraphSnapshotPointer: ...
    @property
    def policy_revision_id(self) -> str: ...
    @property
    def policy_sha256(self) -> str: ...
    @property
    def views(self) -> tuple[SimilarityViewSelection, ...]: ...


def validate_prepared_similarity_sources(
    values: tuple[PreparedSimilaritySource, ...],
    *,
    source_classes: tuple[str, ...],
    maximum_sources: int,
) -> dict[str, PreparedSimilaritySource]:
    """The same metadata closure for queries and fixed DOCUMENT cohort observations."""
    if type(values) is not tuple or len(values) > maximum_sources:
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    sources: dict[str, PreparedSimilaritySource] = {}
    reader: TypeAdapter[PopulationSource] = TypeAdapter(PopulationSource)
    for value in values:
        if not isinstance(value, PreparedSimilaritySource):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        source = reader.validate_python(raw_similarity_contract_value(value.source))
        if (
            source != value.source
            or source.source_class not in source_classes
            or source.item_revision_id in sources
            or (value.profile is None) != (value.solution_evidence is None)
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        if value.profile is not None:
            InferenceTransferProfilePointer.model_validate(
                raw_similarity_contract_value(value.profile)
            )
            KnowledgeSolutionEvidencePointer.model_validate(
                raw_similarity_contract_value(value.solution_evidence)
            )
        sources[source.item_revision_id] = value
    profiles = tuple(v.profile for v in sources.values() if v.profile is not None)
    if len(set(profiles)) != len(profiles):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    return sources


def validate_similarity_document_reads(
    request: SimilarityDocumentReadScope,
    sources: dict[str, PreparedSimilaritySource],
    reads: tuple[ResolvedPinnedEmbeddingIndex, ...],
    expected_views: set[ExperimentView],
) -> dict[ExperimentView, ResolvedPinnedEmbeddingIndex]:
    if type(reads) is not tuple or len(reads) > 3:
        raise SimilarityContextReadError("INDEX_POINTER_INVALID")
    selections = {selection.view: selection for selection in request.views}
    result: dict[ExperimentView, ResolvedPinnedEmbeddingIndex] = {}
    expected_profiles = {
        revision: source.profile
        for revision, source in sources.items()
        if source.profile is not None
    }
    for value in reads:
        if not isinstance(value, ResolvedPinnedEmbeddingIndex) or (
            not isinstance(value.intent, EmbeddingRegistryRead)
            or not isinstance(value.intent.scope, EmbeddingRegistryLookup)
            or not isinstance(value.intent.selection, SimilarityViewSelection)
            or type(value.sources) is not tuple
            or type(value.profiles) is not tuple
            or type(value.bindings) is not tuple
            or type(value.numerical_rows) is not tuple
            or any(
                not isinstance(row, MaterializedEmbeddingReadRow) for row in value.numerical_rows
            )
            or any(
                not isinstance(source, ApprovedItemKnowledgeSourceV2) for source in value.sources
            )
            or any(
                not isinstance(profile, AuthorizedEmbeddingReadProfile)
                for profile in value.profiles
            )
        ):
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        for row in value.numerical_rows:
            if not isinstance(row.row, RegisteredEmbeddingRow) or (
                not isinstance(row.row.encoding, EmbeddingEncodingIdentity)
                or not isinstance(row.row.row_ref, EmbeddingVectorRowRef)
            ):
                raise SimilarityContextReadError("INDEX_POINTER_INVALID")
            EmbeddingEncodingIdentity.model_validate(
                raw_similarity_contract_value(row.row.encoding)
            )
            EmbeddingVectorRowRef.model_validate(raw_similarity_contract_value(row.row.row_ref))
        view = value.intent.selection.view
        if (
            view in result
            or view not in expected_views
            or value.intent.selection != selections.get(view)
            or (
                value.intent.scope.graph_snapshot != request.graph_snapshot
                or value.intent.scope.policy_revision_id != request.policy_revision_id
                or value.intent.scope.policy_sha256 != request.policy_sha256
                or {source.item_revision_id: source for source in value.sources}
                != {revision: source.source for revision, source in sources.items()}
                or len(value.sources) != len(sources)
                or {row.source_item_revision_id: row.profile for row in value.profiles}
                != expected_profiles
                or len(value.profiles) != len(expected_profiles)
            )
        ):
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        revisions: set[str] = set()
        rows = {row.row.encoding.encoding_sha256: row.row for row in value.numerical_rows}
        if len(rows) != len(value.numerical_rows):
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        for original in value.bindings:
            binding = parse_embedding_binding(raw_similarity_contract_value(original))
            source = sources.get(binding.source.item_revision_id)
            if (
                source is None
                or binding.source.item_revision_id in revisions
                or (
                    binding.source != source.source
                    or binding.profile != source.profile
                    or binding.solution_evidence != source.solution_evidence
                    or binding.graph_snapshot != request.graph_snapshot
                    or binding.policy_revision_id != request.policy_revision_id
                    or binding.policy_sha256 != request.policy_sha256
                    or binding.view != view
                    or binding.recipe != value.intent.selection.recipe
                    or binding.encoding.encoding_sha256 not in rows
                    or rows[binding.encoding.encoding_sha256].encoding != binding.encoding
                    or rows[binding.encoding.encoding_sha256].row_ref != binding.row_ref
                )
            ):
                raise SimilarityContextReadError("INDEX_POINTER_INVALID")
            revisions.add(binding.source.item_revision_id)
        result[view] = value
    if set(result) != expected_views:
        raise SimilarityContextReadError("INDEX_POINTER_INVALID")
    return result
