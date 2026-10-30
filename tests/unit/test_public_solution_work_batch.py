"""QUERY2 finite native IO with synthetic vectors; no installed owner or GPU inference."""

import json
from contextlib import contextmanager
from copy import deepcopy

import pytest
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    PublicSolutionWorkBatchInput,
    parse_embedding_work_batch_input,
    parse_supported_embedding_work_batch_input,
)
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    PublicSolutionWorkBatchResult,
    build_embedding_work_batch_result,
    parse_embedding_work_batch_result,
    parse_supported_embedding_work_batch_result,
    validate_embedding_work_batch_result,
)
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_service import embedding_native_stdio as handoff
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_native_stdio import descriptors as descriptors
from tests.unit.test_embedding_work_batch import Fence, batch_body
from tests.unit.test_public_solution_query_contracts import public_query_input

ERRORS = (ValueError, SchemaError)


def public_batch_body(count=2, *, device="CPU"):
    body = batch_body(count=1, device=device)
    body["schema_version"] = "embedding-work-batch-input/2.0"
    body["scope"] = seal(body["scope"] | {"storage_partition": "public-solution"}, "scope_sha256")
    children = []
    for index in range(count):
        query = public_query_input(device=device, creative=bool(index % 2)).model_dump(mode="json")
        query.update(
            job_id=f"job_{index + 1:032x}",
            query_request_id=f"embeddingquery_{index + 1:032x}",
            context_request_sha256=content_sha256({"public_context": index}),
        )
        children.append(
            {
                "scope_sha256": body["scope"]["scope_sha256"],
                "request": seal(query, "request_sha256"),
            }
        )
    return seal(body | {"children": children}, "request_sha256")


def public_case(device="CPU", count=2):
    batch = PublicSolutionWorkBatchInput.model_validate(public_batch_body(count, device=device))
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size, backend.threads = (
        batch.children[0].request.batch_size,
        batch.children[0].request.threads,
    )
    life = []

    @contextmanager
    def scope():
        life.append("load")
        try:
            yield backend
        finally:
            life.append("close")

    resources = EmbeddingWorkBatchExecutionResources(
        batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
    )
    return batch, backend, scope, resources, life


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("count", [1, 3, 32])
def test_public_query_batch_reuses_model_without_relabelling_query_or_profile(device, count):
    batch, backend, scope, resources, life = public_case(device, count)
    fence = Fence()
    encoded = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=fence
    )
    binary = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        batch, tuple(child.result for child in encoded.children), sha256_bytes(binary)
    )
    assert isinstance(result, PublicSolutionWorkBatchResult)
    validate_embedding_work_batch_result(batch, result)
    ranges = validate_embedding_work_batch_binary(batch, result, binary)
    assert life == ["load", "close"] and len(backend.calls) == count
    assert len(ranges) == count and all(view.readonly and view.obj is binary for view in ranges)
    assert all(purpose == "QUERY" and len(texts) == 1 for texts, purpose in backend.calls)
    assert parse_supported_embedding_work_batch_input(batch) == batch
    assert parse_supported_embedding_work_batch_result(result) == result
    for child, output in zip(batch.children, result.children, strict=True):
        validate_public_solution_query_result(child.request, output.result)
        assert output.result.schema_version == "embedding-reference-query-result/2.0"
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(batch)
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_result(result)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_job",
        "duplicate_query",
        "mixed_recipe",
        "scope",
        "partition",
        "actor",
        "document_purpose",
        "legacy_child",
        "threads",
        "timeout",
        "vector_limit",
        "count",
        "hash",
    ],
)
def test_public_batch_rejects_wrong_family_scope_identity_or_resources(fault):
    body = public_batch_body()
    first, second = body["children"]
    if fault == "duplicate_job":
        second["request"]["job_id"] = first["request"]["job_id"]
    elif fault == "duplicate_query":
        second["request"]["query_request_id"] = first["request"]["query_request_id"]
    elif fault == "mixed_recipe":
        second["request"]["recipe"]["schema_version"] = "inference-transfer-embedding-recipe/1.0"
    elif fault == "scope":
        second["scope_sha256"] = content_sha256({"other_scope": True})
    elif fault == "partition":
        body["scope"] = seal(
            body["scope"] | {"storage_partition": "another-partition"}, "scope_sha256"
        )
        for child in body["children"]:
            child["scope_sha256"] = body["scope"]["scope_sha256"]
    elif fault == "actor":
        body["scope"] = seal(
            body["scope"] | {"actor_kind": "LOCAL_INDEXING_SERVICE"}, "scope_sha256"
        )
        for child in body["children"]:
            child["scope_sha256"] = body["scope"]["scope_sha256"]
    elif fault == "document_purpose":
        body["purpose"] = "DOCUMENT"
    elif fault == "legacy_child":
        second["request"] = batch_body()["children"][1]["request"]
    elif fault == "threads":
        second["request"]["threads"] += 1
    elif fault == "timeout":
        body["timeout_seconds"] = 181
    elif fault == "vector_limit":
        body["vector_max_bytes"] = 4
    elif fault == "count":
        body["children"] = body["children"] * 17
    for child in body["children"]:
        child["request"] = seal(child["request"], "request_sha256")
    body = seal(body, "request_sha256")
    if fault == "hash":
        body["request_sha256"] = content_sha256({"wrong": True})
    with pytest.raises(ERRORS):
        PublicSolutionWorkBatchInput.model_validate(body)


def test_revocation_after_a_child_closes_model_without_aggregate_success():
    batch, backend, scope, resources, life = public_case()
    fence = Fence()
    fence.reject_at = 4  # two preflight checks, first pre-encode, then its post-encode
    with pytest.raises(ValueError, match="SOURCE_REVOKED"):
        execute_embedding_work_batch(batch, resources=resources, backend_scope=scope, fence=fence)
    assert len(backend.calls) == 1 and life == ["load", "close"]


@pytest.mark.parametrize("fault", ["offset", "context", "binary", "hash"])
def test_public_batch_result_cannot_substitute_child_context_or_binary(fault):
    batch, _, scope, resources, _ = public_case()
    encoded = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=Fence()
    )
    binary = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        batch, tuple(child.result for child in encoded.children), sha256_bytes(binary)
    )
    body = deepcopy(result.model_dump(mode="json"))
    if fault == "offset":
        body["children"][1]["vector_offset"] = 0
    elif fault == "context":
        child = body["children"][1]
        child["result"] = seal(
            child["result"] | {"context_request_sha256": content_sha256({"wrong": 1})},
            "result_sha256",
        )
    elif fault == "binary":
        binary = bytes(len(binary))
    body = seal(body, "result_sha256")
    if fault == "hash":
        body["result_sha256"] = content_sha256({"wrong": 1})
    with pytest.raises(ERRORS):
        candidate = PublicSolutionWorkBatchResult.model_validate(body)
        validate_embedding_work_batch_binary(batch, candidate, binary)


def test_query2_descriptor_emits_exact_query2_and_legacy_descriptor_rejects_before_model(
    descriptors, tmp_path
):
    batch, backend, scope, _, life = public_case(count=1)
    query = batch.children[0].request
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(query.model_dump(mode="json")))
    with pytest.raises(handoff.NativeEmbeddingHandoffError):
        handoff.run_native_reference_query_descriptors(descriptors, scope)
    assert not life and not backend.calls
    # Refused parsing consumed input only; retain output FDs, reset the input offset.
    import os

    os.lseek(descriptors.input, 0, os.SEEK_SET)
    handoff.run_native_public_solution_query_descriptors(descriptors, scope)
    result = PublicSolutionQueryResult.model_validate(
        json.loads((tmp_path / "result.json").read_bytes())
    )
    validate_public_solution_query_result(query, result)
    assert result.shard.binary.sha256 == sha256_bytes((tmp_path / "vectors.f32").read_bytes())
    assert life == ["load", "close"]


def test_query2_batch_fd_uses_same_writer_and_preserves_order(descriptors, tmp_path):
    batch, backend, scope, resources, life = public_case(count=3)
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(batch.model_dump(mode="json")))
    result = handoff.run_native_public_solution_work_batch_descriptors(
        descriptors, scope, resources=resources, maximum_total_output_bytes=1024**2, fence=Fence()
    )
    assert result == PublicSolutionWorkBatchResult.model_validate(
        json.loads((tmp_path / "result.json").read_bytes())
    )
    assert (
        len(
            validate_embedding_work_batch_binary(
                batch, result, (tmp_path / "vectors.f32").read_bytes()
            )
        )
        == 3
    )
    assert life == ["load", "close"] and len(backend.calls) == 3


def test_public_batch_parser_rejects_relabelled_legacy_request():
    old = EmbeddingWorkBatchInput.model_validate(batch_body())
    with pytest.raises(ERRORS):
        PublicSolutionWorkBatchInput.model_validate(old)
    with pytest.raises(ERRORS):
        PublicSolutionWorkBatchInput.model_validate(
            seal(
                old.model_dump(mode="json") | {"schema_version": "embedding-work-batch-input/2.0"},
                "request_sha256",
            )
        )
