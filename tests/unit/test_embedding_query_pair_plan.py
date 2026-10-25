"""Exact pinned QUERY contracts/admission; source/IAM/numerical leaves remain synthetic."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context_v2 import parse_supported_similarity_context_request
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_identifiers import sha256_bytes
from eom_workflow import embedding_batch_plan as v1
from eom_workflow import embedding_batch_plan_v11 as v11
from eom_workflow import embedding_batch_plan_v12 as v12
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_query_key,
    embedding_batch_selection_read_maximum,
    embedding_batch_selection_schema_ref,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_allocation,
    validate_embedding_batch_binding,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_query_context,
    validate_embedding_batch_route_record,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow_runner import embedding_batch_plan_admission as admission
from jsonschema import Draft202012Validator

from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_reference_query_execution_contracts import case as query_case


def test_exact_schema_is_packaged_and_predecessor_bytes_stay_unchanged():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-plan-v1.2.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == v12.BATCH_PLAN_V12_SCHEMA_SHA256
    for name, expected in (
        ("embedding-batch-plan-v1.schema.json", v1.BATCH_PLAN_SCHEMA_SHA256),
        ("embedding-batch-plan-v1.1.schema.json", v11.BATCH_PLAN_V11_SCHEMA_SHA256),
    ):
        assert sha256_bytes((root / "schemas/workflow" / name).read_bytes()) == expected
    schema = v12.embedding_batch_plan_v12_schema()
    Draft202012Validator.check_schema(schema)
    schema.clear()
    assert v12.embedding_batch_plan_v12_schema()["$id"] == v12.BATCH_PLAN_V12_SCHEMA_REF


@pytest.mark.parametrize("mixed", (False, True))
@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"))
def test_legacy_or_mixed_query_keeps_both_pins_and_original_execution_frames(mixed, status):
    value = paired_query_case(mixed=mixed, status=status)
    assert parse_embedding_batch_selection(value.selection) == value.selection
    assert parse_embedding_batch_plan_request(value.request) == value.request
    assert embedding_batch_plan_schema_identity(value.request) == (
        v12.BATCH_PLAN_V12_PROTOCOL,
        v12.BATCH_PLAN_V12_SCHEMA_SHA256,
    )
    assert (
        embedding_batch_selection_schema_ref(value.selection) == v12.BATCH_SELECTION_V12_SCHEMA_REF
    )
    assert embedding_batch_selection_read_maximum(value.request) == v1.MAX_BATCH_PLAN_BYTES
    validate_embedding_batch_plan_controls(value.request, value.selection, value.policy)
    validate_embedding_batch_allocation(value.request, value.policy, value.allocation)
    validate_embedding_batch_route_record(
        value.request, value.policy, value.allocation, value.route
    )
    validate_embedding_batch_binding(value.request, value.route, value.bound, value.batch)
    device = "CUDA" if status == "ACQUIRED" else "CPU"
    assert value.route.decision.selected.backend.device == device
    assert value.selection.selected_views(device)[0] == getattr(
        value.selection.index_pairs[0], device.lower()
    )
    assert embedding_batch_query_key(value.request, 0) != embedding_batch_query_key(
        value.request, 1
    )
    assert all(
        frame.schema_version == v1.BATCH_PLAN_PROTOCOL
        for frame in (value.allocation, value.route, value.bound)
    )


@pytest.mark.parametrize(
    "fault",
    (
        "null",
        "missing",
        "duplicate",
        "wrong_device",
        "same_pointer",
        "view",
        "recipe",
        "source_classes",
        "classes_order",
        "version",
        "index_purpose",
        "authority",
        "hash",
        "oversize",
        "too_many_anchors",
        "wrong_family",
    ),
)
def test_bad_pins_and_scope_are_not_repaired_or_replaced_with_latest(fault):
    body = paired_query_case().selection.model_dump(mode="json")
    pair = body["index_pairs"][0]
    if fault == "null":
        pair["cpu"]["index"] = None
    elif fault == "missing":
        body["index_pairs"] = []
    elif fault == "duplicate":
        body["index_pairs"] *= 2
    elif fault == "wrong_device":
        pair["cpu"], pair["cuda"] = pair["cuda"], pair["cpu"]
    elif fault == "same_pointer":
        pair["cuda"]["index"]["index_manifest"] = deepcopy(pair["cpu"]["index"]["index_manifest"])
    elif fault == "view":
        pair["cuda"]["view"] = "CONCRETE_FACETS"
    elif fault == "recipe":
        pair["cuda"]["recipe"]["recipe_sha256"] = "sha256:" + "a" * 64
    elif fault == "source_classes":
        body["source_classes"] = ["APPROVED_ITEM"]
    elif fault == "classes_order":
        body["source_classes"].reverse()
    elif fault == "version":
        body["schema_version"] = v1.BATCH_PLAN_PROTOCOL
    elif fault == "index_purpose":
        body["purpose"] = "INDEX"
    elif fault == "authority":
        body["role"] = "ADMIN"
    elif fault == "oversize":
        body["role"] = "a" * v1.MAX_BATCH_PLAN_BYTES
    elif fault == "too_many_anchors":
        body["anchors"] *= 17
    elif fault == "wrong_family":
        pair["cuda"]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    body = seal(body, "selection_sha256")
    if fault == "hash":
        body["selection_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        parse_embedding_batch_selection(body)


def test_selected_profile_must_match_both_pins_not_just_selected_device():
    value = paired_query_case()
    other = planning_case(purpose="INDEX")
    with pytest.raises(ValueError):
        validate_embedding_batch_plan_controls(value.request, value.selection, other.policy)
    old = planning_case()
    with pytest.raises(ValueError):
        validate_embedding_batch_plan_controls(old.request, value.selection, value.policy)
    with pytest.raises(ValueError):
        embedding_batch_query_key(value.request, True)


def selected_workflow(value):
    device = value.route.decision.selected.backend.device
    profile = value.route.decision.selected.profile
    request = query_case(device=device).request.model_dump(mode="json")
    context = request["context_request"]
    selected = value.selection
    context.update(
        anchor=selected.anchors[0].model_dump(mode="json"),
        graph_snapshot=selected.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=selected.access_policy_revision_id,
        policy_sha256=selected.scope.access_policy_sha256,
        views=[row.model_dump(mode="json") for row in selected.selected_views(device)],
        source_classes=list(selected.source_classes),
        vector_mode="REQUIRED",
        **selected.query.model_dump(mode="json"),
    )
    if isinstance(selected.index_pairs[0].cpu, v12.SimilarityViewSelectionV2):
        context["schema_version"] = "system-rag-similarity-request/2.0"
        request["schema_version"] = "reference-query-workflow-request/2.0"
    context = parse_supported_similarity_context_request(seal(context, "request_sha256"))
    request.update(
        context_request=context.model_dump(mode="json"),
        resource_profile=profile.resource_profile.model_dump(mode="json"),
        runtime_bundle=profile.runtime_bundle.model_dump(mode="json"),
    )
    request["operator_audit"]["operator_id"] = selected.scope.actor_id
    return parse_supported_reference_query_workflow_request(seal(request, "request_sha256"))


@pytest.mark.parametrize("fault", (None, "revision", "classes", "optional"))
@pytest.mark.parametrize("mixed", (False, True))
@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY"))
def test_child_context_uses_exact_selected_pins_and_filters(fault, mixed, status):
    value = paired_query_case(mixed=mixed, status=status)
    request = selected_workflow(value)
    if fault:
        body = request.model_dump(mode="json")
        context = body["context_request"]
        if fault == "revision":
            context["views"][0]["index"]["index_revision_id"] = "embeddingindexrev_" + "f" * 32
        elif fault == "classes":
            context["source_classes"] = ["PAST_EXAM"]
        else:
            context["vector_mode"] = "OPTIONAL"
        body["context_request"] = seal(context, "request_sha256")
        request = parse_supported_reference_query_workflow_request(seal(body, "request_sha256"))
        with pytest.raises(ValueError):
            validate_embedding_batch_query_context(
                value.selection, value.route.decision, 0, request
            )
    else:
        validate_embedding_batch_query_context(value.selection, value.route.decision, 0, request)


def test_actual_admission_uses_official_pair_resolver_before_yield(tmp_path, monkeypatch):
    value = source_case(tmp_path, monkeypatch, planned=paired_query_case())
    resolver = Mock(return_value=object())
    monkeypatch.setattr(admission, "resolve_embedding_device_index_pair", resolver)
    try:
        for _ in range(2):
            with (
                value.publisher.sessions.begin() as session,
                value.owner.admit(session, value.request) as current,
            ):
                assert current.indexes == (resolver.return_value,)
                args, kw = resolver.call_args
                assert args == (session, value.caller)
                for name in ("cpu", "cuda"):
                    owner, intent = kw[name + "_owner"], kw[name + "_intent"]
                    assert owner.identity_fence is value.catalog.identity_fence
                    assert owner.engine is value.engine and owner.settings == value.catalog.settings
                    assert intent.selection == getattr(value.selection.index_pairs[0], name)
                    assert intent.scope.graph_snapshot == value.scope.graph_snapshot
                    assert intent.scope.policy_sha256 == value.scope.policy_sha256
                    assert owner.configuration.namespace == intent.scope.namespace
        assert resolver.call_count == 2
        resolver.side_effect = EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        with (
            pytest.raises(EmbeddingRegistryError),
            value.publisher.sessions.begin() as session,
            value.owner.admit(session, value.request),
        ):
            pytest.fail("denied pair reached side effect window")
    finally:
        value.engine.dispose()
