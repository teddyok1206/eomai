"""Actual disposable Item/Artifact/analysis lineage; synthetic model/source admission.

The historical fixture explicitly omits the new pre-acceptance check once, to
represent an existing ACCEPTED model anchor mistake. Production guards are then
restored. No accepted Artifact or terminal row is edited to invent that history.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisWorkerProposal,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand
from eom_catalog_service import knowledge_analysis_service as analysis_owner
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_recovery import recover_native_material_references
from eom_catalog_service.material_learning_store import (
    transition_material_run,
    transition_material_task,
)
from eom_catalog_service.material_registered_base_recovery import CreateMaterialBaseRecoveryCommand
from eom_identifiers import content_sha256
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.material_learning_controls import release_material_learning_controls
from eom_orchestrator.settings import Settings
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from eom_workflow_runner.models import WorkflowCommandRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration import test_knowledge_analysis_service as knowledge
from tests.integration import test_registered_item_solution_application as solutions
from tests.integration.test_material_learning_controls_storage import material_control_arguments
from tests.integration.test_material_learning_recovery_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_learning_recovery_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_read_case as native_read_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_registration_case as native_registration_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_visual_retry_case as native_visual_retry_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    registration_case as registration_case,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def registered_base_recovery_case(
    creative_engine, native_visual_retry_case, native_read_case, controls, tmp_path, monkeypatch
):
    from eom_catalog_service import material_learning_authorization, material_task_results
    from eom_catalog_service.registered_item_solution_base import RegisteredItemSolutionAnchorError

    case = native_visual_retry_case
    _create, resolved, _binding = native_read_case
    publisher = ControlArtifactPublisher(
        creative_engine,
        Settings(
            staging_root=case.settings.staging_root,
            nas_artifact_root=case.settings.nas_artifact_root,
        ),
    )
    presets = release_material_learning_controls(
        build_session_factory(creative_engine), publisher, **material_control_arguments(controls[2])
    )
    analyses = KnowledgeAnalysisApplicationService(creative_engine, case.settings)
    created = analyses.create_with_pinned_preset(
        CreateKnowledgeAnalysisCommand.model_validate(
            dict(
                source=dict(
                    source_kind="APPROVED_ITEM_REVISION",
                    source_class="APPROVED_ITEM",
                    item_revision_id=case.item.item_revision_id,
                ),
                preset_key="material-item-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id=knowledge.POLICY_ID,
                requested_by=case.command.actor_id,
                idempotency_key="historical-material-base:" + uuid4().hex,
            )
        ),
        preset_id=presets.item.preset_id,
        preset_revision_id=presets.item.preset_revision_id,
    )
    with analyses.sessions() as session:
        request = KnowledgeAnalysisRequestV2.model_validate(
            session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id).canonical_request
        )
    pointer = request.source.artifact_member
    content = json.loads(
        case.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=pointer.bytes,
        )
    )
    document = solutions._base_proposal(
        request,
        {
            "stem": json.dumps(content["body"], ensure_ascii=False),
            "explanations": {"correct_answer": content["solution"]},
        },
    ).model_dump(mode="json")
    document["anchors"][0].update(locator="/body", excerpt_sha256=content_sha256(content["body"]))
    document["anchors"][1].update(locator="/solution", excerpt_sha256="sha256:" + "0" * 64)
    knowledge._complete_proposal(
        creative_engine,
        case.settings,
        run_id=created.analysis_run_id,
        staging_root=tmp_path / "historical-worker",
        proposal_override=KnowledgeAnalysisWorkerProposal.model_validate(document),
    )
    with monkeypatch.context() as historical:
        historical.setattr(
            analysis_owner, "validate_registered_item_solution_proposal", lambda *a, **k: None
        )
        accepted = analyses.reconcile(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=created.analysis_run_id,
                requested_by=case.command.actor_id,
            )
        )
    assert accepted.state == "ACCEPTED"
    parent_id = "materialrun_" + uuid4().hex
    now = datetime.now(UTC)
    reference_task = None
    with Session(creative_engine) as session, session.begin():
        old_run = session.get(MaterialLearningRunRecord, case.command.run_id)
        parent = MaterialLearningRunRecord(
            run_id=parent_id,
            material_revision_id=old_run.material_revision_id,
            predecessor_run_id=old_run.run_id,
            attempt=old_run.attempt + 1,
            state="PROCESSING",
            next_event_sequence=1,
            created_by=case.command.actor_id,
            prepared_artifact_id=old_run.prepared_artifact_id,
            prepared_artifact_revision_id=old_run.prepared_artifact_revision_id,
            prepared_sha256=old_run.prepared_sha256,
            created_at=now,
            updated_at=now,
        )
        session.add(parent)
        session.flush()
        for old in session.scalars(
            select(MaterialLearningTaskRecord)
            .where(MaterialLearningTaskRecord.run_id == old_run.run_id)
            .order_by(MaterialLearningTaskRecord.ordinal)
        ):
            is_reference = old.task_id == case.source_task
            clone = MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid4().hex,
                run_id=parent.run_id,
                predecessor_task_id=old.task_id,
                task_kind=old.task_kind,
                unit_key=old.unit_key,
                ordinal=old.ordinal,
                attempt=old.attempt + 1,
                execution_lane="MATERIAL_LEARNING",
                state="ANALYZING" if is_reference else old.state,
                error_code=old.error_code,
                **{
                    key: getattr(old, key)
                    for key in (
                        "input_artifact_id",
                        "input_artifact_revision_id",
                        "input_sha256",
                        "output_artifact_id",
                        "output_artifact_revision_id",
                        "output_sha256",
                        "item_revision_id",
                    )
                },
            )
            session.add(clone)
            if is_reference:
                clone.analysis_run_id = accepted.analysis_run_id
                reference_task = clone
        session.flush()
        transition_material_task(
            session,
            parent,
            reference_task,
            MaterialTaskState.FAILED,
            now=now,
            error_code=RegisteredItemSolutionAnchorError.code,
        )
        transition_material_run(
            session,
            parent,
            MaterialLearningState.FAILED,
            now=now,
            error_code=RegisteredItemSolutionAnchorError.code,
        )
        reference_id = reference_task.task_id
        retry = RetryMaterialLearningRunCommand(
            actor_id=case.command.actor_id,
            run_id=parent.run_id,
            expected_updated_at=parent.updated_at,
        )
    # Source preparation/worker admission is synthetic in native_read_case. Keep
    # that exact declared port synthetic; accepted source/receipt/member/hash,
    # actor, workflow and all recovery persistence are real below.
    monkeypatch.setattr(
        material_task_results, "resolve_completed_material_task", lambda *a, **k: resolved
    )
    monkeypatch.setattr(
        material_learning_authorization.CatalogMaterialLearningSourceAuthorizer,
        "reauthorize",
        lambda *a, **k: None,
    )
    return case, analyses, retry, reference_id, accepted, content


def recover(case, command):
    return recover_native_material_references(
        case.artifacts.sessions, command, prepared=case.pointer, artifacts=case.artifacts
    )


def test_real_invalid_accepted_members_recover_only_the_analysis_and_replay_concurrently(
    creative_engine, registered_base_recovery_case, tmp_path
):
    case, analyses, retry, old_task_id, old_base, content = registered_base_recovery_case
    with Session(creative_engine) as session:
        proof = analyses.validate_material_base_recovery(
            session, task_id=old_task_id, operator_id=retry.actor_id
        )
        original = session.get(KnowledgeAnalysisRunRecord, old_base.analysis_run_id)
        old_pins = (
            original.accepted_result_artifact_id,
            original.accepted_result_artifact_revision_id,
            original.accepted_result_sha256,
            original.proposal_content_set_sha256,
        )
    successor = recover(case, retry)
    with Session(creative_engine) as session:
        child = session.scalar(
            select(MaterialLearningTaskRecord).where(
                MaterialLearningTaskRecord.run_id == successor.run_id,
                MaterialLearningTaskRecord.predecessor_task_id == old_task_id,
            )
        )
        task_id = child.task_id
        assert child.item_revision_id == proof.item_revision_id
        assert child.analysis_run_id is None and child.workflow_id is None
    command = CreateMaterialBaseRecoveryCommand(task_id, old_base.analysis_run_id, retry.actor_id)
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=15)
        return analyses.create_material_base_recovery(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: submit(), range(2)))
    assert results[0].analysis_run_id == results[1].analysis_run_id
    new_base = results[0]
    assert new_base.analysis_run_id != old_base.analysis_run_id
    with Session(creative_engine) as session:
        fresh = session.get(KnowledgeAnalysisRunRecord, new_base.analysis_run_id)
        new_request = KnowledgeAnalysisRequestV2.model_validate(fresh.canonical_request)
        assert fresh.predecessor_analysis_run_id == old_base.analysis_run_id
        assert new_request.source == proof.request.source
        assert (fresh.preset_id, fresh.preset_revision_id, fresh.risk_policy_revision_id) == (
            proof.request.execution_preset_id,
            proof.request.execution_preset_revision_id,
            proof.request.risk_policy_revision_id,
        )
        assert (
            session.get(MaterialLearningTaskRecord, task_id).analysis_run_id
            == fresh.analysis_run_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == fresh.workflow_id)
            )
            == 1
        )
    valid = solutions._base_proposal(
        new_request,
        {
            "stem": json.dumps(content["body"], ensure_ascii=False),
            "explanations": {"correct_answer": content["solution"]},
        },
    ).model_dump(mode="json")
    valid["anchors"][0].update(locator="/body", excerpt_sha256=content_sha256(content["body"]))
    valid["anchors"][1].update(
        locator="/solution", excerpt_sha256=content_sha256(content["solution"])
    )
    knowledge._complete_proposal(
        creative_engine,
        case.settings,
        run_id=new_base.analysis_run_id,
        staging_root=tmp_path / "recovered-worker",
        proposal_override=KnowledgeAnalysisWorkerProposal.model_validate(valid),
    )
    finished = analyses.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=new_base.analysis_run_id, requested_by=retry.actor_id
        )
    )
    assert finished.state == "ACCEPTED"
    assert (
        analyses.create_material_base_recovery(command).analysis_run_id == finished.analysis_run_id
    )
    with Session(creative_engine) as session:
        original = session.get(KnowledgeAnalysisRunRecord, old_base.analysis_run_id)
        assert original.state == "ACCEPTED"
        assert (
            original.accepted_result_artifact_id,
            original.accepted_result_artifact_revision_id,
            original.accepted_result_sha256,
            original.proposal_content_set_sha256,
        ) == old_pins
        assert (
            session.get(MaterialLearningTaskRecord, old_task_id).analysis_run_id
            == old_base.analysis_run_id
        )


def test_ordinary_analysis_retry_still_rejects_accepted_predecessor(registered_base_recovery_case):
    _case, analyses, retry, old_task_id, old_base, _content = registered_base_recovery_case
    with analyses.sessions() as session:
        proof = analyses.validate_material_base_recovery(
            session, task_id=old_task_id, operator_id=retry.actor_id
        )
    with pytest.raises(analysis_owner.KnowledgeAnalysisServiceError) as raised:
        analyses.create_with_pinned_preset(
            CreateKnowledgeAnalysisCommand.model_validate(
                dict(
                    source=dict(
                        source_kind="APPROVED_ITEM_REVISION",
                        source_class="APPROVED_ITEM",
                        item_revision_id=proof.item_revision_id,
                    ),
                    preset_key="material-item-analysis",
                    general_knowledge_mode="DISABLED",
                    risk_policy_revision_id=proof.request.risk_policy_revision_id,
                    requested_by=retry.actor_id,
                    predecessor_analysis_run_id=old_base.analysis_run_id,
                    idempotency_key="ordinary-accepted-denial:" + uuid4().hex,
                )
            ),
            preset_id=proof.request.execution_preset_id,
            preset_revision_id=proof.request.execution_preset_revision_id,
        )
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_RETRY_INVALID"
