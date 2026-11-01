"""Private metadata/storage closure without public source or physical execution authority."""

import pytest
from eom_catalog_contracts.embedding_work_batch import PublicSolutionWorkBatchInput
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow.embedding_batch_plan import EmbeddingBatchBound, EmbeddingBatchPlanRequest
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_query_key,
    embedding_batch_selection_schema_ref,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    parse_public_embedding_batch_plan_request,
    validate_embedding_batch_allocation,
    validate_embedding_batch_binding,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_route_record,
)
from eom_workflow.embedding_batch_plan_v17 import (
    BATCH_PLAN_V17_PROTOCOL,
    BATCH_PLAN_V17_SCHEMA_SHA256,
    BATCH_SELECTION_V17_SCHEMA_REF,
)
from eom_workflow.embedding_device_routing import validate_embedding_device_batch_profile

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case


@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"))
def test_private_metadata_uses_existing_store_and_distinct_batch3_without_public_authority(status):
    value = private_planning_case(status=status)
    assert parse_embedding_batch_plan_request(value.request) == value.request
    assert parse_embedding_batch_selection(value.selection) == value.selection
    assert embedding_batch_plan_schema_identity(value.request) == (
        BATCH_PLAN_V17_PROTOCOL,
        BATCH_PLAN_V17_SCHEMA_SHA256,
    )
    assert embedding_batch_selection_schema_ref(value.selection) == BATCH_SELECTION_V17_SCHEMA_REF
    validate_embedding_batch_plan_controls(value.request, value.selection, value.policy)
    validate_embedding_batch_allocation(value.request, value.policy, value.allocation)
    validate_embedding_batch_route_record(
        value.request, value.policy, value.allocation, value.route
    )
    validate_embedding_batch_binding(value.request, value.route, value.bound, value.batch)
    assert (
        validate_embedding_device_batch_profile(value.policy, value.decision, value.batch)
        == value.batch
    )
    assert (
        EmbeddingBatchPlanStore(value.request, value.selection, value.policy).request
        == value.request
    )
    for reject in (
        parse_public_embedding_batch_plan_request,
        EmbeddingBatchPlanRequest.model_validate,
    ):
        with pytest.raises(ValueError):
            reject(value.request)
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_PLAN_INVALID"):
        embedding_batch_query_key(value.request, 0)


def test_private17_cannot_wrap_the_same_child_as_public_batch2():
    value = private_planning_case()
    public = PublicSolutionWorkBatchInput.model_validate(
        seal(
            value.batch.model_dump(mode="json")
            | {"schema_version": "embedding-work-batch-input/2.0", "purpose": "REFERENCE_QUERY"},
            "request_sha256",
        )
    )
    bound = EmbeddingBatchBound.model_validate(
        seal(
            value.bound.model_dump(mode="json") | {"batch_request_sha256": public.request_sha256},
            "record_sha256",
        )
    )
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_PLAN_INVALID"):
        validate_embedding_batch_binding(value.request, value.route, bound, public)


def test_legacy_model_schema_does_not_advertise_private_purpose_after_shared_value_extension():
    assert EmbeddingBatchPlanRequest.model_json_schema()["properties"]["purpose"]["enum"] == [
        "INDEX",
        "REFERENCE_QUERY",
    ]


def test_public_catalog_admission_denies_private_metadata_before_any_source_access(
    tmp_path, monkeypatch
):
    public = source_case(tmp_path, monkeypatch)
    private = private_planning_case()
    called = []
    monkeypatch.setattr(public.catalog, "authorize_scope", lambda *_args: called.append("source"))
    with (
        pytest.raises(ValueError, match="EMBEDDING_BATCH_PLAN_INVALID"),
        public.owner.admit(object(), private.request),
    ):
        raise AssertionError("a private source cannot enter public admission")
    assert not called
