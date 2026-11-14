"""Combined retry cloning with a typed synthetic Knowledge application guard port."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import KnowledgeProposalArtifactMember
from eom_catalog_service import knowledge_analysis_service as knowledge_owner
from eom_catalog_service import material_learning_recovery as owner
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_registered_base_recovery import (
    MaterialRegisteredBaseRecoveryProof,
)
from eom_catalog_service.registered_item_solution_base import RegisteredItemSolutionAnchorError

from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_visual_recovery import retry_case
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_application import base_request


def reference_case(monkeypatch):
    case = retry_case(monkeypatch)
    request = base_request()
    second_visual = MaterialLearningTaskRecord(
        task_id="materialtask_" + "4" * 32,
        run_id=case.source.run_id,
        task_kind="QUESTION",
        unit_key="question-13",
        ordinal=4,
        attempt=1,
        state="FAILED",
        error_code="OFFICE_VISUAL_USE_UNRESOLVED",
    )
    reference = MaterialLearningTaskRecord(
        task_id="materialtask_" + "5" * 32,
        run_id=case.source.run_id,
        task_kind="QUESTION",
        unit_key="question-14",
        ordinal=5,
        attempt=1,
        state="FAILED",
        error_code=RegisteredItemSolutionAnchorError.code,
        workflow_id="workflow_" + "6" * 32,
        input_artifact_id=case.base_pointer.artifact_id,
        input_artifact_revision_id=case.base_pointer.artifact_revision_id,
        input_sha256=case.base_pointer.sha256,
        output_artifact_id=case.base_pointer.artifact_id,
        output_artifact_revision_id=case.base_pointer.artifact_revision_id,
        output_sha256=case.base_pointer.sha256,
        item_revision_id=request.source.item_revision_id,
        analysis_run_id="analysisrun_" + "7" * 32,
    )
    case.tasks = (*case.tasks, second_visual, reference)
    case.session.scalars = lambda _query: case.tasks
    owner._quiescent_failed_workflows.return_value = {
        reference.workflow_id: SimpleNamespace(state="COMPLETED", created_actor_id=ACTOR)
    }
    proof = MaterialRegisteredBaseRecoveryProof(
        task_id=reference.task_id,
        item_revision_id=reference.item_revision_id,
        base_analysis_run_id=reference.analysis_run_id,
        request=request,
        accepted_result_artifact_id="artifact_" + "8" * 32,
        accepted_result_artifact_revision_id="rev_" + "9" * 32,
        accepted_result_sha256="sha256:" + "a" * 64,
        proposal_receipt=KnowledgeProposalArtifactMember.model_validate(
            request_value()["base_analysis"]["proposal_receipt"]
        ),
        failure_code=reference.error_code,
    )
    validate = Mock(return_value=proof)
    application = Mock(return_value=SimpleNamespace(validate_material_base_recovery=validate))
    monkeypatch.setattr(knowledge_owner, "KnowledgeAnalysisApplicationService", application)
    case.reference, case.proof, case.validate, case.application = (
        reference,
        proof,
        validate,
        application,
    )
    return case


def recover(case, **kwargs):
    return owner.recover_native_material_references(
        case.sessions,
        case.command,
        prepared=case.pointer,
        artifacts=case.artifacts,
        **kwargs,
    )


def test_mixed_visual_and_reference_failures_inherit_only_exact_success_and_item_pins(monkeypatch):
    case = reference_case(monkeypatch)
    before = tuple(
        (
            row.task_id,
            row.state,
            row.analysis_run_id,
            row.item_revision_id,
            row.graph_snapshot_revision_id,
        )
        for row in case.tasks
    )
    result = recover(case)
    assert result.reused_tasks == 2 and result.retried_tasks == 3
    successor = case.records[result.run_id]
    assert successor.prepared_sha256 == case.pointer.sha256
    assert case.source.prepared_sha256 == case.base_pointer.sha256
    clones = [row for row in case.added if isinstance(row, MaterialLearningTaskRecord)]
    assert [row.state for row in clones] == [
        "COMPLETED",
        "COMPLETED",
        "PENDING",
        "PENDING",
        "REGISTERED",
    ]
    assert [row.predecessor_task_id for row in clones] == [row.task_id for row in case.tasks]
    assert all(
        getattr(clones[-1], name) == getattr(case.reference, name)
        for name in owner._ARTIFACT_FIELDS
    )
    assert clones[-1].analysis_run_id is None and clones[-1].solution_analysis_run_id is None
    assert clones[-1].workflow_id is None and clones[-1].error_code is None
    assert clones[1].item_revision_id == case.tasks[1].item_revision_id
    assert clones[1].graph_snapshot_revision_id == case.tasks[1].graph_snapshot_revision_id
    assert (
        clones[2].input_artifact_revision_id is None
        and clones[3].output_artifact_revision_id is None
    )
    assert before == tuple(
        (
            row.task_id,
            row.state,
            row.analysis_run_id,
            row.item_revision_id,
            row.graph_snapshot_revision_id,
        )
        for row in case.tasks
    )
    assert case.locks == ["revision", "run"]
    assert case.validate.call_count == 2
    for call in case.validate.call_args_list:
        assert call.args == (case.session,)
        assert call.kwargs == {"task_id": case.reference.task_id, "operator_id": ACTOR}
    assert owner.append_material_event.call_args_list[0].kwargs["event_type"] == (
        "MATERIAL_NATIVE_REFERENCE_RETRY_STARTED"
    )


def test_exact_replay_reproduces_reference_proof_without_creating_another_successor(monkeypatch):
    case = reference_case(monkeypatch)
    first = recover(case)
    second = recover(case)
    assert first.run_id == second.run_id and not first.replayed and second.replayed
    assert case.validate.call_count == 4
    assert len([row for row in case.added if isinstance(row, MaterialLearningRunRecord)]) == 1


def ordinary_failure(case):
    task = MaterialLearningTaskRecord(
        task_id="materialtask_" + "f" * 32,
        run_id=case.source.run_id,
        task_kind="QUESTION",
        unit_key="question-17",
        ordinal=6,
        attempt=1,
        state="FAILED",
        error_code="MATERIAL_LEARNING_ANALYSIS_TERMINAL_FAILURE",
        workflow_id="workflow_" + "f" * 32,
        analysis_run_id="analysisrun_" + "f" * 32,
        **{name: getattr(case.reference, name) for name in owner._ARTIFACT_FIELDS},
    )
    case.tasks = (*case.tasks, task)
    owner._quiescent_failed_workflows.return_value[task.workflow_id] = SimpleNamespace(
        state="COMPLETED", created_actor_id=ACTOR
    )
    return task


def test_mixed_ordinary_terminal_analysis_reuses_item_without_accepted_base_guard(monkeypatch):
    case = reference_case(monkeypatch)
    ordinary = ordinary_failure(case)
    result = recover(case)
    assert result.retried_tasks == 4 and result.reused_tasks == 2
    clones = [row for row in case.added if isinstance(row, MaterialLearningTaskRecord)]
    clone = clones[-1]
    assert clone.state == "REGISTERED" and clone.predecessor_task_id == ordinary.task_id
    assert all(getattr(clone, name) == getattr(ordinary, name) for name in owner._ARTIFACT_FIELDS)
    assert clone.analysis_run_id is None and clone.solution_analysis_run_id is None
    assert clone.workflow_id is None and clone.error_code is None
    assert ordinary.state == "FAILED" and ordinary.analysis_run_id is not None
    assert recover(case).replayed
    assert {call.kwargs["task_id"] for call in case.validate.call_args_list} == {
        case.reference.task_id
    }


def test_ordinary_failure_alone_cannot_acquire_the_reference_recovery_scope(monkeypatch):
    case = reference_case(monkeypatch)
    ordinary_failure(case)
    case.reference.error_code = "MATERIAL_LEARNING_ANALYSIS_TERMINAL_FAILURE"
    with pytest.raises(MaterialLearningSourceError, match="REFERENCE_RECOVERY_PHASE_INVALID"):
        recover(case)
    case.validate.assert_not_called()
    assert not case.added


def test_forged_typed_task_error_still_requires_the_actual_accepted_base_owner(monkeypatch):
    case = reference_case(monkeypatch)
    ordinary = ordinary_failure(case)
    ordinary.error_code = RegisteredItemSolutionAnchorError.code

    def validate(_session, *, task_id, operator_id):
        assert operator_id == ACTOR
        if task_id == ordinary.task_id:
            raise ValueError("MATERIAL_REGISTERED_BASE_RECOVERY_BASE_INVALID")
        return case.proof

    case.validate.side_effect = validate
    with pytest.raises(ValueError, match="RECOVERY_BASE_INVALID"):
        recover(case)
    assert not case.added


def test_stale_mixed_command_is_rejected_before_any_reference_owner_read(monkeypatch):
    case = reference_case(monkeypatch)
    ordinary_failure(case)
    case.command = case.command.model_copy(
        update={"expected_updated_at": case.command.expected_updated_at + timedelta(seconds=1)}
    )
    with pytest.raises(MaterialLearningSourceError, match="STATE_STALE"):
        recover(case)
    case.validate.assert_not_called()
    assert not case.added


@pytest.mark.parametrize("field", ["task_id", "item_revision_id", "base_analysis_run_id"])
def test_public_owner_proof_must_match_the_exact_failed_task_and_existing_pins(monkeypatch, field):
    case = reference_case(monkeypatch)
    case.validate.return_value = replace(case.proof, **{field: "different-pinned-identity"})
    with pytest.raises(MaterialLearningSourceError, match="REFERENCE_RECOVERY_POINTER_INVALID"):
        recover(case)
    assert not case.added


@pytest.mark.parametrize(
    "code", ["REFERENCE_NOT_INVALID", "SOURCE_HASH_MISMATCH", "PERMISSION_REVOKED"]
)
def test_public_guard_denials_or_source_hash_errors_are_not_reinterpreted_as_visual_failures(
    monkeypatch, code
):
    case = reference_case(monkeypatch)
    case.validate.side_effect = ValueError(code)
    with pytest.raises(ValueError, match=code):
        recover(case)
    assert not case.added


def test_current_reference_proof_is_recomputed_after_creating_the_linked_rows(monkeypatch):
    case = reference_case(monkeypatch)
    case.validate.side_effect = [
        case.proof,
        replace(case.proof, accepted_result_sha256="sha256:" + "0" * 64),
    ]
    with pytest.raises(MaterialLearningSourceError, match="REFERENCE_RECOVERY_CHANGED"):
        recover(case)
    # Actual transaction rollback is covered by the opt-in disposable DB suite.
    assert case.reference.analysis_run_id == case.proof.base_analysis_run_id
    assert case.reference.state == "FAILED"


def test_replay_also_reauthorizes_the_actual_reference_owner(monkeypatch):
    case = reference_case(monkeypatch)
    recover(case)
    case.validate.side_effect = ValueError("PERMISSION_REVOKED")
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        recover(case)
    assert len([row for row in case.added if isinstance(row, MaterialLearningRunRecord)]) == 1


def test_visual_only_recovery_keeps_its_empty_output_guard(monkeypatch):
    case = reference_case(monkeypatch)
    with pytest.raises(MaterialLearningSourceError, match="VISUAL_RECOVERY_PHASE_INVALID"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )
    case.validate.assert_not_called()
    assert not case.added


def test_reference_entry_requires_an_actual_reference_failure_not_only_visual_failures(monkeypatch):
    case = retry_case(monkeypatch)
    with pytest.raises(MaterialLearningSourceError, match="REFERENCE_RECOVERY_PHASE_INVALID"):
        owner.recover_native_material_references(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )
    assert not case.added


def test_nonquestion_failure_is_not_eligible_for_the_combined_entry(monkeypatch):
    case = reference_case(monkeypatch)
    case.tasks[2].task_kind = "DISCOVER"
    with pytest.raises(MaterialLearningSourceError, match="REFERENCE_RECOVERY_PHASE_INVALID"):
        recover(case)
    case.validate.assert_not_called()
    assert not case.added
