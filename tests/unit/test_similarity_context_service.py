"""Synthetic composition only; no production QUERY, authority grant or model invocation."""

from __future__ import annotations

from dataclasses import replace
from math import sqrt
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    ReferenceQuerySpaces,
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingVectorShardManifest,
    embedding_input_set_sha256,
    parse_embedding_index,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentView,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
    SimilarityContextRequest,
    SimilarityIndexPin,
    SimilarityVectorObservation,
    SimilarityViewSelection,
    parse_similarity_context_request,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    PreparedSimilaritySource,
    SimilarityContextReadError,
    SimilarityQueryUnavailable,
    VerifiedReferenceQueryRead,
)
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_space,
    encoding_identity,
    index_manifest,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import sha

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


class Sources:
    def __init__(
        self, prepared: PreparedSimilarityContext, reads: tuple[ResolvedPinnedEmbeddingIndex, ...]
    ) -> None:
        self.prepared, self.reads = prepared, reads
        self.calls: list[str] = []
        self.denial: str | None = None

    def prepare_similarity_context(self, _caller: Any, _request: Any) -> PreparedSimilarityContext:
        self.calls.append("prepare")
        return self.prepared

    def read_similarity_views(
        self, _caller: Any, _request: Any, _prepared: Any
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        self.calls.append("read")
        return self.reads

    def reauthorize_similarity_context(self, _caller: Any, _request: Any, _prepared: Any) -> None:
        self.calls.append("reauthorize")
        if self.denial:
            raise SimilarityContextReadError("SOURCE_REVOKED")


class Query:
    def __init__(self, value: VerifiedReferenceQueryRead | SimilarityQueryUnavailable) -> None:
        self.value = value
        self.calls = 0

    def resolve_reference_query(
        self, _caller: Any, _request: Any, _prepared: Any
    ) -> VerifiedReferenceQueryRead | SimilarityQueryUnavailable:
        self.calls += 1
        return self.value


def case(
    *, missing_view: ExperimentView | None = None
) -> tuple[SimilarityContextRequest, Sources, Query]:
    entries = tuple(embedding_entry(seed) for seed in "abc")
    prepared_sources = tuple(
        PreparedSimilaritySource(
            value.profile.source_basis.source,
            InferenceTransferProfilePointer.from_profile(value.profile),
            value.profile.source_basis.solution_evidence,
        )
        for value in entries
    )
    selections = []
    document_rows = []
    dimension = embedding_space().model_spec.dimension
    one = (1.0,) + (0.0,) * (dimension - 1)
    for view, seed in zip(VIEWS, "123", strict=True):
        bindings = tuple(source_binding(value, view=view) for value in entries)
        index = index_manifest(*bindings, view=view, revision_seed=seed)
        # Each view owns a distinct logical namespace, not only a different revision.
        index = parse_embedding_index(
            seal(
                index.model_dump(mode="json")
                | {
                    "index_id": "embeddingindex_" + seed * 32,
                },
                "index_sha256",
            )
        )
        selection = SimilarityViewSelection(
            view=view,
            recipe=index.recipe,
            index=SimilarityIndexPin(
                index_id=index.index_id,
                index_revision_id=index.index_revision_id,
                index_manifest=index_pointer(index, seed),
                index_sha256=index.index_sha256,
                storage_partition=PARTITION,
                spaces=ReferenceQuerySpaces(
                    query=embedding_space(purpose="QUERY"), document=index.space
                ),
            ),
        )
        selections.append(selection)
        namespace = EmbeddingIndexNamespace(
            storage_partition=PARTITION,
            space_sha256=index.space.space_sha256,
            view=view,
            recipe_sha256=index.recipe.recipe_sha256,
            population_scope="OCCURRENCE_BACKED_PAST_EXAM",
        )
        unique_rows = {}
        for binding in bindings:
            values = one
            if view == "CONTENT_ONLY" and binding.source.item_revision_id.endswith("b" * 32):
                values = (0.6, 0.8) + (0.0,) * (dimension - 2)
            elif view == "CONTENT_ONLY" and binding.source.item_revision_id.endswith("c" * 32):
                values = (1 / sqrt(2), 1 / sqrt(2)) + (0.0,) * (dimension - 2)
            unique_rows[binding.encoding.encoding_sha256] = MaterializedEmbeddingReadRow(
                RegisteredEmbeddingRow(binding.encoding, binding.row_ref), values
            )
        document_rows.append(
            ResolvedPinnedEmbeddingIndex(
                EmbeddingRegistryRead(
                    EmbeddingRegistryLookup(
                        "corpus_" + "1" * 32,
                        namespace,
                        entries[0].profile.source_basis.graph_snapshot,
                        "accessrev_" + "d" * 32,
                        sha("d"),
                    ),
                    selection,
                ),
                tuple(value.source for value in prepared_sources),
                tuple(
                    AuthorizedEmbeddingReadProfile(value.source.item_revision_id, value.profile)
                    for value in prepared_sources
                    if value.profile is not None
                ),
                bindings,
                tuple(unique_rows[key] for key in sorted(unique_rows)),
            )
        )
    body = {
        "schema_version": "system-rag-similarity-request/1.0",
        "request_id": "similarityrequest_" + "a" * 32,
        "consumer_purpose": "PAST_EXAM_VARIATION",
        "anchor": ApprovedReferenceItemAnchor(
            source=prepared_sources[0].source,
            profile=prepared_sources[0].profile,
            solution_evidence=prepared_sources[0].solution_evidence,
        ).model_dump(mode="json"),
        "graph_snapshot": entries[0].profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "d" * 32,
        "policy_sha256": sha("d"),
        "source_classes": ["PAST_EXAM"],
        "topics": [],
        "unit_ids": [],
        "views": [value.model_dump(mode="json") for value in selections],
        "vector_mode": "OPTIONAL",
        "maximum_sources": 1024,
        "top_k": 2,
    }
    request = parse_similarity_context_request(seal(body, "request_sha256"))
    texts = tuple(
        (view, experiment_view_text(entries[0], view) or "")
        for view in VIEWS
        if view != missing_view
    )
    prepared = PreparedSimilarityContext(
        request.request_sha256,
        prepared_sources,
        texts,
        ((prepared_sources[2].source.item_revision_id, 1500),),
    )
    rows: list[dict[str, Any]] = sorted(
        (
            {
                "view": view,
                "encoding": encoding_identity(text, embedding_space(purpose="QUERY")).model_dump(
                    mode="json"
                ),
                "text": text,
            }
            for view, text in texts
        ),
        key=lambda value: value["encoding"]["encoding_sha256"],
    )
    assert selections[0].index is not None
    input_body = {
        "schema_version": "embedding-reference-query-input/1.0",
        "job_id": "job_" + "a" * 32,
        "query_request_id": "embeddingquery_" + "a" * 32,
        "context_request_sha256": request.request_sha256,
        "spaces": selections[0].index.spaces.model_dump(mode="json"),
        "recipe": view_recipe().model_dump(mode="json"),
        "rows": rows,
        "batch_size": 3,
        "threads": 1,
        "input_set_sha256": embedding_input_set_sha256(
            tuple(encoding_identity(row["text"], embedding_space(purpose="QUERY")) for row in rows)
        ),
    }
    query_input = parse_embedding_reference_query_input(seal(input_body, "request_sha256"))
    binary = pack_unit_vectors((one,) * len(rows), dimension=dimension)
    shard_body = vector_shard(
        tuple(row.encoding for row in query_input.rows), space=query_input.spaces.query
    ).model_dump(mode="json")
    shard_body["binary"]["sha256"] = sha256_bytes(binary)
    shard = EmbeddingVectorShardManifest.model_validate(seal(shard_body, "shard_sha256"))
    result_body = {
        "schema_version": "embedding-reference-query-result/1.0",
        "job_id": query_input.job_id,
        "query_request_id": query_input.query_request_id,
        "context_request_sha256": query_input.context_request_sha256,
        "request_sha256": query_input.request_sha256,
        "spaces": query_input.spaces.model_dump(mode="json"),
        "recipe": query_input.recipe.model_dump(mode="json"),
        "input_set_sha256": query_input.input_set_sha256,
        "shard": shard.model_dump(mode="json"),
        "view_rows": [
            {"view": row.view, "row_index": index, "encoding_sha256": row.encoding.encoding_sha256}
            for index, row in enumerate(query_input.rows)
        ],
    }
    result = parse_embedding_reference_query_result(seal(result_body, "result_sha256"))
    member = ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="result.json",
        schema_ref=REFERENCE_QUERY_RESULT_REF,
        media_type="application/json",
        sha256=content_sha256(result.model_dump(mode="json")),
    )
    document_rows = [row for row in document_rows if row.intent.selection.view != missing_view]
    return (
        request,
        Sources(prepared, tuple(document_rows)),
        Query(
            VerifiedReferenceQueryRead(
                query_input, result, member, shard_pointer(shard, "e"), binary
            )
        ),
    )


def test_three_independent_views_nonlexical_candidate_and_deterministic_display_only_result() -> (
    None
):
    request, sources, query = case()
    service = SimilarityContextApplicationService(sources, query)
    result = service.compose(CALLER, request)
    assert result.status == "READY", result
    assert result.population is not None and result.population.authorized_source_count == 3
    assert len(result.candidates) == 2
    assert (
        len(
            [
                value
                for value in result.candidates[0].observations
                if isinstance(value, SimilarityVectorObservation)
            ]
        )
        == 3
    )
    assert any(value.source.item_revision_id.endswith("b" * 32) for value in result.candidates)
    assert sources.calls == ["prepare", "read", "reauthorize"]
    again = service.compose(CALLER, request)
    assert canonical_json_bytes(result.model_dump(mode="json")) == canonical_json_bytes(
        again.model_dump(mode="json")
    )
    assert query.calls == 2  # Immutable query resolution, not encoding or model calls.


def test_explicit_input_v11_configured_batch_four_composes_without_resizing_rows() -> None:
    request, sources, query = case()
    assert isinstance(query.value, VerifiedReferenceQueryRead)
    original = query.value
    native = parse_embedding_reference_query_input_v11(
        seal(
            original.request.model_dump(mode="json")
            | {"schema_version": "embedding-reference-query-input/1.1", "batch_size": 4},
            "request_sha256",
        )
    )
    result = parse_embedding_reference_query_result(
        seal(
            original.result.model_dump(mode="json") | {"request_sha256": native.request_sha256},
            "result_sha256",
        )
    )
    member = ArtifactMemberPointer.model_validate(
        original.result_member.model_dump(mode="json")
        | {"sha256": content_sha256(result.model_dump(mode="json"))}
    )
    query.value = replace(original, request=native, result=result, result_member=member)
    context = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert context.status == "READY", context
    assert context.query_execution is not None
    assert context.query_execution.request_sha256 == native.request_sha256
    assert len(native.rows) == 3 and native.batch_size == 4
    assert len(context.candidates) == 2
    assert sources.calls == ["prepare", "read", "reauthorize"]


def test_input_v11_cannot_reuse_predecessor_result_hash_or_serialize_forged_values() -> None:
    request, sources, query = case()
    assert isinstance(query.value, VerifiedReferenceQueryRead)
    native = parse_embedding_reference_query_input_v11(
        seal(
            query.value.request.model_dump(mode="json")
            | {"schema_version": "embedding-reference-query-input/1.1", "batch_size": 4},
            "request_sha256",
        )
    )
    query.value = replace(query.value, request=native)
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "FAILED" and result.error_code == "QUERY_RESULT_INVALID"
    assert result.candidates == () and result.query_execution is None and result.population is None


@pytest.mark.parametrize("required", [False, True])
def test_optional_unoffered_query_preserves_graph_required_does_not(required: bool) -> None:
    request, sources, _query = case()
    if required:
        request = parse_similarity_context_request(
            seal(request.model_dump(mode="json") | {"vector_mode": "REQUIRED"}, "request_sha256")
        )
        sources.prepared = replace(sources.prepared, request_sha256=request.request_sha256)
    result = SimilarityContextApplicationService(sources).compose(CALLER, request)
    assert result.status == ("UNAVAILABLE" if required else "PARTIAL")
    assert len(result.candidates) == (0 if required else 1)
    assert result.query_execution is None
    assert sources.calls == ["prepare", "reauthorize"]
    assert result.population is not None
    assert all(value.reason == "QUERY_NOT_OFFERED" for value in result.population.views)


@pytest.mark.parametrize(
    "change",
    [
        "authority",
        "topics",
        "units",
        "chat",
        "revoke",
        "source",
        "document",
        "query_hash",
        "query_binary",
        "query_extra",
        "text",
        "missing_read",
    ],
)
def test_invalid_authority_or_integrity_fails_closed_without_partial_disclosure(
    change: str,
) -> None:
    request, sources, query = case()
    owner: Sources | None = sources
    if change in {"topics", "units", "chat"}:
        key, value = {
            "topics": ("topics", ["science.motion"]),
            "units": ("unit_ids", ["unit-motion"]),
            "chat": ("consumer_purpose", "GENERAL_CHAT_READ"),
        }[change]
        request = parse_similarity_context_request(
            seal(request.model_dump(mode="json") | {key: value}, "request_sha256")
        )
    elif change == "authority":
        owner = None
    elif change == "revoke":
        sources.denial = "revoked"
    elif change == "source":
        sources.prepared = replace(sources.prepared, sources=sources.prepared.sources[:1])
    elif change == "document":
        sources.reads = (replace(sources.reads[0], sources=()), *sources.reads[1:])
    elif change == "missing_read":
        sources.reads = sources.reads[:1]
    elif change == "text":
        sources.prepared = replace(
            sources.prepared,
            query_texts=(("CONTENT_ONLY", "다른 조건"), *sources.prepared.query_texts[1:]),
        )
    else:
        assert isinstance(query.value, VerifiedReferenceQueryRead)
        if change == "query_binary":
            query.value = replace(query.value, binary=query.value.binary[:-1])
        elif change == "query_hash":
            query.value = replace(
                query.value,
                result_member=query.value.result_member.model_copy(update={"sha256": sha("f")}),
            )
        else:
            query.value = replace(
                query.value, request=query.value.request.model_copy(update={"authority": "ADMIN"})
            )
    result = SimilarityContextApplicationService(owner, query).compose(CALLER, request)
    assert result.status == "FAILED", (change, result)
    assert result.population is None and not result.candidates and result.graph_evidence is None
    if change in {"authority", "topics", "units", "chat"}:
        assert not sources.calls


def test_explicit_overflow_never_truncates_or_reads_documents() -> None:
    request, sources, _query = case()
    result = SimilarityContextApplicationService(
        sources, Query(SimilarityQueryUnavailable("INPUT_OVERFLOW"))
    ).compose(CALLER, request)
    assert result.status == "PARTIAL" and result.population is not None
    assert all(value.reason == "INPUT_OVERFLOW" for value in result.population.views)
    assert "read" not in sources.calls


def test_missing_anchor_report_and_partial_report_population_are_not_fabricated() -> None:
    request, sources, query = case()
    request = parse_similarity_context_request(
        seal(
            request.model_dump(mode="json")
            | {
                "anchor": request.anchor.model_dump(mode="json")
                | {"profile": None, "solution_evidence": None},
            },
            "request_sha256",
        )
    )
    sources.prepared = replace(
        sources.prepared,
        request_sha256=request.request_sha256,
        sources=(
            replace(sources.prepared.sources[0], profile=None, solution_evidence=None),
            *sources.prepared.sources[1:],
        ),
        query_texts=(),
    )
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "PARTIAL" and result.population is not None
    assert result.population.missing_report_count == 1
    assert all(value.reason == "ANCHOR_REPORT_MISSING" for value in result.population.views)
    assert query.calls == 0 and "read" not in sources.calls


def test_available_query_views_can_be_partial_without_inventing_missing_metadata() -> None:
    request, sources, query = case(missing_view="METADATA_ONLY")
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "PARTIAL" and result.population is not None
    assert result.population.views[2].reason == "VIEW_INPUT_MISSING"
    assert result.query_execution is not None
    assert all(len(value.observations) <= 3 for value in result.candidates)


def test_no_report_member_remains_in_authorized_denominator_but_not_profile_or_vector_pool() -> (
    None
):
    request, sources, query = case()
    no_report = PreparedSimilaritySource(
        embedding_entry("d").profile.source_basis.source, None, None
    )
    sources.prepared = replace(sources.prepared, sources=(*sources.prepared.sources, no_report))
    sources.reads = tuple(
        replace(value, sources=(*value.sources, no_report.source)) for value in sources.reads
    )
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "PARTIAL" and result.population is not None
    assert result.population.authorized_source_count == 4
    assert result.population.accepted_profile_count == 3
    assert result.population.missing_report_count == 1
    assert all(value.source != no_report.source for value in result.candidates)


def test_ranking_uses_unrounded_scores_when_two_display_millionths_are_equal() -> None:
    request, sources, query = case()
    value = sources.reads[0]
    changed = []
    for row in value.numerical_rows:
        binding = next(
            binding for binding in value.bindings if binding.encoding == row.row.encoding
        )
        score = 0.60000001 if binding.source.item_revision_id.endswith("b" * 32) else 0.60000002
        if binding.source.item_revision_id != request.anchor.source.item_revision_id:
            changed.append(replace(row, values=(score, sqrt(1 - score * score), *row.values[2:])))
        else:
            changed.append(row)
    sources.reads = (replace(value, numerical_rows=tuple(changed)), *sources.reads[1:])
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "READY"
    rows = [
        row
        for candidate in result.candidates
        for row in candidate.observations
        if isinstance(row, SimilarityVectorObservation) and row.view == "CONTENT_ONLY"
    ]
    assert {row.cosine_millionths for row in rows} == {600000}
    assert result.candidates[0].source.item_revision_id.endswith("c" * 32)


@pytest.mark.parametrize(
    "malformed",
    ["intent", "selection", "source", "profile", "row", "encoding", "row_ref", "query_member"],
)
def test_malformed_nested_owner_values_return_stable_failure_not_attribute_error(
    malformed: str,
) -> None:
    request, sources, query = case()
    original = sources.reads[0]
    bad: Any = "bad"  # Deliberately malformed owner output, never an admitted contract fixture.
    if malformed == "query_member":
        assert isinstance(query.value, VerifiedReferenceQueryRead)
        query.value = replace(query.value, result_member=bad)
    else:
        if malformed == "intent":
            changed = replace(original, intent=bad)
        elif malformed == "selection":
            changed = replace(original, intent=replace(original.intent, selection=bad))
        elif malformed == "source":
            changed = replace(original, sources=(bad,))
        elif malformed == "profile":
            changed = replace(original, profiles=(bad,))
        else:
            row = original.numerical_rows[0]
            if malformed == "row":
                updated = replace(row, row=bad)
            elif malformed == "encoding":
                updated = replace(row, row=replace(row.row, encoding=bad))
            else:
                updated = replace(row, row=replace(row.row, row_ref=bad))
            changed = replace(original, numerical_rows=(updated,))
        sources.reads = (changed, *sources.reads[1:])
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "FAILED" and result.population is None
    assert result.error_code == (
        "QUERY_RESULT_INVALID" if malformed == "query_member" else "INDEX_POINTER_INVALID"
    )


def test_missing_public_owner_seams_are_not_implicit_grants() -> None:
    request, sources, _query = case()
    result = SimilarityContextApplicationService(cast(Any, object())).compose(CALLER, request)
    assert result.status == "FAILED" and result.error_code == "AUTHORITY_UNAVAILABLE"
    result = SimilarityContextApplicationService(sources, cast(Any, object())).compose(
        CALLER, request
    )
    assert result.status == "PARTIAL" and result.query_execution is None
    assert result.population is not None
    assert all(value.reason == "QUERY_NOT_OFFERED" for value in result.population.views)


def test_related_pool_empty_does_not_claim_query_scoring_or_confuse_anchor_with_candidate() -> None:
    request, sources, query = case()
    sources.prepared = replace(
        sources.prepared, sources=sources.prepared.sources[:1], graph_scores=()
    )
    values = []
    for value in sources.reads:
        binding = value.bindings[0]
        rows = tuple(row for row in value.numerical_rows if row.row.encoding == binding.encoding)
        values.append(
            replace(
                value,
                sources=value.sources[:1],
                profiles=value.profiles[:1],
                bindings=(binding,),
                numerical_rows=rows,
            )
        )
    sources.reads = tuple(values)
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert result.status == "EMPTY" and not result.candidates and result.query_execution is None
    assert result.population is not None and result.population.accepted_profile_count == 1
    assert all(value.scored_count == 0 for value in result.population.views)
