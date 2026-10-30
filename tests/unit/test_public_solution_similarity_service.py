"""Pure public composition with synthetic source/registered rows and a fake encoder backend."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryInput,
)
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_similarity_service import (
    VerifiedPublicSolutionQueryRead,
    compose_public_solution_similarity,
    prepare_public_solution_query_source,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_public_solution_similarity_contracts import member, public_similarity_case


def composition_case():
    request, _, query_input, _, data = public_similarity_case()
    entries, registered, _, namespace, space = data
    capture = ResolvedEmbeddingLookup(
        "corpus_" + "1" * 32,
        space,
        request.views[0].recipe,
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
    from tests.unit.test_public_solution_index_assembly import assemble

    index = assemble(data).index
    one = (1.0,) + (0.0,) * (space.model_spec.dimension - 1)
    document = ResolvedPinnedEmbeddingIndex(
        EmbeddingRegistryRead(scope, request.views[0]),
        capture.sources,
        tuple(
            AuthorizedEmbeddingReadProfile(
                entry.source.item_revision_id,
                PublicSolutionSourceReference.from_entry(entry).profile,
            )
            for entry in entries
        ),
        index.bindings,
        tuple(MaterializedEmbeddingReadRow(row, one) for row in registered),
    )
    backend = SyntheticNativeBackend(query_input.spaces.query)
    backend.batch_size, backend.threads = query_input.batch_size, query_input.threads
    encoded = encode_public_solution_query(query_input, backend)
    result = encoded.result
    query = VerifiedPublicSolutionQueryRead(
        query_input,
        result,
        member(result, schema=PUBLIC_SOLUTION_QUERY_RESULT_REF, name="result.json"),
        member(
            result.shard,
            schema="eom://schemas/knowledge/embedding-vector-shard/1.0",
            name="shard.json",
        ),
        encoded.vectors,
    )
    return request, capture, document, query


def test_public_composer_uses_common_report_text_and_real_query_purpose_without_source_merge():
    request, capture, document, query = composition_case()
    result = compose_public_solution_similarity(request, capture, document, query)
    assert result.status == "READY"
    assert result.population.available_report_count == 2
    assert result.population.available_binding_count == 2
    assert result.population.scored_count == 1
    assert result.candidates[0].source != request.anchor.source
    assert result.candidates[0].observation.cosine_millionths == 1000000
    assert result.query_execution.result_sha256 == query.result.result_sha256
    assert result == compose_public_solution_similarity(request, capture, document, query)
    assert "public_solution" not in result.model_dump_json()
    assert "SCORE_IS_NOT_PROOF_OF_IDENTICAL_REASONING" in result.limitations


def test_query_source_uses_exact_common_report_text_but_not_document_encoding_identity():
    request, capture, document, query = composition_case()
    prepared = prepare_public_solution_query_source(request, capture)
    assert prepared.request_sha256 == request.request_sha256
    assert prepared.anchor == request.anchor
    assert prepared.row == query.request.rows[0]
    assert prepared.row.encoding.space_sha256 == request.views[0].index.spaces.query.space_sha256
    assert prepared.row.encoding.space_sha256 != request.views[0].index.spaces.document.space_sha256
    assert prepared.row.text == capture.entries[0].public_solution.text
    assert prepared.row.encoding not in tuple(binding.encoding for binding in document.bindings)


@pytest.mark.parametrize("fault", ["missing_anchor", "extra", "base", "foreign_request"])
def test_query_source_preparation_rejects_foreign_or_unvalidated_report(fault):
    request, capture, _, _ = composition_case()
    if fault == "missing_anchor":
        capture = replace(capture, entries=())
    elif fault == "extra":
        capture = replace(
            capture,
            entries=(
                capture.entries[0].model_copy(update={"authority": "ADMIN"}),
                *capture.entries[1:],
            ),
        )
    elif fault == "base":
        capture = replace(capture, base_analysis_run_ids=())
    else:
        request = request.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    with pytest.raises((ValueError, SchemaError)):
        prepare_public_solution_query_source(request, capture)


@pytest.mark.parametrize(
    "target",
    ["request", "entry", "nested_report", "query", "result", "member", "profile", "binding"],
)
def test_public_composition_does_not_erase_undeclared_copied_fields_before_validation(target):
    request, capture, document, query = composition_case()
    if target == "request":
        request = request.model_copy(update={"unexpected": True})
    elif target in {"entry", "nested_report"}:
        entry = capture.entries[0]
        entry = (
            entry.model_copy(update={"unexpected": True})
            if target == "entry"
            else entry.model_copy(
                update={
                    "public_solution": entry.public_solution.model_copy(update={"unexpected": True})
                }
            )
        )
        capture = replace(capture, entries=(entry, *capture.entries[1:]))
    elif target == "query":
        query = replace(query, request=query.request.model_copy(update={"unexpected": True}))
    elif target == "result":
        query = replace(query, result=query.result.model_copy(update={"unexpected": True}))
    elif target == "member":
        query = replace(
            query, result_member=query.result_member.model_copy(update={"unexpected": True})
        )
    elif target == "profile":
        first = document.profiles[0]
        document = replace(
            document,
            profiles=(
                replace(first, profile=first.profile.model_copy(update={"unexpected": True})),
                *document.profiles[1:],
            ),
        )
    else:
        document = replace(
            document,
            bindings=(
                document.bindings[0].model_copy(update={"unexpected": True}),
                *document.bindings[1:],
            ),
        )
    with pytest.raises((ValueError, SchemaError)):
        compose_public_solution_similarity(request, capture, document, query)


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "base",
        "recipe",
        "missing_anchor",
        "duplicate",
        "profile",
        "binding",
        "row",
        "scope",
        "extra_row",
        "query_context",
        "query_text",
        "query_member",
        "query_binary",
        "nan",
        "norm",
    ],
)
def test_public_composition_rejects_foreign_proofs_or_numerics(fault):
    request, capture, document, query = composition_case()
    if fault == "source":
        capture = replace(capture, sources=capture.sources[:1])
    elif fault == "base":
        capture = replace(
            capture,
            base_analysis_run_ids=tuple(
                (key, "analysisrun_" + "f" * 32) for key, _ in capture.base_analysis_run_ids
            ),
        )
    elif fault == "recipe":
        capture = replace(capture, space=query.request.spaces.query)
    elif fault == "missing_anchor":
        capture = replace(
            capture,
            entries=tuple(
                entry for entry in capture.entries if entry.source != request.anchor.source
            ),
        )
    elif fault == "duplicate":
        capture = replace(capture, entries=capture.entries * 2)
    elif fault == "profile":
        document = replace(document, profiles=document.profiles[:1])
    elif fault == "binding":
        binding = document.bindings[0]
        document = replace(
            document,
            bindings=(binding.model_copy(update={"binding_sha256": "sha256:" + "f" * 64}),),
        )
    elif fault == "row":
        document = replace(document, numerical_rows=())
    elif fault == "scope":
        intent = replace(
            document.intent,
            scope=replace(document.intent.scope, policy_sha256="sha256:" + "f" * 64),
        )
        document = replace(document, intent=intent)
    elif fault == "extra_row":
        document = replace(document, numerical_rows=document.numerical_rows * 2)
    elif fault == "query_context":
        query = replace(
            query,
            request=PublicSolutionQueryInput.model_validate(
                seal(
                    query.request.model_dump(mode="json")
                    | {"context_request_sha256": "sha256:" + "f" * 64},
                    "request_sha256",
                )
            ),
        )
    elif fault == "query_text":
        query = replace(query, request=query.request.model_copy(update={"rows": ()}))
    elif fault == "query_member":
        query = replace(
            query,
            shard_member=query.shard_member.model_copy(
                update={"artifact_id": "artifact_" + "f" * 32}
            ),
        )
    elif fault == "query_binary":
        query = replace(query, binary=b"bad")
    else:
        value = float("nan") if fault == "nan" else 2.0
        row = document.numerical_rows[0]
        document = replace(
            document, numerical_rows=(replace(row, values=(value, *row.values[1:])),)
        )
    with pytest.raises((ValueError, SchemaError)):
        compose_public_solution_similarity(request, capture, document, query)


def test_partial_coverage_is_preserved_instead_of_inventing_vectors_or_hiding_sources():
    request, capture, document, query = composition_case()
    remaining = tuple(
        binding for binding in document.bindings if binding.source != request.anchor.source
    )
    # Both sources share one exact encoding. Removing only the anchor binding
    # preserves the canonical row and still allows the real query to rank the other source.
    document = replace(document, bindings=remaining)
    result = compose_public_solution_similarity(request, capture, document, query)
    assert result.status == "PARTIAL"
    assert result.population.available_binding_count == 1
    assert result.population.scored_count == 1
    assert "PARTIAL_VIEW_COVERAGE" in result.limitations
    assert result.population.binding_set_sha256 == content_sha256([remaining[0].binding_sha256])
