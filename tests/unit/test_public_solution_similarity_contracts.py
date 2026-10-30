"""Synthetic values for the explicit public report/QUERY/index family, not live search."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
)
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_contracts.similarity_context_v2 import SimilarityContextRequestV2
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_index_assembly import assemble, setup
from tests.unit.test_public_solution_query_contracts import public_query_input, public_query_result


def member(value, *, schema, name, seed="b"):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=name,
        schema_ref=schema,
        media_type="application/json",
        sha256=content_sha256(value.model_dump(mode="json")),
    )


def public_similarity_case():
    data = setup()
    entries = data[0]
    anchor = next(
        entry for entry in entries if entry.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT"
    )
    candidate = next(entry for entry in entries if entry is not anchor)
    index = assemble(data).index
    index_member = member(
        index,
        schema="eom://schemas/knowledge/embedding-index-manifest/3.0",
        name="index.json",
        seed="a",
    )
    numerical = public_query_input(creative=True)
    body = dict(
        schema_version="system-rag-similarity-request/3.0",
        request_id="similarityrequest_" + "1" * 32,
        consumer_purpose="ITEM_DATABASE_SEARCH",
        anchor=PublicSolutionSourceReference.from_entry(anchor).model_dump(mode="json"),
        graph_snapshot=anchor.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=anchor.policy_revision_id,
        policy_sha256=anchor.policy_sha256,
        source_classes=["APPROVED_ITEM", "PAST_EXAM"],
        views=[
            dict(
                view="CONCRETE_FACETS",
                recipe=anchor.recipe.model_dump(mode="json"),
                index=dict(
                    index_id=index.index_id,
                    index_revision_id=index.index_revision_id,
                    index_manifest=index_member.model_dump(mode="json"),
                    index_sha256=index.index_sha256,
                    storage_partition=index.storage_partition,
                    spaces=numerical.spaces.model_dump(mode="json"),
                ),
            )
        ],
        maximum_sources=16384,
        top_k=5,
    )
    request = PublicSolutionSimilarityRequest.model_validate(seal(body, "request_sha256"))
    numerical = PublicSolutionQueryInput.model_validate(
        seal(
            numerical.model_dump(mode="json") | {"context_request_sha256": request.request_sha256},
            "request_sha256",
        )
    )
    result = public_query_result(numerical)
    result_member = member(result, schema=PUBLIC_SOLUTION_QUERY_RESULT_REF, name="result.json")
    shard_member = member(
        result.shard, schema="eom://schemas/knowledge/embedding-vector-shard/1.0", name="shard.json"
    )
    query_execution = PublicSolutionQueryExecutionPointer(
        job_id=numerical.job_id,
        query_request_id=numerical.query_request_id,
        request_sha256=numerical.request_sha256,
        input_set_sha256=numerical.input_set_sha256,
        result_member=result_member,
        result_sha256=result.result_sha256,
    )
    binding = next(row for row in index.bindings if row.source == candidate.source)
    body = dict(
        schema_version="system-rag-similarity-context/3.0",
        request=request.model_dump(mode="json"),
        status="READY",
        population=dict(
            authorized_source_count=2,
            authorized_source_set_sha256="sha256:" + "1" * 64,
            available_report_count=2,
            available_report_set_sha256="sha256:" + "2" * 64,
            available_binding_count=2,
            binding_set_sha256="sha256:" + "3" * 64,
            scored_count=1,
            truncated=False,
        ),
        query_execution=query_execution.model_dump(mode="json"),
        candidates=[
            PublicSolutionSourceReference.from_entry(candidate).model_dump(mode="json")
            | dict(
                observation=dict(
                    channel="VECTOR",
                    view="CONCRETE_FACETS",
                    rank=1,
                    cosine_millionths=999999,
                    score_semantics="ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY",
                    query_row=dict(
                        shard_manifest=shard_member.model_dump(mode="json"),
                        row_index=0,
                        encoding_sha256=numerical.rows[0].encoding.encoding_sha256,
                    ),
                    document_row=binding.row_ref.model_dump(mode="json"),
                ),
            )
        ],
        limitations=["SCORE_IS_NOT_PROOF_OF_IDENTICAL_REASONING"],
        error_code=None,
    )
    context = PublicSolutionSimilarityContext.model_validate(seal(body, "context_sha256"))
    return request, context, numerical, result, data


def test_public_context_is_explicit_and_old_requests_remain_closed():
    request, context, numerical, _, _ = public_similarity_case()
    assert request.anchor.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT"
    assert context.candidates[0].evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS"
    assert numerical.context_request_sha256 == request.request_sha256
    assert context.query_execution.result_member.schema_ref == PUBLIC_SOLUTION_QUERY_RESULT_REF
    assert PublicSolutionSimilarityContext.model_validate(context) == context
    validate_contract("public-solution-similarity-v3", request.model_dump(mode="json"))
    validate_contract("public-solution-similarity-v3", context.model_dump(mode="json"))
    for parser in (parse_similarity_context_request, SimilarityContextRequestV2.model_validate):
        with pytest.raises((ValueError, SchemaError)):
            parser(request.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "legacy_index",
        "source",
        "recipe",
        "classes",
        "views",
        "limit",
        "unknown",
        "graph",
        "anchor_profile",
    ],
)
def test_public_request_never_silently_changes_family_scope_or_identity(fault):
    request, _, _, _, _ = public_similarity_case()
    body = request.model_dump(mode="json")
    if fault == "legacy_index":
        body["views"][0]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    elif fault == "source":
        body["source_classes"] = ["PAST_EXAM"]
    elif fault == "recipe":
        body["views"][0]["recipe"]["recipe_sha256"] = "sha256:" + "f" * 64
    elif fault == "classes":
        body["source_classes"] *= 2
    elif fault == "views":
        body["views"] *= 2
    elif fault == "limit":
        body["maximum_sources"] = 16385
    elif fault == "unknown":
        body["latest"] = True
    elif fault == "graph":
        body["graph_snapshot"]["manifest_sha256"] = "sha256:" + "f" * 64
    elif fault == "anchor_profile":
        body["anchor"]["profile"]["profile_id"] = "inferenceprofile_" + "f" * 32
    else:
        body["request_sha256"] = "sha256:" + "f" * 64
    if fault != "hash":
        body = seal(body, "request_sha256")
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityRequest.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "missing_query",
        "wrong_query",
        "row",
        "view",
        "rank",
        "anchor",
        "duplicate",
        "count",
        "failure",
        "false_complete",
        "warning_missing",
        "unknown",
    ],
)
def test_context_cannot_claim_foreign_execution_or_false_coverage(fault):
    _, context, _, _, _ = public_similarity_case()
    body = context.model_dump(mode="json")
    if fault == "missing_query":
        body["query_execution"] = None
    elif fault == "wrong_query":
        body["query_execution"]["result_member"]["artifact_id"] = "artifact_" + "f" * 32
    elif fault in {"row", "view", "rank"}:
        observation = body["candidates"][0]["observation"]
        if fault == "row":
            observation["query_row"]["row_index"] = 1
        else:
            observation[fault] = "CONTENT_ONLY" if fault == "view" else 2
    elif fault == "anchor":
        body["candidates"][0] = deepcopy(body["request"]["anchor"]) | {
            "observation": body["candidates"][0]["observation"]
        }
    elif fault == "duplicate":
        body["candidates"] *= 2
    elif fault == "count":
        body["population"]["available_binding_count"] = 3
    elif fault == "failure":
        body["status"] = "FAILED"
        body["error_code"] = "QUERY_RESULT_INVALID"
    elif fault == "false_complete":
        body["population"]["authorized_source_count"] = 3
    elif fault == "warning_missing":
        body["limitations"] = []
    elif fault == "unknown":
        body["approval"] = "APPROVED"
    else:
        body["context_sha256"] = "sha256:" + "f" * 64
    if fault != "hash":
        body = seal(body, "context_sha256")
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionSimilarityContext.model_validate(body)


def test_partial_and_empty_are_not_false_full_coverage_or_zero_vector_success():
    _, context, _, _, _ = public_similarity_case()
    body = context.model_dump(mode="json")
    body["status"] = "PARTIAL"
    body["population"]["authorized_source_count"] = 3
    body["limitations"].append("PARTIAL_REPORT_COVERAGE")
    partial = PublicSolutionSimilarityContext.model_validate(seal(body, "context_sha256"))
    assert partial.status == "PARTIAL"
    body["status"] = "EMPTY"
    body["population"]["scored_count"] = 0
    body["candidates"] = []
    assert (
        PublicSolutionSimilarityContext.model_validate(seal(body, "context_sha256")).status
        == "EMPTY"
    )
