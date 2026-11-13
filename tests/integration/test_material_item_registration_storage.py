"""Real Registry/Artifact commit, replay and interruption with a declared synthetic result port.

Completed worker/source authorization is tested by separate role/page owners.
This suite does not claim source rights, model execution or scientific validation.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisWorkerProposal,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_learning import MaterialExtractionWork
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_task_results import ResolvedMaterialTask
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_catalog_service.solution_evidence_resolution import (
    accepted_public_solution_successor_predicate,
    resolve_registered_solution_evidence_by_base_run,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.material_learning_controls import release_material_learning_controls
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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tests.integration import test_knowledge_analysis_service as knowledge
from tests.integration import test_registered_item_solution_application as solutions
from tests.integration.test_material_learning_controls_storage import material_control_arguments
from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls
from tests.unit.test_material_learning_contracts import extraction_result, extraction_work, rehash
from tests.unit.test_material_learning_role_contracts import worker_input

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registration_case(creative_engine, material_intake, controls, tmp_path, monkeypatch):
    actor, settings, _, _ = material_intake
    settings = replace(settings, nas_artifact_root=controls[1].nas_artifact_root)
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
    # This fixture deliberately substitutes the completed-worker/source owner.
    # It is a V1 Registry transaction fixture, not native intake authorization.
    monkeypatch.setattr(owner, "resolve_native_material_registration_binding", lambda *a, **k: None)
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


@pytest.mark.parametrize("material_purpose", [False, True])
def test_uploaded_item_uses_real_registered_solution_and_common_embedding_projection(
    creative_engine, registration_case, tmp_path, controls, material_purpose
):
    """Real source/analysis/report chain; only the worker response is synthetic."""
    create, resolved = registration_case
    owner = create()
    item = owner.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    analyses = KnowledgeAnalysisApplicationService(creative_engine, owner.settings)
    command = CreateKnowledgeAnalysisCommand.model_validate(
        dict(
            source=dict(
                source_kind="APPROVED_ITEM_REVISION",
                source_class="APPROVED_ITEM",
                item_revision_id=item.item_revision_id,
            ),
            preset_key="knowledge-analysis",
            general_knowledge_mode="DISABLED",
            risk_policy_revision_id=knowledge.POLICY_ID,
            requested_by=resolved.operator_id,
            idempotency_key="material-registered-base:" + uuid4().hex,
        )
    )
    base = analyses.create(command)
    with analyses.sessions() as session:
        request = KnowledgeAnalysisRequestV2.model_validate(
            session.get(KnowledgeAnalysisRunRecord, base.analysis_run_id).canonical_request
        )
    pointer = request.source.artifact_member
    assert pointer.schema_ref == "eom.assessment.item-content/1.0"
    content = json.loads(
        owner.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
    )
    # Reuse the registered-solution fixture's exact reference node identities,
    # but pin anchors to the general Item's real fields, not editorial V3 paths.
    proposal = solutions._base_proposal(
        request,
        {
            "stem": json.dumps(content["body"], ensure_ascii=False),
            "explanations": {"correct_answer": content["solution"]},
        },
    ).model_dump(mode="json")
    proposal["anchors"][0]["locator"] = "/body"
    proposal["anchors"][0]["excerpt_sha256"] = content_sha256(content["body"])
    proposal["anchors"][1]["locator"] = "/solution"
    # Exercise the real canonical writer's .000000Z representation, which
    # differs from Pydantic's JSON display but not from the typed UTC instant.
    proposal["completed_at"] = "2026-11-06T07:22:50.000000Z"
    knowledge._complete_proposal(
        creative_engine,
        owner.settings,
        run_id=base.analysis_run_id,
        staging_root=tmp_path / "material-base-response",
        proposal_override=KnowledgeAnalysisWorkerProposal.model_validate(proposal),
    )
    base = analyses.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=base.analysis_run_id, requested_by=resolved.operator_id
        )
    )
    assert base.state == "ACCEPTED"
    solution_command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id=base.analysis_run_id,
        requested_by=resolved.operator_id,
        idempotency_key="material-registered-solution:" + uuid4().hex,
    )
    if material_purpose:
        publisher = ControlArtifactPublisher(
            creative_engine,
            Settings(
                staging_root=owner.settings.staging_root,
                nas_artifact_root=owner.settings.nas_artifact_root,
            ),
        )
        presets = release_material_learning_controls(
            build_session_factory(creative_engine),
            publisher,
            **material_control_arguments(controls[2]),
        )

        def create_solution():
            return analyses.create_material_solution_with_pinned_preset(
                solution_command,
                preset_id=presets.solution.preset_id,
                preset_revision_id=presets.solution.preset_revision_id,
            )
    else:

        def create_solution():
            return analyses.create_solution(solution_command)

    solution = create_solution()
    assert create_solution() == solution
    solutions._complete_solution(
        creative_engine,
        owner.settings,
        solution.analysis_run_id,
        tmp_path / "material-solution-response",
    )
    solution = analyses.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=solution.analysis_run_id, requested_by=resolved.operator_id
        )
    )
    assert solution.state == "ACCEPTED"
    assert create_solution() == solution
    with analyses.sessions() as session:
        evidence = resolve_registered_solution_evidence_by_base_run(
            session, owner.artifacts, base_analysis_run_ids=(base.analysis_run_id,)
        )[base.analysis_run_id]
    assert evidence.source.item_revision_id == item.item_revision_id
    assert evidence.pointer.solution_analysis_run_id == solution.analysis_run_id
    projected = project_public_solution_text(evidence.report)
    assert projected.status == "AVAILABLE" and projected.text
    assert projected == project_public_solution_text(evidence.report)
    # The INDEX/QUERY reader requires the accepted/receipt Artifact metadata to
    # be captured in the same transaction. Exercise its actual bulk predicate
    # and strict physical reader, not only CatalogArtifactService's direct read.
    with analyses.sessions.begin() as session:
        dependencies = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord).where(
                    or_(
                        KnowledgeAnalysisRunRecord.analysis_run_id == base.analysis_run_id,
                        accepted_public_solution_successor_predicate((base.analysis_run_id,)),
                    )
                )
            )
        )
        assert {row.analysis_run_id for row in dependencies} == {
            base.analysis_run_id,
            solution.analysis_run_id,
        }
        reader = PinnedArtifactReadContext(session, owner.settings)
        reader.prefetch(
            tuple(
                sorted(
                    {
                        identity
                        for row in dependencies
                        for identity in (
                            (
                                row.accepted_result_artifact_id,
                                row.accepted_result_artifact_revision_id,
                            ),
                            (row.proposal_artifact_id, row.proposal_artifact_revision_id),
                        )
                    }
                )
            )
        )
        indexed_evidence = resolve_registered_solution_evidence_by_base_run(
            session, reader, base_analysis_run_ids=(base.analysis_run_id,)
        )[base.analysis_run_id]
        assert project_public_solution_text(indexed_evidence.report) == projected
        reader.revalidate_provenance()
    assert (
        not create()
        .register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
        .created
    )
