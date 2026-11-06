"""Real Registry/Artifact commit, replay and interruption with a declared synthetic result port.

Completed worker/source authorization is tested by separate role/page owners.
This suite does not claim source rights, model execution or scientific validation.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning import MaterialExtractionWork
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_task_results import ResolvedMaterialTask
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.compiler import compile_definition
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from eom_workflow.models import MaterialLearningRoleResult
from eom_workflow_runner.repository import (
    create_step_run,
    create_workflow_instance,
    import_workflow_definition,
)
from eom_workflow_runner.state_machine import (
    StepState,
    WorkflowState,
    transition_step,
    transition_workflow,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.unit.test_material_learning_contracts import extraction_result, extraction_work, rehash
from tests.unit.test_material_learning_role_contracts import worker_input

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registration_case(creative_engine, material_intake, tmp_path, monkeypatch):
    actor, settings, _, _ = material_intake
    artifact_root = Path(os.environ["EOM_API_TEST_STATE"]) / "material-registry-artifacts"
    artifact_root.mkdir(exist_ok=True)
    settings = replace(settings, nas_artifact_root=artifact_root)
    settings.staging_root.chmod(0o750)
    for directory in (settings.content_pack_staging_root, settings.registry_staging_root):
        directory.mkdir(mode=0o750)
        directory.chmod(0o750)
    artifacts = CatalogArtifactService(creative_engine, settings)
    packs = ContentPackService(creative_engine, settings)
    pack = packs.import_source(ROOT / "content/packs/uploaded-material-item/1.0.0")
    pack = packs.release(pack.content_pack_release_id, actor_id=actor)
    data = extraction_work()
    data.update(
        material_id="material_" + uuid4().hex,
        material_revision_id="materialrev_" + uuid4().hex,
        task_id="materialtask_" + uuid4().hex,
    )
    work = MaterialExtractionWork.model_validate(rehash(data))
    work_pointer = publish_material_metadata(
        artifacts,
        settings,
        work,
        member_path="material/work.json",
        schema_ref="eom://schemas/material-learning/extraction-work/1.0",
        idempotency_key="synthetic-material-input:" + work.task_id,
        artifact_type="material-learning-input",
    )
    with Session(creative_engine) as session, session.begin():
        definition, _ = import_workflow_definition(
            session,
            compile_definition(ROOT / "config/workflows/material-learning.v1.yaml", {"support"}),
        )
        workflow, _ = create_workflow_instance(
            session,
            definition=definition,
            request=MaterialLearningWorkflowRequest(work_input=work),
            idempotency_key="synthetic-material-registry:" + work.task_id,
            actor_type="human",
            actor_id=actor,
            material_learning_authorizer=SimpleNamespace(reauthorize=lambda *args, **kwargs: work),
        )
        workflow_id = workflow.workflow_id
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_REGISTRY_STARTED",
            actor_type="human",
            actor_id=actor,
            command_id=None,
        )
        step = create_step_run(
            session,
            workflow_id=workflow_id,
            step_key="learn",
            step_type="agent",
            worker_role="support",
            result_schema="material-learning-result@1.0",
            input_pointer_manifest={},
            max_attempts=1,
        )
        for state in (StepState.RUNNING, StepState.SUCCEEDED):
            transition_step(step, state)
        step_id = step.step_run_id
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.COMPLETED,
            "SYNTHETIC_REGISTRY_SOURCE_COMPLETED",
            actor_type="human",
            actor_id=actor,
            command_id=None,
        )
    envelope = worker_input()
    role_data = {
        key: envelope[key]
        for key in ("schema_version", "protocol_version", "job_id", "role", "artifact")
    }
    result = extraction_result()
    result["input_sha256"] = work.input_sha256
    role_data.update(
        workflow_id=workflow_id,
        step_run_id=step_id,
        status="ok",
        completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        output={"learning_result": result},
    )
    role = MaterialLearningRoleResult.model_validate(role_data)
    encoded = canonical_json_bytes(role.model_dump(mode="json"))
    role_path = tmp_path / "synthetic-role.json"
    role_path.write_bytes(encoded)
    committed = artifacts.commit_file_set(
        files={"result.json": role_path},
        primary_file="result.json",
        artifact_type="workflow_support",
        idempotency_key="synthetic-material-result:" + work.task_id,
        request={"fixture": True},
        result={"fixture": True},
        file_metadata={
            "result.json": {
                "schema_ref": "material-learning-result@1.0",
                "media_type": "application/json",
            }
        },
        expected_file_sha256={"result.json": sha256_bytes(encoded)},
    )
    pointer = ArtifactMemberPointer(
        artifact_id=committed.artifact_id,
        artifact_revision_id=committed.revision_id,
        member_path="result.json",
        schema_ref="material-learning-result@1.0",
        media_type="application/json",
        sha256=sha256_bytes(encoded),
    )
    resolved = ResolvedMaterialTask(
        work.task_id,
        work.unit_key,
        actor,
        MaterialLearningAuthorizationRequest(
            workflow_id=workflow_id,
            step_run_id=step_id,
            plan_id="execplan_" + uuid4().hex,
            plan_sha256="sha256:" + "1" * 64,
            input_sha256=work.input_sha256,
        ),
        work,
        work_pointer,
        role,
        pointer,
        len(encoded),
    )
    monkeypatch.setattr(owner, "resolve_completed_material_task", lambda *args, **kwargs: resolved)
    publisher = ControlFileSetPublisher(
        creative_engine,
        Settings(staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root),
    )

    def service():
        value = owner.MaterialItemRegistrationService(
            creative_engine,
            content_pack_release_id=pack.content_pack_release_id,
            publisher=publisher,
            source_commit="a" * 40,
            settings=settings,
        )
        value.sources.reauthorize = Mock()
        return value

    return service, resolved


def test_registry_commit_interruption_reuses_exact_item_and_original_answer(
    creative_engine, registration_case
):
    create, resolved = registration_case
    first = create()
    register = first.registry.register

    def interrupted(command):
        register(command)
        raise RuntimeError("synthetic interruption after Registry commit")

    first.registry.register = interrupted
    with pytest.raises(RuntimeError, match="after Registry commit"):
        first.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, replay.item_revision_id)
        assert revision.metadata_json["source_kind"] == "EXTERNAL"
        assert revision.metadata_json["physical_pages"] == [31]
        assert (
            session.get(ItemRecord, replay.item_id).current_revision_id == replay.item_revision_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.registration_key == revision.registration_key)
            )
            == 1
        )
    assert replay.lineage.source_answer_mode == "EDITORIAL_SOURCE"


def test_concurrent_material_registry_writes_create_one_revision(
    creative_engine, registration_case
):
    create, resolved = registration_case
    barrier = Barrier(2)

    def submit(_):
        service = create()
        barrier.wait(timeout=10)
        return service.register_completed(
            task_id=resolved.task_id, operator_id=resolved.operator_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(submit, range(2))
    assert first.item_revision_id == second.item_revision_id and first.lineage == second.lineage
    assert sum((first.created, second.created)) == 1
