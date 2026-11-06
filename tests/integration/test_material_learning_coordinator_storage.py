"""Actual durable intake/preparation/coordinator with a synthetic extractor, no model work."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import CreateMaterialLearningCommand
from eom_catalog_contracts.material_learning_preparation import MaterialPreparationProfile
from eom_catalog_service.material_learning_coordinator import MaterialLearningCoordinator
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
from eom_catalog_service.material_learning_processing import MaterialLearningProcessingService
from eom_catalog_service.material_learning_source import MaterialLearningSourceService
from eom_catalog_service.material_learning_source_projection import MaterialSourceProjectionService
from eom_catalog_service.material_learning_store import transition_material_run
from eom_identifiers import content_sha256
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.material_learning_state import MaterialLearningState
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_page_preparation import InterruptibleExtractor
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls
from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_material_learning_preparation import profile

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def coordinator_case(creative_engine, material_intake, controls):
    actor, settings, source, source_command = material_intake
    settings = replace(settings, nas_artifact_root=controls[1].nas_artifact_root)
    receipt = MaterialLearningSourceService(creative_engine, settings).ingest(
        source, source_command
    )
    command = CreateMaterialLearningCommand.model_validate(
        dict(
            actor_id=actor,
            idempotency_key="coordinator-" + uuid4().hex,
            upload=dict(
                title="Synthetic mixed workbook",
                material_kind="WORKBOOK",
                source_description="disposable coordinator fixture",
                additional_instructions="",
                curriculum_unit_hints=[],
                rights_confirmed=True,
            ),
            sources=[dict(source_role="MAIN", source_upload=receipt.model_dump(mode="json"))],
        )
    )
    accepted = MaterialLearningIntakeService(creative_engine, settings).create(command)
    platform = Settings(
        staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root
    )
    publisher = ControlFileSetPublisher(creative_engine, platform)
    document = profile()
    document["chunk_page_limit"] = 1
    document["profile_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "profile_sha256"}
    )
    pinned_profile = MaterialPreparationProfile.model_validate(document)
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v1.yaml", {"support"})
    with Session(creative_engine) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        definition_id = definition.definition_id
    _, row = _published_preset()
    # Preparation does not submit/resolve this declared execution port. Actual
    # preset lifecycle/Workflow start are verified in their dedicated DB suites.
    preset = ExecutionPresetRevision.model_validate(row.canonical_document)

    def restart(extractor):
        preparation = MaterialPagePreparationService(
            creative_engine,
            settings=settings,
            publisher=publisher,
            source_commit="1" * 40,
            extractor=extractor,
            projections=MaterialSourceProjectionService(
                creative_engine, settings=settings, platform_settings=platform, publisher=publisher
            ),
        )
        coordinator = MaterialLearningCoordinator(
            creative_engine,
            settings=settings,
            preparation=preparation,
            profile=pinned_profile,
            preset=preset,
            definition_id=definition_id,
            owner_id="synthetic-owner-" + uuid4().hex,
        )
        return MaterialLearningProcessingService(coordinator, registration=Mock(), graph=Mock())

    return accepted, settings, restart


def test_coordinator_restart_reuses_committed_page_and_releases_short_claim(
    creative_engine, coordinator_case
):
    accepted, settings, restart = coordinator_case
    original_files = set(settings.nas_artifact_root.rglob("original.pdf"))
    first_extractor = InterruptibleExtractor()
    first = restart(first_extractor)
    with pytest.raises(RuntimeError, match="synthetic process interruption"):
        first.advance_once()
    with Session(creative_engine) as session:
        run = session.get(MaterialLearningRunRecord, accepted.run_id)
        assert run.state == "PREPARING" and run.lease_owner is None
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.run_id == accepted.run_id
                )
            )
        )
        assert len(tasks) == 1 and tasks[0].input_artifact_revision_id is not None
        original_input = tasks[0].input_artifact_revision_id
    second_extractor = InterruptibleExtractor()
    second_extractor.interrupt = False
    second = restart(second_extractor)
    progress = second.advance_once()
    assert progress.phase == "PREPARED" and progress.workflow_to_drive is None
    assert first_extractor.calls == [1, 2] and second_extractor.calls == [2, 3]
    with Session(creative_engine) as session:
        run = session.get(MaterialLearningRunRecord, accepted.run_id)
        assert run.state == "DISCOVERING" and run.lease_owner is None
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == accepted.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert [(task.task_kind, task.state) for task in tasks] == [
            ("PREPARE", "COMPLETED"),
            ("DISCOVER", "PENDING"),
        ]
        assert tasks[0].input_artifact_revision_id == original_input
    second.registration.register_completed.assert_not_called()
    assert set(settings.nas_artifact_root.rglob("original.pdf")) == original_files


def test_paused_material_without_active_child_does_not_claim_or_execute(
    creative_engine, coordinator_case
):
    accepted, _, restart = coordinator_case
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    owner = restart(extractor)
    assert owner.advance_once().phase == "PREPARED"
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id, with_for_update=True)
        transition_material_run(session, run, MaterialLearningState.PAUSED, now=datetime.now(UTC))
    assert owner.advance_once().phase == "IDLE"
    owner.registration.register_completed.assert_not_called()
    owner.graph.advance_item_analysis.assert_not_called()
