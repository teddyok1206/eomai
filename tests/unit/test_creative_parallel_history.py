"""A new capacity never creates another identity for already submitted source work."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
)
from eom_catalog_service import creative_cohort_preparation as preparation
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow.control_plane import parse_creative_learning_execution_plan
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.unit.test_creative_learning_parallel_continuation import parallel_case
from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_external_item_learning_execution_plan import _plan


@pytest.mark.parametrize("state", ["RUNNING", "COMPLETED", "FAILED"])
@pytest.mark.parametrize("wrong_policy", [False, True])
def test_indexed_predecessor_lookup_reuses_original_work_and_pins(monkeypatch, state, wrong_policy):
    previous, _, value = parallel_case()
    scope = CreativeLearningExecutionScope(
        previous.cohort, CreativeLearningParallelContinuation.model_validate(value), previous
    )
    resolved, _ = proposal()
    target = next(
        t for t in scope.cohort.targets if t.external_number == scope.cohort.seed_external_number
    )
    document = _plan(successor=True)
    pin = scope.extraction_preset if wrong_policy else previous.extraction_preset
    document.update(
        preset_id=pin.preset_id,
        preset_revision_id=pin.preset_revision_id,
        preset_sha256=pin.sha256,
        capacity_policy_revision_id=previous.capacity_policy_revision_id,
        workflow_definition_sha256=previous.workflow_definition_sha256,
        work_input=resolved.work.model_dump(mode="json"),
    )
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    plan = parse_creative_learning_execution_plan(document)
    row = ResolvedExecutionPlanRecord(
        plan_id=plan.plan_id,
        workflow_id=plan.workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
        plan_sha256=plan.plan_sha256,
        resolver_version=plan.resolver_version,
        canonical_document=plan.model_dump(mode="json"),
        resolved_at=plan.resolved_at,
    )
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key=previous.extraction_preset_key,
        external_item_learning_work=plan.work_input,
    )
    workflow = NS(
        workflow_id=plan.workflow_id,
        state=state,
        created_actor_type="human",
        created_actor_id=scope.cohort.requested_by_operator_id,
        definition_hash=previous.workflow_definition_sha256,
        definition_version=previous.workflow_definition_version,
        initial_request=workflow_request_storage_document(request),
    )
    step = NS(step_run_id="steprun_" + "1" * 32)
    session = Mock()
    session.scalar.side_effect = [None, workflow, row, step]
    owner = object.__new__(preparation.CreativeCohortPreparationService)
    owner.scope, owner.cohort = scope, scope.cohort
    owner.targets = {entry.source_id: entry for entry in scope.cohort.targets}
    owner.sessions = lambda: nullcontext(session)
    owner.source = Mock()
    owner._ensure_preview = Mock(
        side_effect=AssertionError("existing source must not render again")
    )
    monkeypatch.setattr(
        preparation, "resolve_external_item_learning_recovery", lambda _session, entry: entry
    )
    if wrong_policy:
        with pytest.raises(ValueError, match="WORKFLOW_POLICY_MISMATCH"):
            owner.prepare(target)
    else:
        selected = owner.prepare(target)
        assert selected.workflow_id == workflow.workflow_id
        assert selected.plan_id == plan.plan_id and selected.plan_sha256 == plan.plan_sha256
        assert session.scalar.call_count == 4
        first, second = session.scalar.call_args_list[:2]
        first_key = first.args[0].compile().params
        second_key = second.args[0].compile().params
        assert first_key != second_key  # new scope, then exact serial predecessor
    assert workflow.state == state
    owner.source.reauthorize.assert_called_once()
    owner._ensure_preview.assert_not_called()
