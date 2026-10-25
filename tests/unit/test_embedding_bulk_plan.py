"""Schema-first bounded metadata/legacy closure; no source permission or GPU activation."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import embedding_batch_plan as v1
from eom_workflow import embedding_batch_plan_v11 as v11
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_selection_read_maximum,
    embedding_batch_selection_schema_ref,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_allocation,
    validate_embedding_batch_binding,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_route_record,
)
from jsonschema import Draft202012Validator

from tests.unit.embedding_bulk_plan_fixtures import bulk_planning_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case


def test_bulk_schema_is_pinned_mirrored_and_leaves_original_schema_bytes_unchanged():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-plan-v1.1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == v11.BATCH_PLAN_V11_SCHEMA_SHA256
    assert (
        sha256_bytes((root / "schemas/workflow/embedding-batch-plan-v1.schema.json").read_bytes())
        == v1.BATCH_PLAN_SCHEMA_SHA256
    )
    schema = v11.embedding_batch_plan_v11_schema()
    Draft202012Validator.check_schema(schema)
    schema.clear()
    assert v11.embedding_batch_plan_v11_schema()["$id"] == v11.BATCH_PLAN_V11_SCHEMA_REF


@pytest.mark.parametrize("count", (1, 32, 33, 520, 1024))
def test_index_bulk_cardinality_and_original_native_frames_close_exactly(count):
    case = bulk_planning_case(count)
    assert len(case.selection.anchors) == count
    assert parse_embedding_batch_plan_request(case.request) == case.request
    assert parse_embedding_batch_selection(case.selection) == case.selection
    validate_embedding_batch_plan_controls(case.request, case.selection, case.policy)
    validate_embedding_batch_allocation(case.request, case.policy, case.allocation)
    validate_embedding_batch_route_record(case.request, case.policy, case.allocation, case.route)
    validate_embedding_batch_binding(case.request, case.route, case.bound, case.batch)
    assert embedding_batch_plan_schema_identity(case.request) == (
        v11.BATCH_PLAN_V11_PROTOCOL,
        v11.BATCH_PLAN_V11_SCHEMA_SHA256,
    )
    assert (
        embedding_batch_selection_schema_ref(case.selection) == v11.BATCH_SELECTION_V11_SCHEMA_REF
    )
    assert (
        embedding_batch_selection_read_maximum(case.request) == v11.MAX_BULK_BATCH_SELECTION_BYTES
    )
    assert all(
        frame.schema_version == v1.BATCH_PLAN_PROTOCOL
        for frame in (case.allocation, case.route, case.bound)
    )
    assert "anchors" not in case.request.model_dump() and "vectors" not in case.request.model_dump()


def test_original_index_and_query_cannot_silently_take_bulk_version_or_limit():
    bulk = bulk_planning_case(33)
    legacy = planning_case()
    body = bulk.selection.model_dump(mode="json") | {"schema_version": v1.BATCH_PLAN_PROTOCOL}
    with pytest.raises(ValueError):
        v1.EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    body = legacy.selection.model_dump(mode="json") | {
        "schema_version": v11.BATCH_PLAN_V11_PROTOCOL
    }
    with pytest.raises(ValueError):
        parse_embedding_batch_selection(seal(body, "selection_sha256"))
    body = legacy.request.model_dump(mode="json") | {"schema_version": v11.BATCH_PLAN_V11_PROTOCOL}
    with pytest.raises(ValueError):
        parse_embedding_batch_plan_request(seal(body, "request_sha256"))
    assert parse_embedding_batch_plan_request(legacy.request) == legacy.request
    assert embedding_batch_plan_schema_identity(legacy.request)[0] == v1.BATCH_PLAN_PROTOCOL


@pytest.mark.parametrize("fault", ("overflow", "duplicate", "hash", "unknown", "extra", "oversize"))
def test_invalid_bulk_pointer_sets_are_rejected_without_repair(fault):
    body = bulk_planning_case(2).selection.model_dump(mode="json")
    if fault == "overflow":
        body["anchors"] *= 513
    elif fault == "duplicate":
        body["anchors"] = [body["anchors"][0]] * 2
    elif fault == "unknown":
        body["schema_version"] = "embedding-batch-plan/99.0"
    elif fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "oversize":
        body["authority"] = "x" * v11.MAX_BULK_BATCH_SELECTION_BYTES
    body = seal(body, "selection_sha256")
    if fault == "hash":
        body["selection_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        parse_embedding_batch_selection(body)


def test_mixed_wire_versions_and_wrong_schema_pointer_fail_explicitly():
    bulk, old = bulk_planning_case(2), planning_case(purpose="INDEX")
    with pytest.raises(ValueError):
        validate_embedding_batch_plan_controls(old.request, bulk.selection, old.policy)
    with pytest.raises(ValueError):
        validate_embedding_batch_plan_controls(bulk.request, old.selection, old.policy)
    body = bulk.request.model_dump(mode="json")
    body["selection_manifest"]["schema_ref"] = v1.BATCH_SELECTION_SCHEMA_REF
    with pytest.raises(ValueError):
        parse_embedding_batch_plan_request(seal(body, "request_sha256"))
    assert (
        sha256_bytes(canonical_json_bytes(bulk.selection.model_dump(mode="json")))
        == bulk.request.selection_manifest.sha256
    )


@pytest.mark.parametrize(
    "value", (None, True, 1, [], "unknown", {"schema_version": "embedding-batch-plan/9.0"})
)
def test_unsupported_shape_is_not_an_implicit_latest(value):
    for parser in (parse_embedding_batch_plan_request, parse_embedding_batch_selection):
        with pytest.raises(ValueError):
            parser(value)
