"""Synthetic public QUERY parent values; not source, allocation or numeric evidence."""

import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityRequest
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchPlanRequest,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_query_key,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_query_context,
)
from eom_workflow.embedding_batch_plan_v12 import EmbeddingBatchSelectionV12
from eom_workflow.embedding_batch_plan_v13 import EmbeddingBatchSelectionV13
from eom_workflow.embedding_batch_plan_v14 import (
    BATCH_PLAN_V14_PROTOCOL,
    BATCH_PLAN_V14_SCHEMA_SHA256,
    BATCH_SELECTION_V14_SCHEMA_REF,
    EmbeddingBatchPlanRequestV14,
    EmbeddingBatchSelectionV14,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequestV3
from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)
from eom_workflow_runner.reference_query_batch_binding import prepare_reference_query_batch_binding
from eom_workflow_runner.reference_query_batch_driver import prepare_batch_reference_query_context
from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery
from eom_workflow_runner.reference_query_routed_context import build_routed_reference_query_context

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_embedding_device_routing import allocation_document, policy_document
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case


def public_parent_case():
    original = planning_case()
    context = public_similarity_case()[0]
    policy_body = policy_document("REFERENCE_QUERY")
    policy_body["view_recipe_sha256"] = context.views[0].recipe.recipe_sha256
    policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(policy_body, "policy_sha256"))
    pair = {}
    for device, profile, seed in (
        ("CPU", policy.cpu.profile, "c"),
        ("CUDA", policy.cuda.profile, "d"),
    ):
        view = context.views[0].model_dump(mode="json")
        query = profile.space.model_dump(mode="json") | {"purpose": "QUERY"}
        view["index"]["spaces"] = {
            "query": seal(query, "space_sha256"),
            "document": profile.space.model_dump(mode="json"),
        }
        view["index"].update(
            index_id="embeddingindex_" + seed * 32,
            index_revision_id="embeddingindexrev_" + seed * 32,
        )
        view["index"]["index_manifest"].update(
            artifact_id="artifact_" + seed * 32, artifact_revision_id="rev_" + seed * 32
        )
        pair[device.lower()] = view
    body = original.selection.model_dump(mode="json") | {
        "schema_version": BATCH_PLAN_V14_PROTOCOL,
        "graph_snapshot": context.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": context.policy_revision_id,
        "anchors": [context.anchor.model_dump(mode="json")],
        "recipe": context.views[0].recipe.model_dump(mode="json"),
        "views": ["CONCRETE_FACETS"],
        "source_classes": list(context.source_classes),
        "query": {
            "consumer_purpose": context.consumer_purpose,
            "maximum_sources": context.maximum_sources,
            "top_k": context.top_k,
        },
        "index_pairs": [pair],
    }
    body["scope"]["access_policy_sha256"] = context.policy_sha256
    body["scope"]["storage_partition"] = context.views[0].index.storage_partition
    body["scope"]["actor_id"] = public_workflow_case().request.operator_audit.operator_id
    body["scope"] = seal(body["scope"], "scope_sha256")
    selection = EmbeddingBatchSelectionV14.model_validate(seal(body, "selection_sha256"))
    request = EmbeddingBatchPlanRequestV14.model_validate(
        seal(
            original.request.model_dump(mode="json")
            | {
                "schema_version": BATCH_PLAN_V14_PROTOCOL,
                "scope": selection.scope.model_dump(mode="json"),
                "selection_manifest": member(
                    "selection.json", BATCH_SELECTION_V14_SCHEMA_REF, selection, "e"
                ).model_dump(mode="json"),
                "selection_sha256": selection.selection_sha256,
                "routing_policy": member(
                    "policy.json",
                    "eom://schemas/workflow/embedding-device-routing/1.0",
                    policy,
                    "f",
                ).model_dump(mode="json"),
                "routing_policy_sha256": policy.policy_sha256,
                "child_selection_sha256s": list(selection.child_selection_sha256s),
            },
            "request_sha256",
        )
    )
    return NS(**locals())


def test_public_query_parent_is_a_closed_additive_family_with_unchanged_route_policy():
    case = public_parent_case()
    assert parse_embedding_batch_selection(case.selection) == case.selection
    assert parse_embedding_batch_plan_request(case.request) == case.request
    assert embedding_batch_plan_schema_identity(case.request) == (
        BATCH_PLAN_V14_PROTOCOL,
        BATCH_PLAN_V14_SCHEMA_SHA256,
    )
    validate_embedding_batch_plan_controls(case.request, case.selection, case.policy)
    assert embedding_batch_query_key(case.request, 0)
    for old in (EmbeddingBatchSelection, EmbeddingBatchSelectionV12, EmbeddingBatchSelectionV13):
        with pytest.raises(ValueError):
            old.model_validate(case.selection.model_dump(mode="json"))
    with pytest.raises(ValueError):
        EmbeddingBatchPlanRequest.model_validate(case.request.model_dump(mode="json"))


@pytest.mark.parametrize("status,device", (("ACQUIRED", "CUDA"), ("BUSY", "CPU")))
def test_exact_public_child_context_follows_the_original_physical_route(status, device):
    case = public_parent_case()
    observation = EmbeddingGpuAllocationObservation.model_validate(
        allocation_document(case.policy, status)
    )
    decision = plan_embedding_device_route(case.policy, observation)
    old = public_workflow_case(device=device).request.model_dump(mode="json")
    context = case.context.model_dump(mode="json")
    context["views"] = [
        view.model_dump(mode="json") for view in case.selection.selected_views(device)
    ]
    old.update(
        context_request=seal(context, "request_sha256"),
        runtime_bundle=decision.selected.profile.runtime_bundle.model_dump(mode="json"),
        resource_profile=decision.selected.profile.resource_profile.model_dump(mode="json"),
    )
    old["operator_audit"]["operator_id"] = case.selection.scope.actor_id
    child = ReferenceQueryWorkflowRequestV3.model_validate(seal(old, "request_sha256"))
    validate_embedding_batch_query_context(case.selection, decision, 0, child)
    altered = child.context_request.model_dump(mode="json")
    altered["top_k"] += 1
    wrong = child.model_copy(
        update={
            "context_request": PublicSolutionSimilarityRequest.model_validate(
                seal(altered, "request_sha256")
            )
        }
    )
    with pytest.raises(ValueError):
        validate_embedding_batch_query_context(case.selection, decision, 0, wrong)


@pytest.mark.parametrize(
    "fault", ("duplicate", "legacy_options", "same_index", "wrong_device", "unknown", "hash")
)
def test_rejects_ambiguous_or_unpinned_public_parent_inputs(fault):
    case = public_parent_case()
    body = deepcopy(case.selection.model_dump(mode="json"))
    if fault == "duplicate":
        body["anchors"] *= 2
    elif fault == "legacy_options":
        body["query"]["topics"] = []
    elif fault == "same_index":
        body["index_pairs"][0]["cuda"] = deepcopy(body["index_pairs"][0]["cpu"])
    elif fault == "wrong_device":
        pair = body["index_pairs"][0]
        pair["cpu"], pair["cuda"] = pair["cuda"], pair["cpu"]
    elif fault == "unknown":
        body["query"]["execute_as_admin"] = True
    else:
        body["selection_sha256"] = "sha256:" + "0" * 64
    if fault != "hash":
        body = seal(body, "selection_sha256")
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV14.model_validate(body)


def test_public_query_parent_schema_is_mirrored_and_pinned():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-plan-v1.4.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == BATCH_PLAN_V14_SCHEMA_SHA256


def public_parent_route_case(status="ACQUIRED"):
    case = public_parent_case()
    allocation = new_embedding_batch_allocation_candidate(
        case.request, case.policy, now_monotonic_ns=time.monotonic_ns()
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            allocation_document(case.policy, status)
            | {
                "request_sha256": case.request.request_sha256,
                "allocation_attempt_id": allocation.control_request.allocation_attempt_id,
            },
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(case.policy, observation)
    route = EmbeddingBatchRoute.model_validate(
        seal(
            {
                "schema_version": "embedding-batch-plan/1.0",
                "message_type": "ROUTED",
                "request_sha256": case.request.request_sha256,
                "allocation_record_sha256": allocation.record_sha256,
                "observation": observation.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    return NS(case=case, allocation=allocation, decision=decision, route=route)


@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"))
def test_public_routed_context_and_child_identity_reuse_the_existing_parent_path(status):
    value = public_parent_route_case(status)
    case, allocation, decision, route = value.case, value.allocation, value.decision, value.route
    arguments = dict(
        parent=case.request,
        selection=case.selection,
        policy=case.policy,
        allocation=allocation,
        route=route,
        ordinal=0,
    )
    context = build_routed_reference_query_context(**arguments)
    assert isinstance(context, PublicSolutionSimilarityRequest)
    assert context == build_routed_reference_query_context(**arguments)
    assert context == prepare_batch_reference_query_context(case.request, 0, context)
    assert context.anchor == case.selection.anchors[0]
    assert context.views == case.selection.selected_views(decision.selected.backend.device)
    assert not {"topics", "unit_ids", "vector_mode"}.intersection(type(context).model_fields)
    for ordinal in (True, -1, 1, "0"):
        with pytest.raises(ValueError):
            build_routed_reference_query_context(**(arguments | {"ordinal": ordinal}))


def test_public_parent_binds_only_numeric_batch2_and_stages_exact_bytes(tmp_path, monkeypatch):
    import os

    from eom_catalog_contracts.embedding_work_batch import PublicSolutionWorkBatchInput
    from eom_catalog_service import embedding_batch_owner_workspace as workspace
    from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

    from tests.unit.test_embedding_batch_owner_control import control_frames
    from tests.unit.test_reference_query_execution_contracts import case as legacy_query_case

    value = public_parent_route_case()
    public = public_workflow_case(device="CUDA")
    material = PreparedBatchReferenceQuery(
        public.request, public.policy, public.bundle, public.launch, public.native_input
    )
    binding, batch = prepare_reference_query_batch_binding(
        value.case.request, value.route, (material,)
    )
    assert isinstance(batch, PublicSolutionWorkBatchInput)
    assert batch.children[0].request == material.request
    assert binding.children[0].native_input_sha256 == material.request.request_sha256
    frames = control_frames(request=value.allocation.control_request, batch=batch, binding=binding)
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(workspace, "BATCH_OWNER_ROOT", root)
    monkeypatch.setattr(
        workspace, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    staged = workspace.stage_owner_embedding_batch(frames.request, frames.ready, binding, batch)
    assert workspace.read_owner_embedding_batch(frames.request, staged.notice) == staged
    assert staged.batch == batch and staged.batch.schema_version == "embedding-work-batch-input/2.0"
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        prepare_reference_query_batch_binding(value.case.original.request, value.route, (material,))
    legacy = legacy_query_case(device="CUDA")
    wrong = PreparedBatchReferenceQuery(
        legacy.request, legacy.policy, legacy.bundle, legacy.launch, legacy.native_input
    )
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        prepare_reference_query_batch_binding(value.case.request, value.route, (wrong,))
