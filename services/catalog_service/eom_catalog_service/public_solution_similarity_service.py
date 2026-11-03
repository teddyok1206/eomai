"""Common public-solution composition over official Catalog reads, not another search store."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import overload

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_reference_query import ReferenceQueryTextInput
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    SHARD_SCHEMA_REF,
    EmbeddingVectorRowRef,
)
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityLimitation,
    PublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionReferenceV4,
    PublicSolutionSimilarityContextV4,
    PublicSolutionSimilarityRequestV4,
    SupportedPublicSolutionSimilarityContext,
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_request,
    public_solution_reference_for_entry,
)
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.embedding_registry_ports import (
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_document_scope import (
    PublicSolutionDocumentScope,
    validate_public_solution_document,
    validated_public_solution_entries,
)
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_vector_ranking import rank_similarity_profiles


def _require(condition: bool, code: SimilarityFailureCode) -> None:
    if not condition:
        raise SimilarityContextReadError(code)


@dataclass(frozen=True, slots=True)
class VerifiedPublicSolutionQueryRead:
    """Current-root committed bytes from the QUERY owner, not execution/source authority.

    The actual owner must authorize operator, native admission, committed producer,
    lifecycle and Artifact metadata. The composer independently closes values/hash.
    """

    request: PublicSolutionQueryInput = field(repr=False)
    result: PublicSolutionQueryResult
    result_member: ArtifactMemberPointer
    shard_member: ArtifactMemberPointer
    binary: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedPublicSolutionQuerySource:
    """One owner-local normalized anchor, not a persistent source or execution grant."""

    request_sha256: str
    anchor: PublicSolutionReferenceV4
    row: ReferenceQueryTextInput


def prepare_public_solution_query_source(
    request: SupportedPublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
) -> PreparedPublicSolutionQuerySource:
    """Use the same report projection as DOCUMENT, with the distinct QUERY space.

    The caller owns official current source/index reads and reauthorization in
    one root. This pure materialization never substitutes DOCUMENT vectors.
    """
    request = parse_supported_public_solution_similarity_request(request)
    entries = _public_entries(request, capture)
    return PreparedPublicSolutionQuerySource(
        request.request_sha256, request.anchor, _anchor_query_row(request, entries)
    )


def _anchor_query_row(
    request: SupportedPublicSolutionSimilarityRequest,
    entries: Mapping[str, PublicSolutionEncodingEntry],
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


def _document_scope(
    request: SupportedPublicSolutionSimilarityRequest,
) -> PublicSolutionDocumentScope:
    return PublicSolutionDocumentScope(
        request.views[0],
        request.graph_snapshot,
        request.policy_revision_id,
        request.policy_sha256,
        request.source_classes,
        request.maximum_sources,
    )


def _public_entries(
    request: SupportedPublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
) -> dict[str, PublicSolutionEncodingEntry]:
    _require(
        type(capture) is ResolvedEmbeddingLookup and bool(capture.sources),
        "SOURCE_POINTER_INVALID",
    )
    entries = validated_public_solution_entries(_document_scope(request), capture)
    if isinstance(request, PublicSolutionSimilarityRequest):
        _require(
            all(isinstance(entry, PublicSolutionEmbeddingEntry) for entry in entries.values()),
            "SOURCE_POINTER_INVALID",
        )
    anchor = entries.get(request.anchor.source.item_revision_id)
    _require(anchor is not None, "SOURCE_POINTER_INVALID")
    assert anchor is not None
    _require(
        public_solution_reference_for_entry(anchor) == request.anchor,
        "SOURCE_POINTER_INVALID",
    )
    return entries


def _query_vector(
    request: SupportedPublicSolutionSimilarityRequest,
    entries: Mapping[str, PublicSolutionEncodingEntry],
    query: VerifiedPublicSolutionQueryRead,
) -> tuple[tuple[float, ...], PublicSolutionQueryExecutionPointer]:
    vector, execution = read_verified_public_solution_query_vector(query)
    numerical = query.request
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
    return vector, execution


def read_verified_public_solution_query_vector(
    query: VerifiedPublicSolutionQueryRead,
) -> tuple[tuple[float, ...], PublicSolutionQueryExecutionPointer]:
    """Validate common QUERY2 committed members/bytes; not its Item/private ownership."""
    _require(type(query) is VerifiedPublicSolutionQueryRead, "QUERY_RESULT_INVALID")
    numerical = PublicSolutionQueryInput.model_validate(query.request)
    result = PublicSolutionQueryResult.model_validate(query.result)
    validate_public_solution_query_result(numerical, result)
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


@overload
def compose_public_solution_similarity(
    request: PublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
    document: ResolvedPinnedEmbeddingIndex,
    query: VerifiedPublicSolutionQueryRead,
) -> PublicSolutionSimilarityContext: ...


@overload
def compose_public_solution_similarity(
    request: PublicSolutionSimilarityRequestV4,
    capture: ResolvedEmbeddingLookup,
    document: ResolvedPinnedEmbeddingIndex,
    query: VerifiedPublicSolutionQueryRead,
) -> PublicSolutionSimilarityContextV4: ...


def compose_public_solution_similarity(
    request: SupportedPublicSolutionSimilarityRequest,
    capture: ResolvedEmbeddingLookup,
    document: ResolvedPinnedEmbeddingIndex,
    query: VerifiedPublicSolutionQueryRead,
) -> SupportedPublicSolutionSimilarityContext:
    """Compose owner-local values only. No DB/IO/launch or substitute for actual authorization.

    Sources and unique numerical rows use keyed maps; exact ranking is the shared
    O(n*d + n*log(n)) rule. Bounded context contains references, never report text.
    """
    request = parse_supported_public_solution_similarity_request(request)
    entries = _public_entries(request, capture)
    validated = validate_public_solution_document(
        _document_scope(request), capture, entries, document
    )
    references, profiles = validated.references, validated.profiles
    bindings, rows = validated.bindings, validated.rows
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
        reference = references[binding.source.item_revision_id]
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
        schema_version="system-rag-similarity-context/5.0"
        if request.schema_version == "system-rag-similarity-request/5.0"
        else "system-rag-similarity-context/4.0"
        if isinstance(request, PublicSolutionSimilarityRequestV4)
        else "system-rag-similarity-context/3.0",
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
    result_type = (
        PublicSolutionSimilarityContextV4
        if isinstance(request, PublicSolutionSimilarityRequestV4)
        else PublicSolutionSimilarityContext
    )
    return result_type.model_validate(body | {"context_sha256": content_sha256(body)})
