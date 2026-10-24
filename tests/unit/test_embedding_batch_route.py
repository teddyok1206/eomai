"""Exact selected-route closure over synthetic batches; not allocation or activation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.inference_transfer_experiment import VIEWS
from eom_catalog_service.embedding_device_index_pair import pair_embedding_device_indexes
from eom_identifiers import content_sha256
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.embedding_batch_route import (
    EmbeddingBatchRouteError,
    validate_embedding_batch_route,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    encoding_identity,
    index_manifest,
    index_pointer,
    seal,
    source_binding,
)
from tests.unit.test_embedding_device_routing import allocation_document, policy_document
from tests.unit.test_embedding_reference_query_v11_contracts import input_body
from tests.unit.test_embedding_work_batch import batch_body


def route_case(
    status: str = "ACQUIRED",
    purpose: Literal["INDEX", "REFERENCE_QUERY"] = "REFERENCE_QUERY",
    *,
    row_count: int = 1,
) -> dict[str, Any]:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document(purpose))
    allocation = EmbeddingGpuAllocationObservation.model_validate(
        allocation_document(policy, status)
    )
    decision = plan_embedding_device_route(policy, allocation)
    profile = decision.selected.profile
    body = batch_body("DOCUMENT" if purpose == "INDEX" else "REFERENCE_QUERY")
    if purpose == "REFERENCE_QUERY":
        query = profile.space.model_dump(mode="json") | {"purpose": "QUERY"}
        query = seal(query, "space_sha256")
        for child in body["children"]:
            old = child["request"]
            request = input_body(row_count=row_count) | {
                "job_id": old["job_id"],
                "query_request_id": old["query_request_id"],
                "context_request_sha256": old["context_request_sha256"],
                "spaces": {"query": query, "document": profile.space.model_dump(mode="json")},
            }
            _retarget(request, query, profile.resource_profile.threads)
            child["request"] = seal(request, "request_sha256")
    else:
        for child in body["children"]:
            request = child["request"]
            request["space"] = profile.space.model_dump(mode="json")
            request["batch_size"] = profile.resource_profile.batch_size
            _retarget(request, request["space"], profile.resource_profile.threads)
            child["request"] = seal(request, "request_sha256")
    body["resource_profile_sha256"] = profile.resource_profile.resource_profile_sha256
    body["routing_decision_sha256"] = decision.decision_sha256
    batch = EmbeddingWorkBatchInput.model_validate(seal(body, "request_sha256"))
    pairs = []
    for view_index, view in enumerate(VIEWS):
        if purpose == "INDEX" or view not in {row.view for row in batch.children[0].request.rows}:
            continue
        indexes = []
        for device_index, binding in enumerate((policy.cpu, policy.cuda)):
            seed = str(2 * view_index + device_index + 1)
            index = index_manifest(
                source_binding(embedding_entry(), view=view, space=binding.profile.space),
                space=binding.profile.space,
                view=view,
                revision_seed=seed,
            )
            document = index.model_dump(mode="json") | {"index_id": "embeddingindex_" + seed * 32}
            indexes.append(EmbeddingIndexManifest.model_validate(seal(document, "index_sha256")))
        cpu, cuda = indexes
        pairs.append(
            pair_embedding_device_indexes(
                cpu_member=index_pointer(cpu, str(2 * view_index + 1)),
                cpu_index=cpu,
                cuda_member=index_pointer(cuda, str(2 * view_index + 2)),
                cuda_index=cuda,
            )
        )
    return dict(
        policy=policy, allocation=allocation, decision=decision, batch=batch, indexes=tuple(pairs)
    )


def _retarget(request: dict[str, Any], space: dict[str, Any], threads: int) -> None:
    from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace

    checked = EmbeddingSpace.model_validate(space)
    for row in request["rows"]:
        row["encoding"] = encoding_identity(row["text"], checked).model_dump(mode="json")
    request["rows"].sort(key=lambda row: row["encoding"]["encoding_sha256"])
    request["input_set_sha256"] = content_sha256([row["encoding"] for row in request["rows"]])
    request["threads"] = threads


@pytest.mark.parametrize("status", ["ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"])
@pytest.mark.parametrize("purpose", ["INDEX", "REFERENCE_QUERY"])
def test_selected_device_profile_batch_and_index_close_exactly(status, purpose) -> None:
    case = route_case(status, purpose)
    result = validate_embedding_batch_route(**case)
    if purpose == "INDEX":
        assert result == ()
    else:
        assert len(result) == 1 and result[0][0] == "CONTENT_ONLY"
        assert result[0][1].space == case["decision"].selected.profile.space
        assert result[0][1].space.runtime.device == ("CUDA" if status == "ACQUIRED" else "CPU")


def test_all_views_are_selected_in_stable_order_not_as_one_arbitrary_index() -> None:
    case = route_case(row_count=3)
    case["indexes"] = tuple(reversed(case["indexes"]))
    selected = validate_embedding_batch_route(**case)
    assert tuple(view for view, _ in selected) == VIEWS
    assert len({pin.index_revision_id for _, pin in selected}) == 3


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "extra_view", "partition", "recipe", "space"]
)
def test_missing_wrong_or_duplicate_view_index_is_not_substituted(fault: str) -> None:
    case = route_case()
    pair = case["indexes"][0]
    if fault == "missing":
        case["indexes"] = ()
    elif fault == "duplicate":
        case["indexes"] = (pair, pair)
    elif fault == "extra_view":
        case["indexes"] = (replace(pair, view="METADATA_ONLY"),)
    elif fault == "partition":
        case["indexes"] = (replace(pair, storage_partition="different"),)
    elif fault == "recipe":
        case["indexes"] = (replace(pair, recipe_sha256="sha256:" + "9" * 64),)
    else:
        case["indexes"] = (replace(pair, cuda=pair.cpu),)
    with pytest.raises(EmbeddingBatchRouteError):
        validate_embedding_batch_route(**case)


@pytest.mark.parametrize("fault", ["decision", "resource", "threads", "batch", "purpose"])
def test_batch_cannot_reuse_another_selection_or_numerical_recipe(fault: str) -> None:
    case = route_case()
    body = case["batch"].model_dump(mode="json")
    if fault in ("decision", "resource"):
        field = "routing_decision_sha256" if fault == "decision" else "resource_profile_sha256"
        body[field] = "sha256:" + "9" * 64
    elif fault in ("threads", "batch"):
        for child in body["children"]:
            child["request"]["threads" if fault == "threads" else "batch_size"] = 2
            child["request"] = seal(child["request"], "request_sha256")
    else:
        case["policy"] = EmbeddingDeviceRoutingPolicy.model_validate(policy_document("INDEX"))
    if fault != "purpose":
        case["batch"] = EmbeddingWorkBatchInput.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        validate_embedding_batch_route(**case)


def test_document_batch_cannot_attach_a_query_index_pair() -> None:
    case = route_case(purpose="INDEX")
    case["indexes"] = route_case()["indexes"]
    with pytest.raises(EmbeddingBatchRouteError):
        validate_embedding_batch_route(**case)
