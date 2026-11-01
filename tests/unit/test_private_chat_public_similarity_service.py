"""Synthetic owned question and common public rows; not live authorization or GPU evidence."""

from dataclasses import fields, replace
from functools import lru_cache

import pytest
from eom_catalog_contracts.private_chat_similarity_v2 import (
    PrivateChatSimilarityRequestV2,
    validate_private_chat_public_query_execution,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.private_chat_public_similarity_service import (
    compose_private_chat_public_similarity,
)
from eom_catalog_service.public_solution_similarity_service import VerifiedPublicSolutionQueryRead
from eom_orchestrator.general_chat_public_query_projection import project_private_chat_public_query
from eom_orchestrator.general_chat_similarity_basis import PreparedPrivateChatQuery
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_query_basis import TEXT, basis
from tests.unit.test_public_solution_similarity_contracts import member
from tests.unit.test_registered_public_solution_similarity_service import (
    registered_composition_case,
)


@lru_cache(maxsize=1)
def private_public_case():
    original, capture, document, prior = registered_composition_case()
    body = original.model_dump(mode="json")
    del body["anchor"]
    body.update(
        schema_version="system-rag-private-chat-similarity-request/2.0",
        consumer_purpose="GENERAL_CHAT_READ",
        query_basis=basis().model_dump(mode="json"),
        vector_mode="REQUIRED",
    )
    request = PrivateChatSimilarityRequestV2.model_validate(seal(body, "request_sha256"))
    prepared = project_private_chat_public_query(
        PreparedPrivateChatQuery(request.query_basis, TEXT),
        original.views[0],
        context_request_sha256=request.request_sha256,
        job_id=prior.request.job_id,
        query_request_id=prior.request.query_request_id,
        batch_size=prior.request.batch_size,
        threads=prior.request.threads,
    )
    backend = SyntheticNativeBackend(prepared.native.spaces.query)
    backend.batch_size, backend.threads = prepared.native.batch_size, prepared.native.threads
    encoded = encode_public_solution_query(prepared.native, backend)
    query = VerifiedPublicSolutionQueryRead(
        prepared.native,
        encoded.result,
        member(
            encoded.result,
            schema="eom://schemas/knowledge/embedding-reference-query-result/2.0",
            name="result.json",
        ),
        member(
            encoded.result.shard,
            schema="eom://schemas/knowledge/embedding-vector-shard/1.0",
            name="shard.json",
        ),
        encoded.vectors,
    )
    return request, capture, document, query


def compose(request, capture, document, query, *, text=TEXT):
    return compose_private_chat_public_similarity(
        request, capture, document, query, question_text=text
    )


def test_private_question_ranks_all_three_source_kinds_without_a_fictional_self_anchor():
    request, capture, document, query = private_public_case()
    result = compose(request, capture, document, query)
    assert result.status == "READY"
    assert result.population.authorized_source_count == 3
    assert result.population.available_report_count == result.population.scored_count == 3
    assert len(result.candidates) == 3
    assert {candidate.evidence.kind for candidate in result.candidates} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    assert len(document.numerical_rows) == 1
    assert all(
        candidate.observation.cosine_millionths == 1_000_000 for candidate in result.candidates
    )
    assert result.query_execution.basis_sha256 == request.query_basis.basis_sha256
    assert result.query_execution.result_sha256 == query.result.result_sha256
    assert TEXT not in result.model_dump_json()
    assert repr(TEXT) not in repr(query)
    representation = {field.name: field.repr for field in fields(query)}
    assert representation["request"] is False and representation["binary"] is False
    assert all(
        entry.public_solution.text not in result.model_dump_json() for entry in capture.entries
    )
    assert result == compose(request, capture, document, query)
    validate_private_chat_public_query_execution(
        result, query.request, query.result, query.result_member, query.shard_member
    )


@pytest.mark.parametrize("coverage", ("report", "binding", "truncated"))
def test_missing_coverage_is_reported_without_fallback_vectors_or_disappearing_sources(coverage):
    request, capture, document, query = private_public_case()
    if coverage == "report":
        removed = capture.entries[-1].source.item_revision_id
        capture = replace(capture, entries=capture.entries[:-1])
        document = replace(
            document,
            profiles=tuple(p for p in document.profiles if p.source_item_revision_id != removed),
            bindings=tuple(b for b in document.bindings if b.source.item_revision_id != removed),
        )
    elif coverage == "binding":
        document = replace(document, bindings=document.bindings[:-1])
    else:
        capture = replace(capture, truncated=True)
    result = compose(request, capture, document, query)
    assert result.status == "PARTIAL"
    assert result.population.authorized_source_count == 3
    assert result.population.scored_count == len(document.bindings)
    assert {
        "report": "PARTIAL_REPORT_COVERAGE",
        "binding": "PARTIAL_VIEW_COVERAGE",
        "truncated": "BOUNDED_SCOPE_TRUNCATED",
    }[coverage] in result.limitations


@pytest.mark.parametrize("authorized_count", (0, 3))
def test_empty_coverage_needs_no_fake_native_query_and_keeps_known_scope(authorized_count):
    request, capture, document, _ = private_public_case()
    capture = replace(
        capture,
        sources=capture.sources[:authorized_count],
        entries=(),
        base_analysis_run_ids=capture.base_analysis_run_ids[:authorized_count],
    )
    document = replace(
        document, sources=capture.sources, profiles=(), bindings=(), numerical_rows=()
    )
    result = compose(request, capture, document, None)
    assert result.status == "EMPTY" and result.query_execution is None
    assert result.population.authorized_source_count == authorized_count
    assert result.population.scored_count == 0 and result.candidates == ()
    assert "NO_RELATED_CANDIDATES" in result.limitations
    assert ("PARTIAL_REPORT_COVERAGE" in result.limitations) == bool(authorized_count)


def test_no_bindings_cannot_hide_an_unnecessary_query_or_make_zero_vectors():
    request, capture, document, query = private_public_case()
    document = replace(document, bindings=(), numerical_rows=())
    assert compose(request, capture, document, None).status == "EMPTY"
    with pytest.raises(ValueError):
        compose(request, capture, document, query)
    with pytest.raises(ValueError):
        compose(
            request, capture, replace(document, bindings=private_public_case()[2].bindings), None
        )


@pytest.mark.parametrize(
    "fault",
    (
        "text",
        "request_extra",
        "entry_extra",
        "report_extra",
        "duplicate_source",
        "foreign_base",
        "foreign_recipe",
        "source_class",
        "scope",
        "profile",
        "binding",
        "row",
        "extra_row",
        "nan",
        "norm",
        "query_extra",
        "result_extra",
        "query_member",
        "query_binary",
        "query_context",
        "query_basis",
        "query_space",
        "no_query",
    ),
)
def test_private_common_composition_rejects_wrong_proofs_and_original_query_association(fault):
    request, capture, document, query = private_public_case()
    text = TEXT
    if fault == "text":
        text = TEXT.strip()
    elif fault == "request_extra":
        request = request.model_copy(update={"authority": "ADMIN"})
    elif fault in {"entry_extra", "report_extra"}:
        first = capture.entries[0]
        first = (
            first.model_copy(update={"authority": "ADMIN"})
            if fault == "entry_extra"
            else first.model_copy(
                update={
                    "public_solution": first.public_solution.model_copy(
                        update={"private_reasoning": "not allowed"}
                    )
                }
            )
        )
        capture = replace(capture, entries=(first, *capture.entries[1:]))
    elif fault == "duplicate_source":
        capture = replace(capture, sources=capture.sources * 2)
    elif fault == "foreign_base":
        capture = replace(capture, base_analysis_run_ids=())
    elif fault == "foreign_recipe":
        capture = replace(capture, space=query.request.spaces.query)
    elif fault in {"source_class", "query_basis"}:
        body = request.model_dump(mode="json")
        if fault == "source_class":
            body["source_classes"] = ["PAST_EXAM"]
        else:
            body["query_basis"]["turn_id"] = "chatturn_" + "9" * 32
            body["query_basis"] = seal(body["query_basis"], "basis_sha256")
        request = PrivateChatSimilarityRequestV2.model_validate(seal(body, "request_sha256"))
    elif fault == "scope":
        document = replace(
            document,
            intent=replace(
                document.intent,
                scope=replace(document.intent.scope, policy_sha256="sha256:" + "f" * 64),
            ),
        )
    elif fault == "profile":
        document = replace(document, profiles=document.profiles[:-1])
    elif fault == "binding":
        document = replace(
            document,
            bindings=(
                document.bindings[0].model_copy(update={"binding_sha256": "sha256:" + "f" * 64}),
            ),
        )
    elif fault == "row":
        document = replace(document, numerical_rows=())
    elif fault == "extra_row":
        document = replace(document, numerical_rows=document.numerical_rows * 2)
    elif fault in {"nan", "norm"}:
        row = document.numerical_rows[0]
        document = replace(
            document,
            numerical_rows=(
                replace(row, values=(float("nan") if fault == "nan" else 2.0, *row.values[1:])),
            ),
        )
    elif fault == "query_extra":
        query = replace(query, request=query.request.model_copy(update={"authority": "ADMIN"}))
    elif fault == "result_extra":
        query = replace(query, result=query.result.model_copy(update={"authority": "ADMIN"}))
    elif fault == "query_member":
        query = replace(
            query,
            shard_member=query.shard_member.model_copy(
                update={"artifact_id": "artifact_" + "f" * 32}
            ),
        )
    elif fault == "query_binary":
        query = replace(query, binary=b"invalid")
    elif fault in {"query_context", "query_space"}:
        body = request.model_dump(mode="json")
        if fault == "query_context":
            body["request_id"] = "similarityrequest_" + "f" * 32
        else:
            body["views"][0]["index"]["storage_partition"] = "partition_" + "f" * 32
        request = PrivateChatSimilarityRequestV2.model_validate(seal(body, "request_sha256"))
    else:
        query = None
    with pytest.raises((ValueError, SchemaError)):
        compose(request, capture, document, query, text=text)


def test_invalid_private_numerical_input_never_exposes_question_in_schema_error():
    request, capture, document, query = private_public_case()
    query = replace(query, request=query.request.model_copy(update={"authority": TEXT}))
    with pytest.raises(ValueError, match=r"^QUERY_RESULT_INVALID$") as caught:
        compose(request, capture, document, query)
    assert str(caught.value) == "QUERY_RESULT_INVALID"
    assert caught.value.__suppress_context__


def test_reordering_capture_does_not_change_context_hash_or_exact_tie_order():
    request, capture, document, query = private_public_case()
    original = compose(request, capture, document, query)
    reordered = compose(
        request,
        replace(
            capture,
            sources=tuple(reversed(capture.sources)),
            entries=tuple(reversed(capture.entries)),
            base_analysis_run_ids=tuple(reversed(capture.base_analysis_run_ids)),
        ),
        replace(
            document,
            sources=tuple(reversed(document.sources)),
            profiles=tuple(reversed(document.profiles)),
            bindings=tuple(reversed(document.bindings)),
        ),
        query,
    )
    assert reordered == original
