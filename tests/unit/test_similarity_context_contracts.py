"""Closed synthetic auxiliary context values; no query runtime or consumer is activated."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import (
    ReadySimilarityContext,
    SimilarityViewSelection,
    parse_similarity_context,
    parse_similarity_context_request,
    validate_similarity_index_pin,
    validate_similarity_query_execution,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    index_manifest,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record
from tests.unit.test_embedding_reference_query_contracts import query_input_body, query_result_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def context_request_body(*, prepared: bool = True, missing_report: bool = False) -> dict[str, Any]:
    entry = embedding_entry()
    query = query_input_body()
    views: list[dict[str, Any]] = []
    cases: tuple[tuple[ExperimentView, str], ...] = (
        ("CONTENT_ONLY", "1"),
        ("CONCRETE_FACETS", "2"),
    )
    for view, seed in cases:
        index = index_manifest(source_binding(view=view), view=view, revision_seed=seed)
        views.append(
            {
                "view": view,
                "recipe": view_recipe().model_dump(mode="json"),
                "index": {
                    "index_id": index.index_id,
                    "index_revision_id": index.index_revision_id,
                    "index_manifest": index_pointer(index, seed).model_dump(mode="json"),
                    "index_sha256": index.index_sha256,
                    "storage_partition": PARTITION,
                    "spaces": query["spaces"],
                }
                if prepared
                else None,
            }
        )
    return seal(
        {
            "schema_version": "system-rag-similarity-request/1.0",
            "request_id": "similarityrequest_" + "a" * 32,
            "consumer_purpose": "PAST_EXAM_VARIATION",
            "anchor": {
                "basis": "APPROVED_REFERENCE_ITEM",
                "source": entry.profile.source_basis.source.model_dump(mode="json"),
                "profile": None
                if missing_report
                else InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                    mode="json"
                ),
                "solution_evidence": None
                if missing_report
                else entry.profile.source_basis.solution_evidence.model_dump(mode="json"),
            },
            "graph_snapshot": entry.profile.source_basis.graph_snapshot.model_dump(mode="json"),
            "policy_revision_id": "accessrev_" + "d" * 32,
            "policy_sha256": sha("d"),
            "source_classes": ["APPROVED_ITEM", "PAST_EXAM"],
            "topics": [],
            "unit_ids": [],
            "views": views,
            "vector_mode": "OPTIONAL",
            "maximum_sources": 1024,
            "top_k": 8,
        },
        "request_sha256",
    )


def context_body(
    *, ready: bool = True, required: bool = False, missing_report: bool = False
) -> dict[str, Any]:
    request = context_request_body(prepared=ready, missing_report=missing_report)
    if required:
        request["vector_mode"] = "REQUIRED"
        request = seal(request, "request_sha256")
    query = query_input_body()
    query["context_request_sha256"] = request["request_sha256"]
    query = seal(query, "request_sha256")
    result = parse_embedding_reference_query_result(query_result_body(query))
    result_member = ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="result.json",
        schema_ref=REFERENCE_QUERY_RESULT_REF,
        media_type="application/json",
        sha256=content_sha256(result.model_dump(mode="json")),
    )
    query_shard = shard_pointer(result.shard, "e")
    entry = embedding_entry("b")
    observations: list[dict[str, Any]] = [
        {"channel": "GRAPH_LEXICAL", "rank": 1, "graph_relevance_milli": 2000}
    ]
    if ready:
        for row in result.view_rows:
            document_row = source_binding(entry, view=row.view).row_ref.model_dump(mode="json")
            observations.append(
                {
                    "channel": "VECTOR",
                    "view": row.view,
                    "rank": 1,
                    "cosine_millionths": 670001,
                    "score_semantics": "ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY",
                    "query_row": {
                        "shard_manifest": query_shard.model_dump(mode="json"),
                        "row_index": row.row_index,
                        "encoding_sha256": row.encoding_sha256,
                    },
                    "document_row": document_row,
                }
            )
    views = [
        {
            "view": selection["view"],
            "status": "READY" if ready else "UNAVAILABLE",
            "available_binding_count": 2 if ready else None,
            "binding_set_sha256": sha("d") if ready else None,
            "scored_count": 1 if ready else 0,
            "missing_view_count": 0 if ready else None,
            "reason": None
            if ready
            else ("ANCHOR_REPORT_MISSING" if missing_report else "INDEX_NOT_PREPARED"),
        }
        for selection in request["views"]
    ]
    candidates = (
        [
            {
                "source": entry.profile.source_basis.source.model_dump(mode="json"),
                "profile": InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                    mode="json"
                ),
                "solution_evidence": entry.profile.source_basis.solution_evidence.model_dump(
                    mode="json"
                ),
                "observations": observations,
                "explanation": None,
            }
        ]
        if not required or ready
        else []
    )
    limitations = ["REFERENCE_ANCHOR_NOT_PRIVATE_INTENT"]
    if not ready:
        limitations.append("VECTOR_NOT_AVAILABLE")
    if missing_report:
        limitations.append("PARTIAL_REPORT_COVERAGE")
    if not candidates:
        limitations.append("NO_RELATED_CANDIDATES")
    return seal(
        {
            "schema_version": "system-rag-similarity-context/1.0",
            "request": request,
            "status": "READY" if ready else ("UNAVAILABLE" if required else "PARTIAL"),
            "population": {
                "authorized_source_count": 2,
                "authorized_source_set_sha256": sha("c"),
                "accepted_profile_count": 1 if missing_report else 2,
                "accepted_profile_set_sha256": sha("e"),
                "missing_report_count": 1 if missing_report else 0,
                "truncated": False,
                "views": views,
            },
            "query_execution": {
                "job_id": query["job_id"],
                "query_request_id": query["query_request_id"],
                "request_sha256": query["request_sha256"],
                "input_set_sha256": query["input_set_sha256"],
                "result_member": result_member.model_dump(mode="json"),
                "result_sha256": result.result_sha256,
            }
            if ready
            else None,
            "graph_evidence": None,
            "candidates": candidates,
            "limitations": limitations,
            "error_code": None,
        },
        "context_sha256",
    )


def test_schema_registered_additively_draft_mirror_and_raw_hash_are_exact() -> None:
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-context"]
    payload = (ROOT / resource.canonical_path).read_bytes()
    assert (
        payload
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(payload)
        == resource.sha256
        == "sha256:7d1d4bb07964060143acacb32a3dad8ccbc41519d5847742ffe5deb739b57b20"
    )
    Draft202012Validator.check_schema(load_schema("system-rag-similarity-context"))


def test_reference_context_round_trip_separate_channels_and_exact_query_closure() -> None:
    context = parse_similarity_context(context_body())
    assert isinstance(context, ReadySimilarityContext)
    assert parse_similarity_context(context) == context
    assert context.request.anchor.basis == "APPROVED_REFERENCE_ITEM"
    assert [row.channel for row in context.candidates[0].observations] == [
        "GRAPH_LEXICAL",
        "VECTOR",
        "VECTOR",
    ]
    query = query_input_body()
    query["context_request_sha256"] = context.request.request_sha256
    query = seal(query, "request_sha256")
    request = parse_embedding_reference_query_input(query)
    result = parse_embedding_reference_query_result(query_result_body(query))
    assert context.query_execution is not None
    validate_similarity_query_execution(
        context,
        request,
        result,
        context.query_execution.result_member,
        shard_pointer(result.shard, "e"),
    )
    assert canonical_json_bytes(context.model_dump(mode="json"))
    assert context.query_execution.result_sha256 != context.query_execution.result_member.sha256


def test_optional_graph_only_and_required_unavailable_are_not_the_same_success() -> None:
    optional = parse_similarity_context(context_body(ready=False))
    required = parse_similarity_context(context_body(ready=False, required=True))
    assert optional.status == "PARTIAL" and len(optional.candidates) == 1
    assert required.status == "UNAVAILABLE" and not required.candidates
    assert optional.query_execution is required.query_execution is None
    assert optional.population is not None
    assert all(row.available_binding_count is None for row in optional.population.views)
    missing = parse_similarity_context(context_body(ready=False, missing_report=True))
    assert missing.request.anchor.profile is None
    assert missing.request.anchor.solution_evidence is None
    assert missing.population is not None and missing.population.missing_report_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "guiadmin"),
        ("role", "ADMIN"),
        ("permissions", ["READ"]),
        ("query_text", "개인 질문"),
        ("path", "/mnt/nas"),
        ("maximum_sources", True),
    ],
)
def test_request_rejects_authority_private_text_path_and_boolean(field: str, value: object) -> None:
    document = context_request_body()
    document[field] = value
    with pytest.raises(ERRORS):
        parse_similarity_context_request(seal(document, "request_sha256"))


@pytest.mark.parametrize(
    "change",
    [
        "basis",
        "source",
        "report",
        "graph",
        "hash",
        "duplicate_view",
        "mixed_device",
        "recipe",
        "extra",
    ],
)
def test_request_rejects_wrong_or_missing_pins_without_repair(change: str) -> None:
    document = context_request_body()
    if change == "basis":
        document["anchor"]["basis"] = "PRIVATE_AUTHORING_INTENT"
    elif change == "source":
        document["anchor"]["source"]["lifecycle_state"] = "PENDING"
    elif change == "report":
        document["anchor"]["solution_evidence"] = None
    elif change == "graph":
        document["graph_snapshot"]["manifest_sha256"] = sha("f")
    elif change == "hash":
        document["request_sha256"] = sha("f")
    elif change == "duplicate_view":
        document["views"][1] = document["views"][0]
    elif change == "mixed_device":
        document["views"][0]["index"]["spaces"]["query"]["runtime"]["device"] = "CUDA"
    elif change == "recipe":
        document["views"][0]["recipe"]["recipe_sha256"] = sha("f")
    else:
        document["anchor"]["profile"]["approved"] = True
    with pytest.raises(ERRORS):
        parse_similarity_context_request(
            document if change == "hash" else seal(document, "request_sha256")
        )


@pytest.mark.parametrize(
    "change",
    [
        "coverage",
        "duplicate",
        "anchor",
        "probability",
        "float",
        "query",
        "row",
        "rank",
        "missing_report",
        "truncated",
        "failed",
        "copied_bool",
    ],
)
def test_context_rejects_contradictory_disclosure_and_copied_fields(change: str) -> None:
    document = context_body()
    if change == "coverage":
        document["population"]["authorized_source_count"] = 1
    elif change == "duplicate":
        document["candidates"].append(copy.deepcopy(document["candidates"][0]))
    elif change == "anchor":
        document["candidates"][0]["source"] = document["request"]["anchor"]["source"]
    elif change == "probability":
        document["candidates"][0]["observations"][1]["score_semantics"] = "PROBABILITY"
    elif change == "float":
        document["candidates"][0]["observations"][1]["cosine_millionths"] = 0.67
    elif change == "query":
        document["query_execution"] = None
    elif change == "row":
        document["candidates"][0]["observations"][1]["query_row"]["row_index"] = True
    elif change == "rank":
        document["candidates"][0]["observations"][1]["rank"] = 2
    elif change == "missing_report":
        document["population"]["accepted_profile_count"] = 1
        document["population"]["missing_report_count"] = 1
    elif change == "truncated":
        document["population"]["truncated"] = True
    elif change == "failed":
        document["status"] = "FAILED"
        document["error_code"] = "SOURCE_ACCESS_DENIED"
    else:
        context = parse_similarity_context(document)
        assert context.population is not None
        with pytest.raises(ERRORS):
            parse_similarity_context(
                context.model_copy(
                    update={
                        "population": context.population.model_copy(
                            update={"authorized_source_count": True}
                        )
                    }
                )
            )
        return
    with pytest.raises(ERRORS):
        parse_similarity_context(
            document if change == "float" else seal(document, "context_sha256")
        )


@pytest.mark.parametrize("change", ["stale_revision", "missing", "hash", "recipe", "view"])
def test_resolved_index_pin_rejects_missing_stale_hash_recipe_view(change: str) -> None:
    request = parse_similarity_context_request(context_request_body())
    selection = request.views[0]
    manifest = index_manifest(
        source_binding(view="CONTENT_ONLY"), view="CONTENT_ONLY", revision_seed="1"
    )
    assert selection.index is not None
    pointer = selection.index.index_manifest
    validate_similarity_index_pin(selection, pointer, manifest)
    if change == "stale_revision":
        manifest = index_manifest(
            source_binding(view="CONTENT_ONLY"), view="CONTENT_ONLY", revision_seed="3"
        )
    elif change == "missing":
        selection = SimilarityViewSelection(
            view=selection.view, recipe=selection.recipe, index=None
        )
    elif change == "hash":
        pointer = pointer.model_copy(update={"sha256": sha("f")})
    elif change == "recipe":
        selection = selection.model_copy(
            update={"recipe": selection.recipe.model_copy(update={"ranking": "ROUNDED_TIES"})}
        )
    else:
        selection = selection.model_copy(update={"view": "METADATA_ONLY"})
    with pytest.raises(ERRORS):
        validate_similarity_index_pin(selection, pointer, manifest)


def test_failed_context_has_no_population_candidates_or_partial_query_disclosure() -> None:
    document = context_body()
    document.update(
        status="FAILED",
        population=None,
        query_execution=None,
        graph_evidence=None,
        candidates=[],
        error_code="SOURCE_HASH_MISMATCH",
    )
    assert parse_similarity_context(seal(document, "context_sha256")).status == "FAILED"


def test_nested_model_copy_extra_and_construct_missing_are_not_silently_dropped() -> None:
    request = parse_similarity_context_request(context_request_body())
    for copied in (
        request.model_copy(update={"actor_id": "ADMIN"}),
        request.model_copy(
            update={
                "views": (
                    request.views[0].model_copy(update={"approved": True}),
                    *request.views[1:],
                )
            }
        ),
        type(request).model_construct(request_id=request.request_id),
    ):
        with pytest.raises(ERRORS):
            parse_similarity_context_request(copied)


def test_contract_modules_do_not_import_runtime_storage_network_or_benchmark_admission() -> None:
    forbidden = {
        "sqlalchemy",
        "torch",
        "transformers",
        "subprocess",
        "socket",
        "requests",
        "eom_catalog_service",
        "eom_orchestrator",
        "eom_gpu_lease",
    }
    for filename in ("embedding_reference_query.py", "similarity_context.py"):
        source = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / filename
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module is not None and node.module.split(".")[0] not in forbidden
                assert "embedding_device_benchmark" not in node.module


def test_third_view_explicitly_unavailable_is_partial_not_claimed_ready() -> None:
    document = context_body()
    document["request"]["views"].append(
        {
            "view": "METADATA_ONLY",
            "recipe": view_recipe().model_dump(mode="json"),
            "index": None,
        }
    )
    document["request"] = seal(document["request"], "request_sha256")
    document["population"]["views"].append(
        {
            "view": "METADATA_ONLY",
            "status": "UNAVAILABLE",
            "available_binding_count": None,
            "binding_set_sha256": None,
            "scored_count": 0,
            "missing_view_count": None,
            "reason": "QUERY_NOT_OFFERED",
        }
    )
    document["status"] = "PARTIAL"
    document["limitations"].append("VECTOR_NOT_AVAILABLE")
    context = parse_similarity_context(seal(document, "context_sha256"))
    assert context.status == "PARTIAL"
    assert context.population is not None and len(context.population.views) == 3


def test_full_official_past_exam_page_lineage_is_retained_not_downcast() -> None:
    record = snapshot_v3_record()
    assert record.staged_entry is not None
    document = context_request_body()
    document["anchor"].update(
        source=record.source.model_dump(mode="json"),
        profile=record.index_entry.profile.model_dump(mode="json")
        if record.index_entry.profile is not None
        else None,
        solution_evidence=record.staged_entry.profile.source_basis.solution_evidence.model_dump(
            mode="json"
        ),
    )
    request = parse_similarity_context_request(seal(document, "request_sha256"))
    assert request.anchor.source == record.source
    assert request.anchor.source.model_dump(mode="json")["page_image_count"] == 1


def test_missing_anchor_report_cannot_be_claimed_as_available_query_coverage() -> None:
    document = context_body()
    document["request"]["anchor"]["profile"] = None
    document["request"]["anchor"]["solution_evidence"] = None
    document["request"] = seal(document["request"], "request_sha256")
    with pytest.raises(ERRORS):
        parse_similarity_context(seal(document, "context_sha256"))


def test_cyclic_oversized_raw_shapes_fail_with_explicit_bounded_validation_error() -> None:
    document = context_request_body()
    cycle: list[object] = []
    cycle.append(cycle)
    document["views"] = cycle
    with pytest.raises(ValueError, match="nesting/node bound"):
        parse_similarity_context_request(document)
    document["views"] = [None] * 1025
    with pytest.raises(ValueError, match="array bound"):
        parse_similarity_context_request(document)


def test_empty_context_does_not_fabricate_related_candidates_or_query_execution() -> None:
    document = context_body()
    document.update(status="EMPTY", candidates=[], query_execution=None)
    document["population"].update(authorized_source_count=1, accepted_profile_count=1)
    for row in document["population"]["views"]:
        row.update(scored_count=0, available_binding_count=1)
    document["limitations"].append("NO_RELATED_CANDIDATES")
    context = parse_similarity_context(seal(document, "context_sha256"))
    assert context.status == "EMPTY" and not context.candidates
    assert context.query_execution is None


@pytest.mark.parametrize("change", ["execution", "query_row", "missing_view", "stale_member"])
def test_query_execution_pointer_resolution_rejects_foreign_missing_or_stale_values(
    change: str,
) -> None:
    document = context_body()
    if change == "execution":
        document["query_execution"]["result_sha256"] = sha("f")
    elif change == "query_row":
        original = document["candidates"][0]["observations"][1]["query_row"]
        original["row_index"] = 1 - original["row_index"]
    context = parse_similarity_context(seal(document, "context_sha256"))
    query = query_input_body()
    query["context_request_sha256"] = context.request.request_sha256
    query = seal(query, "request_sha256")
    request = parse_embedding_reference_query_input(query)
    result = parse_embedding_reference_query_result(query_result_body(query))
    assert context.query_execution is not None
    member = context.query_execution.result_member
    shard = shard_pointer(result.shard, "e")
    if change == "missing_view":
        result_body = result.model_dump(mode="json")
        result_body["view_rows"][0]["view"] = "METADATA_ONLY"
        result = parse_embedding_reference_query_result(seal(result_body, "result_sha256"))
    elif change == "stale_member":
        member = member.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ERRORS):
        validate_similarity_query_execution(context, request, result, member, shard)
