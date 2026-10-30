"""Common public-solution composition over official Catalog reads, not another search store."""

from dataclasses import dataclass

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_reference_query import ReferenceQueryTextInput
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    SHARD_SCHEMA_REF,
    EmbeddingVectorRowRef,
)
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityLimitation,
    PublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.embedding_registry_ports import (
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_vector_ranking import (
    rank_similarity_profiles,
    validate_similarity_vectors,
)


def _require(condition: bool, code: SimilarityFailureCode) -> None:
    if not condition:
        raise SimilarityContextReadError(code)


@dataclass(frozen=True, slots=True)
class VerifiedPublicSolutionQueryRead:
    """Current-root committed bytes from the QUERY owner, not execution/source authority.

    The actual owner must authorize operator, native admission, committed producer,
    lifecycle and Artifact metadata. The composer independently closes values/hash.
    """

    request: PublicSolutionQueryInput
    result: PublicSolutionQueryResult
    result_member: ArtifactMemberPointer
    shard_member: ArtifactMemberPointer
    binary: bytes


@dataclass(frozen=True, slots=True)
class PreparedPublicSolutionQuerySource:
    """One owner-local normalized anchor, not a persistent source or execution grant."""

    request_sha256: str
    anchor: PublicSolutionSourceReference
    row: ReferenceQueryTextInput


def prepare_public_solution_query_source(
    request: PublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
) -> PreparedPublicSolutionQuerySource:
    """Use the same report projection as DOCUMENT, with the distinct QUERY space.

    The caller owns official current source/index reads and reauthorization in
    one root. This pure materialization never substitutes DOCUMENT vectors.
    """
    request = PublicSolutionSimilarityRequest.model_validate(request)
    entries = _public_entries(request, capture)
    return PreparedPublicSolutionQuerySource(
        request.request_sha256, request.anchor, _anchor_query_row(request, entries)
    )


def _anchor_query_row(
    request: PublicSolutionSimilarityRequest,
    entries: dict[str, PublicSolutionEmbeddingEntry],
) -> ReferenceQueryTextInput:
    view = request.views[0]
    expected = prepare_public_solution_encoding(
        entries[request.anchor.source.item_revision_id],
        space=view.index.spaces.query,
        storage_partition=view.index.storage_partition,
    ).input
    _require(expected is not None, "QUERY_RESULT_INVALID")
    assert expected is not None
    return ReferenceQueryTextInput(
        view="CONCRETE_FACETS", encoding=expected.encoding, text=expected.text
    )


def _public_entries(
    request: PublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
) -> dict[str, PublicSolutionEmbeddingEntry]:
    view = request.views[0]
    _require(
        type(capture) is ResolvedEmbeddingLookup
        and type(capture.sources) is tuple
        and type(capture.entries) is tuple
        and type(capture.truncated) is bool
        and 1 <= len(capture.sources) <= request.maximum_sources
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
        and all(source.source_class in request.source_classes for source in capture.sources),
        "SOURCE_POINTER_INVALID",
    )
    entries = {}
    for original in capture.entries:
        _require(isinstance(original, PublicSolutionEmbeddingEntry), "SOURCE_POINTER_INVALID")
        assert isinstance(original, PublicSolutionEmbeddingEntry)
        entry = PublicSolutionEmbeddingEntry.model_validate(raw_similarity_contract_value(original))
        key = entry.source.item_revision_id
        _require(
            key not in entries
            and entry.source == sources.get(key)
            and entry.base_analysis_run_id == bases.get(key)
            and entry.graph_snapshot == request.graph_snapshot
            and entry.policy_revision_id == request.policy_revision_id
            and entry.policy_sha256 == request.policy_sha256
            and entry.recipe == view.recipe,
            "SOURCE_POINTER_INVALID",
        )
        entries[key] = entry
    anchor = entries.get(request.anchor.source.item_revision_id)
    _require(anchor is not None, "SOURCE_POINTER_INVALID")
    assert anchor is not None
    _require(
        PublicSolutionSourceReference.from_entry(anchor) == request.anchor,
        "SOURCE_POINTER_INVALID",
    )
    return entries


def _query_vector(
    request: PublicSolutionSimilarityRequest,
    entries: dict[str, PublicSolutionEmbeddingEntry],
    query: VerifiedPublicSolutionQueryRead,
) -> tuple[tuple[float, ...], PublicSolutionQueryExecutionPointer]:
    _require(type(query) is VerifiedPublicSolutionQueryRead, "QUERY_RESULT_INVALID")
    numerical = PublicSolutionQueryInput.model_validate(query.request)
    result = PublicSolutionQueryResult.model_validate(query.result)
    validate_public_solution_query_result(numerical, result)
    view = request.views[0]
    expected = _anchor_query_row(request, entries)
    _require(
        numerical.context_request_sha256 == request.request_sha256
        and numerical.spaces == view.index.spaces
        and numerical.recipe == view.recipe
        and numerical.rows[0].encoding == expected.encoding
        and numerical.rows[0].text == expected.text,
        "QUERY_RESULT_INVALID",
    )
    for pointer, name, schema, value in (
        (query.result_member, "result.json", PUBLIC_SOLUTION_QUERY_RESULT_REF, result),
        (query.shard_member, "shard.json", SHARD_SCHEMA_REF, result.shard),
    ):
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
        _require(
            pointer.member_path == name
            and pointer.schema_ref == schema
            and pointer.media_type == "application/json"
            and pointer.sha256 == content_sha256(value.model_dump(mode="json")),
            "QUERY_RESULT_INVALID",
        )
    _require(
        (query.result_member.artifact_id, query.result_member.artifact_revision_id)
        == (query.shard_member.artifact_id, query.shard_member.artifact_revision_id),
        "QUERY_RESULT_INVALID",
    )
    vectors = read_unit_vectors(
        query.binary,
        dimension=result.shard.dimension,
        row_count=1,
        expected_sha256=result.shard.binary.sha256,
    )
    return vectors[0], PublicSolutionQueryExecutionPointer(
        job_id=numerical.job_id,
        query_request_id=numerical.query_request_id,
        request_sha256=numerical.request_sha256,
        input_set_sha256=numerical.input_set_sha256,
        result_member=query.result_member,
        result_sha256=result.result_sha256,
    )


def compose_public_solution_similarity(
    request: PublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
    document: ResolvedPinnedEmbeddingIndex,
    query: VerifiedPublicSolutionQueryRead,
) -> PublicSolutionSimilarityContext:
    """Compose owner-local values only. No DB/IO/launch or substitute for actual authorization.

    Sources and unique numerical rows use keyed maps; exact ranking is the shared
    O(n*d + n*log(n)) rule. Bounded context contains references, never report text.
    """
    request = PublicSolutionSimilarityRequest.model_validate(request)
    entries = _public_entries(request, capture)
    view = request.views[0]
    _require(
        type(document) is ResolvedPinnedEmbeddingIndex
        and document.intent.selection == view
        and document.intent.scope.corpus_id == capture.corpus_id
        and document.intent.scope.graph_snapshot == request.graph_snapshot
        and document.intent.scope.policy_revision_id == request.policy_revision_id
        and document.intent.scope.policy_sha256 == request.policy_sha256
        and document.intent.scope.maximum_sources == request.maximum_sources
        and {source.item_revision_id: source for source in document.sources}
        == {source.item_revision_id: source for source in capture.sources}
        and len(document.sources) == len(capture.sources),
        "INDEX_POINTER_INVALID",
    )
    profiles = {
        row.source_item_revision_id: PublicSolutionProfilePointer.model_validate(
            raw_similarity_contract_value(row.profile)
        )
        for row in document.profiles
    }
    _require(
        len(profiles) == len(document.profiles)
        and profiles
        == {key: PublicSolutionProfilePointer.from_entry(entry) for key, entry in entries.items()},
        "INDEX_POINTER_INVALID",
    )
    rows = {row.row.encoding.encoding_sha256: row for row in document.numerical_rows}
    _require(len(rows) == len(document.numerical_rows), "INDEX_POINTER_INVALID")
    bindings = {}
    for original in document.bindings:
        _require(
            isinstance(original, PublicSolutionEmbeddingSourceBinding), "INDEX_POINTER_INVALID"
        )
        assert isinstance(original, PublicSolutionEmbeddingSourceBinding)
        binding = PublicSolutionEmbeddingSourceBinding.model_validate(
            raw_similarity_contract_value(original)
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
    vector, execution = _query_vector(request, entries, query)
    ranked = rank_similarity_profiles(
        vector,
        tuple(
            (binding.profile, rows[binding.encoding.encoding_sha256].values)
            for key, binding in bindings.items()
            if key != request.anchor.source.item_revision_id
        ),
        top_k=request.top_k,
    )
    by_profile = {binding.profile: binding for binding in bindings.values()}
    candidates = []
    for rank, (profile, score) in enumerate(ranked, 1):
        binding = by_profile[profile]
        reference = PublicSolutionSourceReference.from_entry(
            entries[binding.source.item_revision_id]
        )
        candidates.append(
            reference.model_dump(mode="json")
            | {
                "observation": {
                    "channel": "VECTOR",
                    "view": "CONCRETE_FACETS",
                    "rank": rank,
                    "cosine_millionths": round(score * 1_000_000),
                    "score_semantics": "ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY",
                    "query_row": EmbeddingVectorRowRef(
                        shard_manifest=query.shard_member,
                        row_index=0,
                        encoding_sha256=query.result.shard.rows[0].encoding_sha256,
                    ).model_dump(mode="json"),
                    "document_row": binding.row_ref.model_dump(mode="json"),
                }
            }
        )
    limitations: list[PublicSolutionSimilarityLimitation] = [
        "SCORE_IS_NOT_PROOF_OF_IDENTICAL_REASONING"
    ]
    if len(entries) < len(capture.sources):
        limitations.append("PARTIAL_REPORT_COVERAGE")
    if len(bindings) < len(entries):
        limitations.append("PARTIAL_VIEW_COVERAGE")
    if capture.truncated:
        limitations.append("BOUNDED_SCOPE_TRUNCATED")
    scored = len(bindings) - int(request.anchor.source.item_revision_id in bindings)
    body = dict(
        schema_version="system-rag-similarity-context/3.0",
        request=request.model_dump(mode="json"),
        status="EMPTY" if not scored else "PARTIAL" if len(limitations) > 1 else "READY",
        population=dict(
            authorized_source_count=len(capture.sources),
            authorized_source_set_sha256=population_sha256(capture.sources),
            available_report_count=len(entries),
            available_report_set_sha256=content_sha256(
                [profiles[key].model_dump(mode="json") for key in sorted(profiles)]
            ),
            available_binding_count=len(bindings),
            binding_set_sha256=content_sha256(
                [bindings[key].binding_sha256 for key in sorted(bindings)]
            ),
            scored_count=scored,
            truncated=capture.truncated,
        ),
        query_execution=execution.model_dump(mode="json"),
        candidates=candidates,
        limitations=limitations,
        error_code=None,
    )
    return PublicSolutionSimilarityContext.model_validate(
        body | {"context_sha256": content_sha256(body)}
    )
