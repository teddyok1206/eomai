"""Mixed report provenance over one existing row and QUERY2; synthetic owner leaves."""

from dataclasses import replace
from functools import lru_cache

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryInput,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityContextV4,
    PublicSolutionSimilarityRequestV4,
    public_solution_reference_for_entry,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index,
)
from eom_catalog_service.public_solution_similarity_service import (
    VerifiedPublicSolutionQueryRead,
    compose_public_solution_similarity,
    prepare_public_solution_query_source,
)
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_public_solution_similarity_contracts import member, public_similarity_case
from tests.unit.test_registered_public_solution_index import registered_index_entry


@lru_cache(maxsize=3)
def registered_composition_case(anchor_kind="ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"):
    original, _, numerical, _, data = public_similarity_case()
    previous, rows, shards, namespace, space = data
    entries = tuple(
        sorted(
            (*previous, registered_index_entry()), key=lambda entry: entry.source.item_revision_id
        )
    )
    index = assemble_registered_public_solution_index(
        entries,
        available_rows=rows,
        shards=shards,
        namespace=namespace,
        space=space,
        index_id=original.views[0].index.index_id,
        index_revision_id="embeddingindexrev_" + "4" * 32,
        previous_manifest=None,
        created_at=NOW,
    ).index
    anchor = next(entry for entry in entries if entry.evidence.kind == anchor_kind)
    body = original.model_dump(mode="json")
    body.update(
        schema_version="system-rag-similarity-request/4.0",
        anchor=public_solution_reference_for_entry(anchor).model_dump(mode="json"),
    )
    body["views"][0]["index"].update(
        index_revision_id=index.index_revision_id,
        index_sha256=index.index_sha256,
        index_manifest=member(
            index,
            schema="eom://schemas/knowledge/embedding-index-manifest/4.0",
            name="index.json",
            seed="e",
        ).model_dump(mode="json"),
    )
    request = PublicSolutionSimilarityRequestV4.model_validate(seal(body, "request_sha256"))
    capture = ResolvedEmbeddingLookup(
        "corpus_" + "1" * 32,
        space,
        anchor.recipe,
        tuple(entry.source for entry in entries),
        entries,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in entries
        ),
    )
    scope = EmbeddingRegistryLookup(
        capture.corpus_id,
        namespace,
        request.graph_snapshot,
        request.policy_revision_id,
        request.policy_sha256,
        request.maximum_sources,
    )
    document = ResolvedPinnedEmbeddingIndex(
        EmbeddingRegistryRead(scope, request.views[0]),
        capture.sources,
        tuple(
            AuthorizedEmbeddingReadProfile(
                entry.source.item_revision_id, public_solution_reference_for_entry(entry).profile
            )
            for entry in entries
        ),
        index.bindings,
        tuple(
            MaterializedEmbeddingReadRow(row, (1.0,) + (0.0,) * (space.model_spec.dimension - 1))
            for row in rows
        ),
    )
    prepared = prepare_public_solution_query_source(request, capture)
    numerical = PublicSolutionQueryInput.model_validate(
        seal(
            numerical.model_dump(mode="json")
            | {
                "context_request_sha256": request.request_sha256,
                "rows": [prepared.row.model_dump(mode="json")],
                "input_set_sha256": embedding_input_set_sha256((prepared.row.encoding,)),
            },
            "request_sha256",
        )
    )
    backend = SyntheticNativeBackend(numerical.spaces.query)
    backend.batch_size, backend.threads = numerical.batch_size, numerical.threads
    encoded = encode_public_solution_query(numerical, backend)
    query = VerifiedPublicSolutionQueryRead(
        numerical,
        encoded.result,
        member(encoded.result, schema=PUBLIC_SOLUTION_QUERY_RESULT_REF, name="result.json"),
        member(
            encoded.result.shard,
            schema="eom://schemas/knowledge/embedding-vector-shard/1.0",
            name="shard.json",
        ),
        encoded.vectors,
    )
    return request, capture, document, query


@pytest.mark.parametrize(
    "anchor_kind",
    [
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    ],
)
def test_all_three_source_kinds_rank_through_same_query2_text_row_and_one_document_row(anchor_kind):
    request, capture, document, query = registered_composition_case(anchor_kind)
    result = compose_public_solution_similarity(request, capture, document, query)
    assert isinstance(result, PublicSolutionSimilarityContextV4) and result.status == "READY"
    assert (
        result.population.available_binding_count == result.population.available_report_count == 3
    )
    assert result.population.scored_count == len(result.candidates) == 2
    assert query.request.schema_version == "embedding-reference-query-input/2.0"
    assert query.result.schema_version == "embedding-reference-query-result/2.0"
    assert len(document.numerical_rows) == 1
    assert {entry.public_solution.text for entry in capture.entries} == {query.request.rows[0].text}
    assert all(
        entry.public_solution.text not in result.model_dump_json() for entry in capture.entries
    )
    assert request.anchor.source.item_revision_id not in {
        entry.source.item_revision_id for entry in result.candidates
    }


def test_missing_anchor_document_vector_still_ranks_other_sources_as_partial():
    request, capture, document, query = registered_composition_case()
    document = replace(
        document,
        bindings=tuple(
            binding for binding in document.bindings if binding.source != request.anchor.source
        ),
    )
    result = compose_public_solution_similarity(request, capture, document, query)
    assert result.status == "PARTIAL" and result.population.scored_count == 2
    assert result.population.available_binding_count == 2
    assert "PARTIAL_VIEW_COVERAGE" in result.limitations


@pytest.mark.parametrize(
    "fault",
    [
        "missing_source",
        "wrong_profile",
        "wrong_base",
        "query_provenance",
        "query_binary",
        "undeclared_entry",
    ],
)
def test_registered_proof_or_numeric_mismatch_is_not_tolerated(fault):
    request, capture, document, query = registered_composition_case()
    if fault == "missing_source":
        capture = replace(capture, entries=capture.entries[:-1])
    elif fault == "wrong_profile":
        document = replace(document, profiles=document.profiles[:-1])
    elif fault == "wrong_base":
        capture = replace(
            capture,
            base_analysis_run_ids=tuple(
                (key, "analysisrun_" + "0" * 32) for key, _ in capture.base_analysis_run_ids
            ),
        )
    elif fault == "query_provenance":
        query = replace(
            query,
            request=query.request.model_copy(
                update={"context_request_sha256": "sha256:" + "0" * 64}
            ),
        )
    elif fault == "query_binary":
        query = replace(query, binary=b"corrupt")
    else:
        entry = next(
            entry
            for entry in capture.entries
            if entry.evidence.kind == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
        )
        forged = entry.model_copy(update={"permission_override": True})
        capture = replace(
            capture,
            entries=tuple(
                forged if original is entry else original for original in capture.entries
            ),
        )
    with pytest.raises((ValueError, SchemaError)):
        compose_public_solution_similarity(request, capture, document, query)
