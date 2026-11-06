"""Actual uploaded Document/knowledge creation and atomic task binding, no model execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from eom_catalog_contracts import ReconcileKnowledgeAnalysisCommand
from eom_catalog_contracts.material_knowledge_analysis import CreateMaterialKnowledgeAnalysisCommand
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_store import (
    add_material_task,
    transition_material_run,
    transition_material_task,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.material_learning_controls import release_material_learning_controls
from eom_orchestrator.settings import Settings
from eom_workflow.compiler import compile_definition
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from eom_workflow_runner.state_machine import (
    CommandState,
    WorkflowState,
    transition_command,
    transition_workflow,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_knowledge_analysis_service import POLICY_ID
from tests.integration.test_material_learning_controls_storage import material_control_arguments
from tests.integration.test_material_learning_coordinator_storage import (
    coordinator_case as coordinator_case,
)
from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_page_preparation import InterruptibleExtractor
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


def test_actual_material_knowledge_creation_binds_one_child_and_replays_concurrently(
    creative_engine,
    coordinator_case,
    controls,
):
    accepted, settings, restart = coordinator_case
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    processing = restart(extractor)
    assert processing.advance_once().phase == "PREPARED"
    claim = processing.coordinator.claim()
    assert claim is not None
    context = processing.coordinator.context(claim)
    processing.coordinator.release(claim)
    source = context.prepared.sources[0]
    publisher = ControlArtifactPublisher(
        creative_engine,
        Settings(staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root),
    )
    presets = release_material_learning_controls(
        build_session_factory(creative_engine), publisher, **material_control_arguments(controls[2])
    )
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id, with_for_update=True)
        transition_material_run(
            session, run, MaterialLearningState.PROCESSING, now=datetime.now(UTC)
        )
        task, _ = add_material_task(
            session, run, task_kind="EXPLANATION", unit_key="synthetic-explanation-one", ordinal=3
        )
        task_id = task.task_id
        actor = run.created_by
        transition_material_task(
            session, run, task, MaterialTaskState.PREPARING, now=datetime.now(UTC)
        )
        import_workflow_definition(
            session,
            compile_definition(ROOT / "config/workflows/knowledge-analysis.v12.yaml", {"support"}),
        )
    command = CreateMaterialKnowledgeAnalysisCommand.model_validate(
        dict(
            material_task_id=task_id,
            source=dict(
                source_class="INTERNAL_GUIDE",
                document_revision_id=source.document_revision_id,
                first_physical_page=1,
                last_physical_page=1,
                curriculum_unit_keys=["1-(1)"],
                selected_regions=[
                    dict(
                        source_role="MAIN",
                        physical_page=1,
                        bounding_box=dict(left=0, top=0, right=10000, bottom=10000),
                    )
                ],
            ),
            preset_key="material-knowledge-analysis",
            risk_policy_revision_id=POLICY_ID,
            requested_by=actor,
            idempotency_key="material-knowledge:" + task_id,
        )
    )
    pointer = publish_material_metadata(
        processing.coordinator.artifacts,
        settings,
        command,
        member_path="material/knowledge-command.json",
        schema_ref="eom://schemas/knowledge/create-material-knowledge-analysis/1.0",
        artifact_type="material-knowledge-command",
        idempotency_key="material-knowledge-input:" + task_id,
    )
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id, with_for_update=True)
        task = session.get(MaterialLearningTaskRecord, task_id)
        processing.coordinator.pin_input(task, pointer)
        assert transition_material_task(
            session, run, task, MaterialTaskState.READY, now=datetime.now(UTC)
        )
        assert transition_material_task(
            session, run, task, MaterialTaskState.ANALYZING, now=datetime.now(UTC)
        )
    service = KnowledgeAnalysisApplicationService(creative_engine, settings)
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=10)
        return service.create_material_with_pinned_preset(
            command,
            preset_id=presets.document.preset_id,
            preset_revision_id=presets.document.preset_revision_id,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(create, range(2))
        assert (
            first.analysis_run_id == second.analysis_run_id
            and first.workflow_id == second.workflow_id
        )
        with Session(creative_engine) as session:
            task = session.get(MaterialLearningTaskRecord, task_id)
            assert task.analysis_run_id == first.analysis_run_id
            assert task.workflow_id == first.workflow_id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(KnowledgeAnalysisRunRecord)
                    .where(KnowledgeAnalysisRunRecord.idempotency_key == command.idempotency_key)
                )
                == 1
            )
            assert (
                session.get(WorkflowInstanceRecord, first.workflow_id).role_schema_version
                == "workflow-role/1.38.0"
            )
    finally:
        # No worker was executed. Close only these synthetic pending commands
        # through their lifecycle owners so fixture cleanup leaves no live lane.
        with Session(creative_engine) as session, session.begin():
            task = session.get(MaterialLearningTaskRecord, task_id)
            workflow_id = task.workflow_id
            analysis_id = task.analysis_run_id
            if workflow_id:
                for pending in session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.workflow_id == workflow_id,
                        WorkflowCommandRecord.state == "PENDING",
                    )
                ):
                    transition_command(pending, CommandState.CANCELLED)
                transition_workflow(
                    session,
                    workflow_id,
                    WorkflowState.CANCELLED,
                    "SYNTHETIC_MATERIAL_TEST_FINISHED",
                    actor_type="system",
                    actor_id=actor,
                    command_id=None,
                )
        if analysis_id:
            service.reconcile(
                ReconcileKnowledgeAnalysisCommand(analysis_run_id=analysis_id, requested_by=actor)
            )
        with Session(creative_engine) as session, session.begin():
            run = session.get(MaterialLearningRunRecord, accepted.run_id, with_for_update=True)
            task = session.get(MaterialLearningTaskRecord, task_id)
            transition_material_task(
                session,
                run,
                task,
                MaterialTaskState.FAILED,
                now=datetime.now(UTC),
                error_code="SYNTHETIC_MATERIAL_TEST_FINISHED",
            )
