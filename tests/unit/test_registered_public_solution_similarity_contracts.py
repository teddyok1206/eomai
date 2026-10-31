"""Metadata closure only: synthetic references, no IAM, model or live search claim."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityContextV4,
    PublicSolutionSimilarityRequestV4,
    RegisteredPublicSolutionSourceReference,
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
    public_solution_reference_for_entry,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_index import registered_index_entry


@lru_cache(maxsize=1)
def registered_similarity_case():
    original, prior_context, numerical, result, data = public_similarity_case()
    entry = registered_index_entry()
    value = original.model_dump(mode="json")
    value["schema_version"] = "system-rag-similarity-request/4.0"
    value["views"][0]["index"]["index_manifest"]["schema_ref"] = (
        "eom://schemas/knowledge/embedding-index-manifest/4.0"
    )
    request = PublicSolutionSimilarityRequestV4.model_validate(seal(value, "request_sha256"))
    candidate = public_solution_reference_for_entry(entry).model_dump(mode="json")
    candidate["observation"] = deepcopy(
        prior_context.candidates[0].model_dump(mode="json")["observation"]
    )
    candidate["observation"]["rank"] = 2
    body = prior_context.model_dump(mode="json")
    body.update(
        schema_version="system-rag-similarity-context/4.0", request=request.model_dump(mode="json")
    )
    body["candidates"].append(candidate)
    body["population"].update(
        authorized_source_count=3,
        available_report_count=3,
        available_binding_count=3,
        scored_count=2,
    )
    context = PublicSolutionSimilarityContextV4.model_validate(seal(body, "context_sha256"))
    return request, context, entry, numerical, result, data


def test_closed_metadata4_preserves_old_candidates_and_unchanged_query2():
    request, context, entry, numerical, result, data = registered_similarity_case()
    assert context.candidates[0].evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS"
    assert context.candidates[1].evidence.kind == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    assert (
        context.candidates[1].profile
        == RegisteredPublicSolutionSourceReference.from_entry(entry).profile
    )
    assert numerical.schema_version == "embedding-reference-query-input/2.0"
    assert result.schema_version == "embedding-reference-query-result/2.0"
    assert numerical.rows[0].text == entry.public_solution.text == data[0][0].public_solution.text
    for value in (request, context):
        validate_contract("public-solution-similarity-v4", value.model_dump(mode="json"))
        assert type(value).model_validate_json(value.model_dump_json()) == value
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityRequest.model_validate(request.model_dump(mode="json"))
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityContext.model_validate(context.model_dump(mode="json"))


def test_registered_anchor_and_historical_index3_pin_do_not_require_new_numeric_format():
    request, _, entry, *_ = registered_similarity_case()
    body = request.model_dump(mode="json")
    body["anchor"] = public_solution_reference_for_entry(entry).model_dump(mode="json")
    body["views"][0]["index"]["index_manifest"]["schema_ref"] = (
        "eom://schemas/knowledge/embedding-index-manifest/3.0"
    )
    registered = PublicSolutionSimilarityRequestV4.model_validate(seal(body, "request_sha256"))
    assert registered.anchor.evidence.kind == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    assert registered.anchor.base_analysis_run_id == entry.evidence.solution.base_analysis_run_id


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_base",
        "foreign_profile",
        "old_profile",
        "source_class",
        "unknown_proof",
        "extra",
        "index2",
        "float",
    ],
)
def test_registered_source_and_index_proofs_do_not_accept_rehashed_forgery(fault):
    request, _, entry, *_ = registered_similarity_case()
    body = request.model_dump(mode="json")
    body["anchor"] = public_solution_reference_for_entry(entry).model_dump(mode="json")
    if fault == "foreign_base":
        body["anchor"]["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif fault == "foreign_profile":
        body["anchor"]["profile"]["profile_revision_id"] = "inferenceprofilerev_" + "0" * 32
    elif fault == "old_profile":
        body["anchor"]["profile"]["schema_ref"] = (
            "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
        )
    elif fault == "source_class":
        body["anchor"]["source"]["source_class"] = "PAST_EXAM"
    elif fault == "unknown_proof":
        body["anchor"]["evidence"]["kind"] = "MODEL_SAYS_APPROVED"
    elif fault == "extra":
        body["anchor"]["authority_override"] = True
    elif fault == "index2":
        body["views"][0]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    else:
        body["top_k"] = 5.0
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityRequestV4.model_validate(
            body if fault == "float" else seal(body, "request_sha256")
        )


@pytest.mark.parametrize(
    "fault", ["false_complete", "duplicate", "rank", "query_producer", "base", "scope", "float"]
)
def test_common_context_closure_is_not_weakened_for_registered_candidates(fault):
    _, context, *_ = registered_similarity_case()
    body = context.model_dump(mode="json")
    if fault == "false_complete":
        body["population"]["available_binding_count"] = 2
    elif fault == "duplicate":
        body["candidates"][1] = deepcopy(body["candidates"][0])
    elif fault == "rank":
        body["candidates"][1]["observation"]["rank"] = 1
    elif fault == "query_producer":
        body["candidates"][1]["observation"]["query_row"]["shard_manifest"][
            "artifact_revision_id"
        ] = "rev_" + "f" * 32
    elif fault == "base":
        body["candidates"][1]["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif fault == "scope":
        body["request"]["maximum_sources"] = 2
        body["request"] = seal(body["request"], "request_sha256")
    else:
        body["candidates"][1]["observation"]["cosine_millionths"] = 0.5
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityContextV4.model_validate(
            body if fault == "float" else seal(body, "context_sha256")
        )


def test_schema4_is_packaged_and_old_metadata_and_numerical_schema_bytes_are_frozen():
    Draft202012Validator.check_schema(load_schema("public-solution-similarity-v4"))
    root = Path(__file__).resolve().parents[2]
    canonical = root / "schemas/knowledge/public-solution-similarity-v4.schema.json"
    packaged = (
        root
        / "packages/catalog_contracts/eom_catalog_contracts/resources"
        / "knowledge/public-solution-similarity-v4.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    for name, expected in (
        (
            "public-solution-similarity-v3",
            "3a19bca7baeaebba895ddac13cd35bd5b9c8d374065dc03cc6a232cfba05d673",
        ),
        (
            "public-solution-query-v2",
            "9632da6fa2d7458761c3262430c2843a41f2d70042c26bef57ba8f7a13964769",
        ),
    ):
        assert (
            sha256_bytes((root / "schemas/knowledge" / (name + ".schema.json")).read_bytes())
            == "sha256:" + expected
        )


def test_closed_family_dispatch_preserves_each_original_envelope_and_rejects_unknown():
    old_request, old_context, *_ = public_similarity_case()
    new_request, new_context, *_ = registered_similarity_case()
    for request in (old_request, new_request):
        assert parse_supported_public_solution_similarity_request(request) == request
    for context in (old_context, new_context):
        assert parse_supported_public_solution_similarity_context(context) == context
    for parse, document in (
        (parse_supported_public_solution_similarity_request, new_request.model_dump(mode="json")),
        (parse_supported_public_solution_similarity_context, new_context.model_dump(mode="json")),
    ):
        document["schema_version"] = document["schema_version"].replace("/4.0", "/5.0")
        with pytest.raises(ValueError, match="FAMILY_UNSUPPORTED"):
            parse(document)


@pytest.mark.parametrize("fault", ["source_class", "base", "undeclared"])
def test_registered_leaf_reference_cannot_bypass_its_proof_identity(fault):
    entry = registered_index_entry()
    body = RegisteredPublicSolutionSourceReference.from_entry(entry).model_dump(mode="json")
    if fault == "source_class":
        body["source"]["source_class"] = "PAST_EXAM"
    elif fault == "base":
        body["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    else:
        body["permission_override"] = True
    with pytest.raises(ValueError):
        RegisteredPublicSolutionSourceReference.model_validate(body)
