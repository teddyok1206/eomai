"""Real original control publication/reads; explicit synthetic source/runtime authority."""

import json
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_allocation_window_seconds
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_orchestrator.local_embedding_control_artifacts import SOURCE_PLAN_ARTIFACT_TYPE
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from eom_workflow.local_embedding_source_plan_v3 import parse_local_embedding_source_plan_v3
from eom_workflow_runner import document_embedding_parent_preparation as parent_preparation
from eom_workflow_runner import local_embedding_service_reconciliation as preparation
from eom_workflow_runner.document_embedding_parent_preparation import (
    prepare_document_embedding_parent,
)

from tests.unit.document_embedding_parent_fixtures import parent_case as parent_case
from tests.unit.test_local_indexing_routed_sources import routed as routed
from tests.unit.test_local_indexing_routed_sources import routed_publisher as routed_publisher


def test_new_parent_allocation_has_control_allowance_not_a_larger_numeric_profile(
    parent_case, monkeypatch
):
    now = 10**12
    monkeypatch.setattr(parent_preparation, "time", SimpleNamespace(monotonic_ns=lambda: now))
    value = parent_case
    parent = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    numeric = value.pair.cuda.runtime_profile.resource_profile.timeout_seconds
    assert (
        parent.allocation.control_request.expires_monotonic_ns
        == now + embedding_gpu_allocation_window_seconds(numeric) * 10**9
    )
    assert value.request.resource_profile.timeout_seconds == numeric


def test_same_original_request_reuses_parent_and_selection_but_not_an_allocation_nonce(parent_case):
    value = parent_case
    first = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    replay = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    assert first.request == replay.request
    assert first.request.parent_request_sha256 == value.request.request_sha256
    assert first.request.schema_version == "embedding-batch-plan/1.1"
    assert first.allocation != replay.allocation
    assert first.allocation.control_request.parent_request_sha256 == first.request.request_sha256
    assert replay.allocation.control_request.parent_request_sha256 == first.request.request_sha256
    with (
        value.routed.publisher.sessions.begin() as session,
        first.operation.admission.admit(session, first.request) as current,
    ):
        assert current.selection.views == (value.request.namespace.view,)
        assert tuple(a.source for a in current.selection.anchors) == value.plan.sources
        assert current.selection.scope.actor_id == value.request.actor_context.service_id


def test_revoked_current_source_cannot_publish_or_dispatch_a_parent(parent_case):
    value = parent_case
    value.routed.current.deny = True
    with pytest.raises(PermissionError):
        prepare_document_embedding_parent(value.pair, value.request, value.sources.configuration)


def test_new_metadata_owner_reuses_original_selection_pointer_and_parent(parent_case):
    value = parent_case
    first = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    value.pair.cuda.controls.source_commit = "b" * 40
    replay = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    assert replay.request == first.request
    assert replay.operation.source_commit == "b" * 40
    assert replay.request.selection_manifest == first.request.selection_manifest
    assert replay.allocation != first.allocation


def test_cpu_match_rebuilds_exact_gpu_targets_into_a_separate_native_space(
    parent_case, monkeypatch
):
    value = parent_case
    # Immutable definition metadata only; this test never submits a Workflow.
    monkeypatch.setattr(
        preparation,
        "admitted_workflow_definition",
        lambda *_args, **_kwargs: SimpleNamespace(definition_hash="sha256:" + "9" * 64),
    )
    matched = value.pair.cpu.prepare_matching(value.pair.cuda, value.request)
    assert matched.space.runtime.device == "CPU" and matched.space != value.request.space
    assert matched.graph_snapshot == value.request.graph_snapshot
    assert matched.namespace.view == value.request.namespace.view
    with value.routed.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext.for_session(session, value.pair.cpu.owner.settings)
        pointer = matched.source_plan
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(SOURCE_PLAN_ARTIFACT_TYPE,),
            expected_primary_file="source-plan.json",
            max_bytes=64 * 1024**2,
        ).payload
        cpu_plan = parse_local_embedding_source_plan(json.loads(raw))
        assert cpu_plan.plan_sha256 == matched.source_plan_sha256
        assert cpu_plan.sources == value.plan.sources and cpu_plan.space != value.plan.space


@pytest.mark.parametrize("routed", ["public"], indirect=True)
def test_public_parent_pins_report_proofs_and_cpu_matching_uses_same_solution_text(
    parent_case, monkeypatch
):
    value = parent_case
    first = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    replay = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    assert first.request == replay.request
    assert first.request.schema_version == "embedding-batch-plan/1.3"
    assert first.allocation != replay.allocation
    with (
        value.routed.publisher.sessions.begin() as session,
        first.operation.admission.admit(session, first.request) as current,
    ):
        assert {anchor.evidence.kind for anchor in current.selection.anchors} == {
            "ACCEPTED_SOLUTION_ANALYSIS",
            "REGISTERED_CREATIVE_SOURCE_REPORT",
        }
        assert tuple(anchor.source for anchor in current.selection.anchors) == value.plan.sources
    monkeypatch.setattr(
        preparation,
        "admitted_workflow_definition",
        lambda *_args, **_kwargs: SimpleNamespace(definition_hash="sha256:" + "9" * 64),
    )
    matched = value.pair.cpu.prepare_matching(value.pair.cuda, value.request)
    assert matched.schema_version == "local-embedding-workflow-request/3.0"
    assert matched.space.runtime.device == "CPU"
    with value.routed.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext.for_session(session, value.pair.cpu.owner.settings)
        pointer = matched.source_plan
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(SOURCE_PLAN_ARTIFACT_TYPE,),
            expected_primary_file="source-plan.json",
            max_bytes=64 * 1024**2,
        ).payload
    cpu_plan = parse_local_embedding_source_plan_v3(json.loads(raw))
    assert cpu_plan.plan_sha256 == matched.source_plan_sha256
    assert cpu_plan.sources == value.plan.sources and cpu_plan.space != value.plan.space
    assert tuple(d.encoding.input_text_sha256 for d in cpu_plan.demands) == tuple(
        d.encoding.input_text_sha256 for d in value.plan.demands
    )
