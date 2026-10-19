"""Mixed metadata preserves real evidence families and all released query bytes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    EmbeddingReferenceQueryResult,
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_context_v2 import (
    AcceptedSimilarityCandidateV2,
    RegisteredReviewSimilarityCandidateV2,
    SimilarityContextV2,
    parse_similarity_context_request_v2,
    parse_similarity_context_v2,
    parse_supported_similarity_context,
    parse_supported_similarity_context_request,
    validate_similarity_index_pin_v2,
    validate_similarity_query_execution_v2,
)
from eom_catalog_contracts.similarity_materials_v2 import (
    build_similarity_materials_v2,
    validate_similarity_materials_v2,
)
from eom_catalog_contracts.similarity_read import SimilarityContextReadReply
from eom_catalog_contracts.similarity_read_v2 import (
    SimilarityContextReadReplyV2,
    SimilarityContextReadRequestV2,
    validate_similarity_read_reply_v2,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_embedding_index_assembly_v2 import pointer
from tests.unit.test_embedding_reference_query_contracts import query_input_body, query_result_body
from tests.unit.test_similarity_context_contracts import context_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def mixed_context_body() -> dict[str, Any]:
    body = context_body()
    body["schema_version"] = "system-rag-similarity-context/2.0"
    request = body["request"]
    request["schema_version"] = "system-rag-similarity-request/2.0"
    for view in request["views"]:
        view["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    body["request"] = seal(request, "request_sha256")
    population = body["population"]
    for old, new in (
        ("accepted_profile_count", "available_profile_count"),
        ("accepted_profile_set_sha256", "available_profile_set_sha256"),
        ("missing_report_count", "missing_evidence_count"),
    ):
        population[new] = population.pop(old)
    candidate = body["candidates"][0]
    candidate["evidence_kind"] = "REGISTERED_ITEM_REVIEW_SOLUTION"
    entry = mixed_embedding_case()[0]
    candidate["source"] = entry.profile.source_basis.source.model_dump(mode="json")
    candidate["profile"] = RegisteredReviewProfilePointer.from_profile(entry.profile).model_dump(
        mode="json"
    )
    candidate["review_evidence"] = entry.profile.source_basis.review_evidence.model_dump(
        mode="json"
    )
    del candidate["solution_evidence"]
    return seal(body, "context_sha256")


@pytest.mark.parametrize("name", ["context", "materials", "read"])
def test_new_resources_are_mirrored_draft2020_and_hash_pinned(name: str) -> None:
    resource = CATALOG_SCHEMA_RESOURCES[f"system-rag-similarity-{name}-v2"]
    payload = (ROOT / resource.canonical_path).read_bytes()
    assert (
        payload
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(payload) == resource.sha256
    Draft202012Validator.check_schema(load_schema(f"system-rag-similarity-{name}-v2"))


def test_explicit_review_candidate_does_not_forge_accepted_solution_or_erase_profile2() -> None:
    context = parse_similarity_context_v2(mixed_context_body())
    assert isinstance(context, SimilarityContextV2)
    candidate = context.candidates[0]
    assert isinstance(candidate, RegisteredReviewSimilarityCandidateV2)
    assert isinstance(candidate.profile, RegisteredReviewProfilePointer)
    assert not isinstance(candidate.profile, InferenceTransferProfilePointer)
    assert not hasattr(candidate, "solution_evidence")
    assert context.population is not None
    assert not hasattr(context.population, "accepted_profile_count")
    assert parse_supported_similarity_context(context) == context
    assert parse_supported_similarity_context_request(context.request) == context.request
    with pytest.raises(ERRORS):
        parse_similarity_context(context)
    old = parse_similarity_context(context_body())
    assert parse_supported_similarity_context(old) == old
    with pytest.raises(ERRORS):
        parse_similarity_context_v2(old)


def test_accepted_candidate_retains_original_profile_and_evidence() -> None:
    body = mixed_context_body()
    candidate = context_body()["candidates"][0]
    body["candidates"] = [candidate | {"evidence_kind": "ACCEPTED_SOLUTION_ANALYSIS"}]
    context = parse_similarity_context_v2(seal(body, "context_sha256"))
    assert isinstance(context.candidates[0], AcceptedSimilarityCandidateV2)
    assert (
        context.candidates[0].solution_evidence.model_dump(mode="json")
        == candidate["solution_evidence"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "old_index",
        "old_profile",
        "wrong_source",
        "fake_solution",
        "wrong_kind",
        "bool_count",
        "accepted_count",
        "missing_limit",
        "duplicate_rank",
        "wrong_request_hash",
        "extra",
    ],
)
def test_forged_or_cross_family_contexts_fail_closed(fault: str) -> None:
    body = mixed_context_body()
    candidate = body["candidates"][0]
    if fault == "old_index":
        body["request"]["views"][0]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/1.0"
        )
        body["request"] = seal(body["request"], "request_sha256")
    elif fault == "old_profile":
        candidate["profile"] = context_body()["candidates"][0]["profile"]
    elif fault == "wrong_source":
        candidate["source"]["item_revision_id"] = "itemrev_" + "0" * 32
    elif fault == "fake_solution":
        candidate["solution_evidence"] = context_body()["candidates"][0]["solution_evidence"]
    elif fault == "wrong_kind":
        candidate["evidence_kind"] = "ACCEPTED_SOLUTION_ANALYSIS"
    elif fault == "bool_count":
        body["population"]["available_profile_count"] = True
    elif fault == "accepted_count":
        body["population"]["accepted_profile_count"] = 2
    elif fault == "missing_limit":
        body["population"]["missing_evidence_count"] = 1
        body["population"]["available_profile_count"] = 1
        for view in body["population"]["views"]:
            view["available_binding_count"] = 1
    elif fault == "duplicate_rank":
        candidate["observations"].append(copy.deepcopy(candidate["observations"][0]))
    elif fault == "wrong_request_hash":
        body["request"]["request_sha256"] = "sha256:" + "0" * 64
    else:
        body["unreviewed"] = True
    with pytest.raises(ERRORS):
        parse_similarity_context_v2(seal(body, "context_sha256"))


def test_same_numerical_input_result1_bind_opaque_context2_hash_without_retagging() -> None:
    body = mixed_context_body()
    request_body = query_input_body()
    request_body["context_request_sha256"] = body["request"]["request_sha256"]
    request = parse_embedding_reference_query_input(seal(request_body, "request_sha256"))
    result = parse_embedding_reference_query_result(
        query_result_body(request.model_dump(mode="json"))
    )
    body["query_execution"]["request_sha256"] = request.request_sha256
    body["query_execution"]["result_sha256"] = result.result_sha256
    body["query_execution"]["result_member"]["sha256"] = content_sha256(
        result.model_dump(mode="json")
    )
    context = parse_similarity_context_v2(seal(body, "context_sha256"))
    execution = context.query_execution
    assert execution is not None
    shard = context.candidates[0].observations[1].query_row.shard_manifest
    validate_similarity_query_execution_v2(context, request, result, execution.result_member, shard)
    assert request.schema_version == "embedding-reference-query-input/1.0"
    assert isinstance(result, EmbeddingReferenceQueryResult)
    assert result.schema_version == "embedding-reference-query-result/1.0"


def test_real_mixed_index2_manifest_validation_rejects_crossed_pointer_and_revision() -> None:
    _entry, _binding, _shard, _member, index = mixed_embedding_case("CONTENT_ONLY")
    body = mixed_context_body()["request"]
    selection = body["views"][0]
    selection["index"].update(
        index_id=index.index_id,
        index_revision_id=index.index_revision_id,
        index_manifest=pointer(index).model_dump(mode="json"),
        index_sha256=index.index_sha256,
    )
    request = parse_similarity_context_request_v2(seal(body, "request_sha256"))
    validate_similarity_index_pin_v2(request.views[0], pointer(index), index)
    with pytest.raises(ERRORS):
        validate_similarity_index_pin_v2(
            request.views[0],
            pointer(index).model_copy(
                update={"schema_ref": "eom://schemas/knowledge/embedding-index-manifest/1.0"}
            ),
            index,
        )


def test_read2_requires_exact_actor_selection_and_original_result_family() -> None:
    context = parse_similarity_context_v2(mixed_context_body())
    request = SimilarityContextReadRequestV2(
        schema_version="system-rag-similarity-read-request/2.0",
        operation="READ_SIMILARITY_CONTEXT",
        actor_id="operator_" + "a" * 32,
        selection={
            "workflow_id": "workflow_" + "b" * 32,
            "workflow_request_sha256": "sha256:" + "b" * 64,
            "context_request_sha256": context.request.request_sha256,
        },
    )
    body = {
        "schema_version": "system-rag-similarity-read-reply/2.0",
        "operation": "READ_SIMILARITY_CONTEXT",
        "status": "SUCCESS",
        "actor_id": request.actor_id,
        "request_sha256": content_sha256(request.model_dump(mode="json")),
        "result": context.model_dump(mode="json"),
        "error_code": None,
    }
    reply = SimilarityContextReadReplyV2.model_validate(body)
    validate_similarity_read_reply_v2(request, reply)
    with pytest.raises(ERRORS):
        SimilarityContextReadReply.model_validate(body)
    with pytest.raises(ERRORS):
        validate_similarity_read_reply_v2(
            request, reply.model_copy(update={"actor_id": "operator_" + "c" * 32})
        )


def test_materialization_keeps_original_review_envelope_projection_without_second_source() -> None:
    context = parse_similarity_context_v2(mixed_context_body())
    entry = mixed_embedding_case()[0]
    anchor = embedding_entry().profile
    # Use the exact original candidate profile basis; no serialization conversion to1.
    body = context.model_dump(mode="json")
    body["request"]["graph_snapshot"] = entry.profile.source_basis.graph_snapshot.model_dump(
        mode="json"
    )
    body["request"]["anchor"] = {
        "basis": "APPROVED_REFERENCE_ITEM",
        "source": anchor.source_basis.source.model_dump(mode="json"),
        "profile": InferenceTransferProfilePointer.from_profile(anchor).model_dump(mode="json"),
        "solution_evidence": anchor.source_basis.solution_evidence.model_dump(mode="json"),
    }
    body["request"] = seal(body["request"], "request_sha256")
    context = parse_similarity_context_v2(seal(body, "context_sha256"))
    materials = build_similarity_materials_v2(context, anchor_profile=anchor, entries=(entry,))
    assert materials.entries[0].profile is not None
    assert materials.entries[0].profile.schema_version == "item-inference-transfer-profile/2.0"
    assert validate_similarity_materials_v2(materials, context) == materials
    with pytest.raises(ERRORS):
        validate_similarity_materials_v2(
            materials.model_copy(update={"entries": (embedding_entry("b"),)}), context
        )
