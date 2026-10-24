"""Synthetic planning values; never source, physical allocation or numeric evidence."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow import embedding_batch_plan as plan
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal, view_recipe
from tests.unit.test_embedding_batch_route import route_case
from tests.unit.test_embedding_gpu_control import control_case
from tests.unit.test_similarity_context_contracts import context_request_body


def member(name, schema, value, seed):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=name,
        media_type="application/json",
        schema_ref=schema,
        sha256=sha256_bytes(canonical_json_bytes(value.model_dump(mode="json"))),
    )


def planning_case(*, purpose="REFERENCE_QUERY", status="ACQUIRED", batch_id=None):
    old = route_case(status, purpose)
    anchors = []
    for seed in ("a", "b"):
        entry = embedding_entry(seed)
        anchors.append(
            dict(
                basis="APPROVED_REFERENCE_ITEM",
                source=entry.profile.source_basis.source.model_dump(mode="json"),
                profile=InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                    mode="json"
                ),
                solution_evidence=entry.profile.source_basis.solution_evidence.model_dump(
                    mode="json"
                ),
            )
        )
    context = context_request_body()
    selection = plan.EmbeddingBatchSelection.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "SELECTION",
                "purpose": purpose,
                "scope": old["batch"].scope.model_dump(mode="json"),
                "corpus_id": "corpus_" + "1" * 32,
                "graph_snapshot": context["graph_snapshot"],
                "access_policy_revision_id": context["policy_revision_id"],
                "anchors": anchors,
                "recipe": view_recipe().model_dump(mode="json"),
                "views": ["CONTENT_ONLY", "CONCRETE_FACETS"]
                if purpose == "INDEX"
                else ["CONTENT_ONLY"],
                "query": None
                if purpose == "INDEX"
                else {
                    "consumer_purpose": "MOCK_EXAM_OBSERVATION",
                    "topics": [],
                    "unit_ids": [],
                    "maximum_sources": 520,
                    "top_k": 5,
                },
            },
            "selection_sha256",
        )
    )
    policy = old["policy"]
    request = plan.EmbeddingBatchPlanRequest.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "REQUEST",
                "batch_id": batch_id or "embeddingbatch_" + "1" * 32,
                "parent_request_sha256": "sha256:" + "1" * 64,
                "purpose": purpose,
                "scope": selection.scope.model_dump(mode="json"),
                "selection_manifest": member(
                    "selection.json", plan.BATCH_SELECTION_SCHEMA_REF, selection, "1"
                ).model_dump(mode="json"),
                "selection_sha256": selection.selection_sha256,
                "routing_policy": member(
                    "policy.json",
                    "eom://schemas/workflow/embedding-device-routing/1.0",
                    policy,
                    "2",
                ).model_dump(mode="json"),
                "routing_policy_sha256": policy.policy_sha256,
                "child_selection_sha256s": list(selection.child_selection_sha256s),
            },
            "request_sha256",
        )
    )
    control = control_case()[0].model_dump(mode="json")
    control.update(
        parent_request_sha256=request.request_sha256,
        child_set_sha256=content_sha256(list(request.child_selection_sha256s)),
        routing_policy_sha256=policy.policy_sha256,
        purpose=purpose,
        configuration=policy.cuda.backend.backend.configuration.model_dump(mode="json"),
        receipt_raw_sha256=policy.cuda.backend.backend.receipt_raw_sha256,
    )
    control = EmbeddingGpuAllocationRequest.model_validate(seal(control, "message_sha256"))
    allocation = plan.EmbeddingBatchAllocation.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "ALLOCATION",
                "request_sha256": request.request_sha256,
                "control_request": control.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            old["allocation"].model_dump(mode="json") | {"request_sha256": request.request_sha256},
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(policy, observation)
    route = plan.EmbeddingBatchRoute.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "ROUTED",
                "request_sha256": request.request_sha256,
                "allocation_record_sha256": allocation.record_sha256,
                "observation": observation.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            old["batch"].model_dump(mode="json")
            | {"routing_decision_sha256": decision.decision_sha256},
            "request_sha256",
        )
    )
    bound = plan.EmbeddingBatchBound.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "BOUND",
                "request_sha256": request.request_sha256,
                "route_record_sha256": route.record_sha256,
                "batch_request_sha256": batch.request_sha256,
                "resource_profile_sha256": batch.resource_profile_sha256,
                "children": [
                    dict(
                        selection_sha256=key,
                        workflow_id="workflow_" + str(i) * 32,
                        step_run_id="steprun_" + str(i) * 32,
                        native_job_id=child.request.job_id,
                        workflow_request_sha256=content_sha256({"workflow": i}),
                        launch_association_sha256=content_sha256({"launch": i}),
                        native_input_sha256=child.request.request_sha256,
                    )
                    for i, (key, child) in enumerate(
                        zip(request.child_selection_sha256s, batch.children, strict=True), 1
                    )
                ],
            },
            "record_sha256",
        )
    )
    failure = plan.EmbeddingBatchFailure.model_validate(
        seal(
            {
                "schema_version": plan.BATCH_PLAN_PROTOCOL,
                "message_type": "FAILED",
                "request_sha256": request.request_sha256,
                "error_code": "SOURCE_REVOKED",
                "evidence": request.selection_manifest.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    return SimpleNamespace(
        selection=selection,
        policy=policy,
        request=request,
        allocation=allocation,
        route=route,
        batch=batch,
        bound=bound,
        failure=failure,
    )


def test_schema_is_pinned_mirrored_202012_and_isolated():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-plan-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == plan.BATCH_PLAN_SCHEMA_SHA256
    schema = plan.embedding_batch_plan_schema()
    Draft202012Validator.check_schema(schema)
    schema.clear()
    assert plan.embedding_batch_plan_schema()["$schema"].endswith("2020-12/schema")


@pytest.mark.parametrize("purpose", ["INDEX", "REFERENCE_QUERY"])
@pytest.mark.parametrize("status", ["ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"])
def test_original_selection_allocation_route_and_child_binding_close(purpose, status):
    value = planning_case(purpose=purpose, status=status)
    plan.validate_embedding_batch_plan_controls(value.request, value.selection, value.policy)
    plan.validate_embedding_batch_allocation(value.request, value.policy, value.allocation)
    plan.validate_embedding_batch_route_record(
        value.request, value.policy, value.allocation, value.route
    )
    plan.validate_embedding_batch_binding(value.request, value.route, value.bound, value.batch)


@pytest.mark.parametrize(
    "name", ["selection", "request", "allocation", "route", "bound", "failure"]
)
def test_raw_extra_fields_and_copied_corruption_are_not_hidden(name):
    value = getattr(planning_case(), name)
    for changed in (
        value.model_dump(mode="json") | {"untrusted": "not authority"},
        value.model_copy(update={"schema_version": "forged"}),
    ):
        with pytest.raises(ValueError):
            type(value).model_validate(changed)


@pytest.mark.parametrize("fault", ["pointer", "children", "scope", "policy", "selection"])
def test_selection_pointer_scope_and_recipe_cannot_be_replaced_by_latest(fault):
    value = planning_case()
    body = value.request.model_dump(mode="json")
    if fault == "pointer":
        body["selection_manifest"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "children":
        body["child_selection_sha256s"].reverse()
    elif fault == "scope":
        body["scope"] = seal(body["scope"] | {"actor_id": "operator_foreign"}, "scope_sha256")
    else:
        body["routing_policy_sha256" if fault == "policy" else "selection_sha256"] = (
            "sha256:" + "f" * 64
        )
    changed = plan.EmbeddingBatchPlanRequest.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        plan.validate_embedding_batch_plan_controls(changed, value.selection, value.policy)


@pytest.mark.parametrize("fault", ["parent", "attempt", "policy", "child_set", "configuration"])
def test_allocation_and_route_are_original_request_and_runtime_specific(fault):
    value = planning_case()
    allocation, route = value.allocation, value.route
    if fault == "attempt":
        body = route.model_dump(mode="json")
        body["observation"] = seal(
            body["observation"] | {"allocation_attempt_id": "embeddingallocation_" + "b" * 32},
            "observation_sha256",
        )
        route = plan.EmbeddingBatchRoute.model_validate(seal(body, "record_sha256"))
    else:
        body = allocation.model_dump(mode="json")
        key = {
            "parent": "parent_request_sha256",
            "policy": "routing_policy_sha256",
            "child_set": "child_set_sha256",
        }.get(fault)
        if key:
            body["control_request"][key] = "sha256:" + "f" * 64
        else:
            body["control_request"]["configuration"]["configuration_sha256"] = "sha256:" + "f" * 64
        body["control_request"] = seal(body["control_request"], "message_sha256")
        allocation = plan.EmbeddingBatchAllocation.model_validate(seal(body, "record_sha256"))
    with pytest.raises(ValueError):
        plan.validate_embedding_batch_route_record(value.request, value.policy, allocation, route)


def test_duplicate_or_reordered_child_binding_cannot_change_original_order():
    value = planning_case()
    body = value.bound.model_dump(mode="json")
    body["children"].reverse()
    changed = plan.EmbeddingBatchBound.model_validate(seal(body, "record_sha256"))
    with pytest.raises(ValueError):
        plan.validate_embedding_batch_binding(value.request, value.route, changed, value.batch)
    body["children"][1] = deepcopy(body["children"][0])
    with pytest.raises(ValueError):
        plan.EmbeddingBatchBound.model_validate(seal(body, "record_sha256"))
