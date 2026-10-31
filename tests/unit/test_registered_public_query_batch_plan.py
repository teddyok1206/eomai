"""Closed metadata successors only; no runtime/permission or real GPU evidence."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_work_batch import PublicSolutionWorkBatchInput
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityRequestV4,
    public_solution_reference_for_entry,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_query_key,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_query_context,
)
from eom_workflow.embedding_batch_plan_v14 import EmbeddingBatchSelectionV14
from eom_workflow.embedding_batch_plan_v15 import (
    BATCH_PLAN_V15_PROTOCOL,
    BATCH_PLAN_V15_SCHEMA_SHA256,
    BATCH_SELECTION_V15_SCHEMA_REF,
    EmbeddingBatchPlanRequestV15,
    EmbeddingBatchSelectionV15,
)
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequestV4
from eom_workflow.reference_query_routed_preparation import (
    REGISTERED_PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256,
    PublicRoutedReferenceQueryPreparation,
    RegisteredPublicRoutedReferenceQueryPreparation,
    parse_supported_reference_query_routed_preparation,
)
from eom_workflow_runner.reference_query_batch_binding import prepare_reference_query_batch_binding
from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery
from eom_workflow_runner.reference_query_routed_context import build_routed_reference_query_context

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member
from tests.unit.test_public_solution_query_batch_plan import (
    public_parent_case,
    public_parent_route_case,
)
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)
from tests.unit.test_registered_public_solution_index import registered_index_entry


def registered_public_parent_case(
    *, registered_anchor=True, migrated_devices=("CPU", "CUDA"), batch_id=None
):
    original = public_parent_case()
    body = original.selection.model_dump(mode="json")
    body["schema_version"] = BATCH_PLAN_V15_PROTOCOL
    if registered_anchor:
        body["anchors"] = [
            public_solution_reference_for_entry(registered_index_entry()).model_dump(mode="json")
        ]
    for device in migrated_devices:
        body["index_pairs"][0][device.lower()]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/4.0"
        )
    selection = EmbeddingBatchSelectionV15.model_validate(seal(body, "selection_sha256"))
    body = original.request.model_dump(mode="json")
    if batch_id is not None:
        body["batch_id"] = batch_id
    body.update(
        schema_version=BATCH_PLAN_V15_PROTOCOL,
        selection_manifest=member(
            "selection.json", BATCH_SELECTION_V15_SCHEMA_REF, selection, "e"
        ).model_dump(mode="json"),
        selection_sha256=selection.selection_sha256,
        child_selection_sha256s=list(selection.child_selection_sha256s),
    )
    request = EmbeddingBatchPlanRequestV15.model_validate(seal(body, "request_sha256"))
    return SimpleNamespace(
        original=original, selection=selection, request=request, policy=original.policy
    )


def registered_public_preparation_case(*, key="synthetic-registered-public-query"):
    case = registered_public_parent_case()
    return RegisteredPublicRoutedReferenceQueryPreparation.model_validate(
        seal(
            dict(
                schema_version="reference-query-routed-preparation/3.0",
                operator_id=case.selection.scope.actor_id,
                idempotency_key=key,
                intent_sha256=case.request.parent_request_sha256,
                owner_configuration_sha256="sha256:" + "c" * 64,
                parent=case.request.model_dump(mode="json"),
            ),
            "preparation_sha256",
        )
    )


@pytest.mark.parametrize("registered_anchor", [False, True])
@pytest.mark.parametrize("migrated_devices", [(), ("CPU",), ("CUDA",), ("CPU", "CUDA")])
def test_closed_parent15_preserves_original_device_pins_and_metadata_families(
    registered_anchor, migrated_devices
):
    case = registered_public_parent_case(
        registered_anchor=registered_anchor, migrated_devices=migrated_devices
    )
    assert parse_embedding_batch_plan_request(case.request) == case.request
    assert parse_embedding_batch_selection(case.selection) == case.selection
    assert embedding_batch_plan_schema_identity(case.request) == (
        BATCH_PLAN_V15_PROTOCOL,
        BATCH_PLAN_V15_SCHEMA_SHA256,
    )
    assert embedding_batch_query_key(case.request, 0)
    validate_embedding_batch_plan_controls(case.request, case.selection, case.policy)
    for device in ("CPU", "CUDA"):
        view = case.selection.selected_views(device)[0]
        assert view.index.spaces == case.original.selection.selected_views(device)[0].index.spaces
        assert view.index.index_manifest.schema_ref.endswith(
            "/4.0" if device in migrated_devices else "/3.0"
        )
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV14.model_validate(case.selection.model_dump(mode="json"))


@pytest.mark.parametrize("status", ["ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"])
def test_original_route_and_same_child_context4_use_unchanged_numeric_batch2(status):
    value = public_parent_route_case(status, case_factory=registered_public_parent_case)
    case = value.case
    context = build_routed_reference_query_context(
        parent=case.request,
        selection=case.selection,
        policy=case.policy,
        allocation=value.allocation,
        route=value.route,
        ordinal=0,
    )
    assert isinstance(context, PublicSolutionSimilarityRequestV4)
    device = value.decision.selected.backend.device
    assert context.anchor == case.selection.anchors[0]
    assert context.views == case.selection.selected_views(device)
    previous = public_workflow_case(device=device).request.model_dump(mode="json")
    previous.update(
        schema_version="reference-query-workflow-request/4.0",
        context_request=context.model_dump(mode="json"),
        runtime_bundle=value.decision.selected.profile.runtime_bundle.model_dump(mode="json"),
        resource_profile=value.decision.selected.profile.resource_profile.model_dump(mode="json"),
    )
    previous["operator_audit"]["operator_id"] = case.selection.scope.actor_id
    child = ReferenceQueryWorkflowRequestV4.model_validate(seal(previous, "request_sha256"))
    validate_embedding_batch_query_context(case.selection, value.decision, 0, child)
    with pytest.raises(ValueError):
        validate_embedding_batch_query_context(case.original.selection, value.decision, 0, child)
    material = registered_public_workflow_case(device=device)
    assert material.native_input.schema_version == "embedding-reference-query-input/2.0"
    if device == "CPU":
        # Fixed CPU handoff/executor recovery is covered separately with its
        # actual fixed resource fixture; this synthetic route is metadata only.
        return
    values = (
        material.request,
        material.policy,
        material.bundle,
        material.launch,
        material.native_input,
    )
    prepared = PreparedBatchReferenceQuery(*values)
    binding, batch = prepare_reference_query_batch_binding(
        case.request,
        value.route,
        (prepared,),
    )
    assert isinstance(batch, PublicSolutionWorkBatchInput)
    assert batch.schema_version == "embedding-work-batch-input/2.0"
    assert binding.children[0].native_input_sha256 == material.native_input.request_sha256


@pytest.mark.parametrize("fault", ["actor", "intent", "parent", "hash", "extra"])
def test_preparation3_preserves_actual_original_parent_identity_and_rejects_old_parser(fault):
    value = registered_public_preparation_case()
    assert parse_supported_reference_query_routed_preparation(canonical_json_bytes(value)) == value
    with pytest.raises(ValueError):
        PublicRoutedReferenceQueryPreparation.model_validate(value.model_dump(mode="json"))
    body = deepcopy(value.model_dump(mode="json"))
    if fault == "actor":
        body["operator_id"] = "operator_" + "f" * 32
    elif fault == "intent":
        body["intent_sha256"] = "sha256:" + "f" * 64
    elif fault == "parent":
        body["parent"] = public_parent_case().request.model_dump(mode="json")
    elif fault == "extra":
        body["execute_as_admin"] = True
    body = seal(body, "preparation_sha256")
    if fault == "hash":
        body["preparation_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        RegisteredPublicRoutedReferenceQueryPreparation.model_validate(body)


def test_successor_schemas_are_exact_mirrors_and_old_bytes_remain_pinned():
    root = Path(__file__).resolve().parents[2]
    for name, digest in (
        ("embedding-batch-plan-v1.5.schema.json", BATCH_PLAN_V15_SCHEMA_SHA256),
        (
            "reference-query-routed-preparation-v3.schema.json",
            REGISTERED_PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256,
        ),
        (
            "embedding-batch-plan-v1.4.schema.json",
            "sha256:f0f44da9655632dc11b23a8656c88049e01f73257818e6a1add22c3e706181b5",
        ),
        (
            "reference-query-routed-preparation-v2.schema.json",
            "sha256:38d7d03387d13d57e55a07c2dee96846f8fde13b86e8ca4daf93533ca9db92ba",
        ),
    ):
        raw = (root / "schemas/workflow" / name).read_bytes()
        assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == digest


@pytest.mark.parametrize(
    "fault", ["duplicate", "device", "proof", "index_family", "extra", "hash", "copied"]
)
def test_parent15_does_not_accept_rehashed_or_constructed_foreign_metadata(fault):
    selection = registered_public_parent_case().selection
    if fault == "copied":
        with pytest.raises(ValueError):
            EmbeddingBatchSelectionV15.model_validate(
                selection.model_copy(update={"execute_as_admin": True})
            )
        return
    body = selection.model_dump(mode="json")
    if fault == "duplicate":
        body["anchors"] *= 2
    elif fault == "device":
        body["index_pairs"][0]["cuda"] = deepcopy(body["index_pairs"][0]["cpu"])
    elif fault == "proof":
        body["anchors"][0]["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif fault == "index_family":
        body["index_pairs"][0]["cuda"]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    elif fault == "extra":
        body["query"]["execute_as_admin"] = True
    body = seal(body, "selection_sha256")
    if fault == "hash":
        body["selection_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV15.model_validate(body)
