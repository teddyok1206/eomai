"""V2 Registry commits/replay on guarded PostgreSQL; completed worker port is synthetic.

This exercises the real released Pack, workflow/step, Artifact and Registry owners.
It does not claim Native pixel interpretation or live model/source authorization.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_V2_REF,
    MaterialItemLineageV2,
)
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.compiler import compile_definition
from eom_workflow.material_learning_request import (
    MaterialLearningWorkflowRequestV2,
    MaterialLearningWorkflowRequestV3,
)
from eom_workflow.models import MaterialLearningRoleResultV2, MaterialLearningRoleResultV3
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

from tests.integration.test_material_item_registration_storage import (
    ROOT,
)
from tests.integration.test_material_item_registration_storage import (
    controls as controls,
)
from tests.integration.test_material_item_registration_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_item_registration_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_item_registration_storage import (
    registration_case as registration_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def coverage_registration(creative_engine, registration_case, tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    return build_family_registration(
        creative_engine, registration_case, tmp_path, monkeypatch, **options
    )


def build_family_registration(
    creative_engine, registration_case, tmp_path, monkeypatch, *, family=2, points=2
):
    """Real Registry inputs around a synthetic admitted/completed worker port."""
    create, prior = registration_case
    exact = family == 3
    prototype = create()
    packs = ContentPackService(creative_engine, prototype.settings)
    pack = packs.import_source(
        ROOT / "content/packs/uploaded-material-item" / ("1.4.0" if exact else "1.2.0")
    )
    pack = packs.release(pack.content_pack_release_id, actor_id=prior.operator_id)
    request = (
        MaterialLearningWorkflowRequestV3(
            work_input=prior.work, native_visual_scope=None, native_printed_score=None
        )
        if exact
        else MaterialLearningWorkflowRequestV2(work_input=prior.work, native_visual_scope=None)
    )
    authorizer = SimpleNamespace(
        authorize_future_input=lambda *args, **kwargs: request.worker_request(),
        authorize_exact_score_input=lambda *args, **kwargs: request.worker_request(),
    )
    with Session(creative_engine) as session, session.begin():
        definition, _ = import_workflow_definition(
            session,
            compile_definition(
                ROOT / f"config/workflows/material-learning.v{family}.yaml", {"support"}
            ),
        )
        workflow, _ = create_workflow_instance(
            session,
            definition=definition,
            request=request,
            idempotency_key="synthetic-material-coverage:" + prior.task_id,
            actor_type="human",
            actor_id=prior.operator_id,
            material_learning_authorizer=authorizer,
        )
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_REGISTRY_STARTED",
            actor_type="human",
            actor_id=prior.operator_id,
            command_id=None,
        )
        step = create_step_run(
            session,
            workflow_id=workflow.workflow_id,
            step_key="learn",
            step_type="agent",
            worker_role="support",
            result_schema=f"material-learning-result@{family}.0",
            input_pointer_manifest={},
            max_attempts=1,
        )
        for state in (StepState.RUNNING, StepState.SUCCEEDED):
            transition_step(step, state)
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.COMPLETED,
            "SYNTHETIC_REGISTRY_COMPLETED",
            actor_type="human",
            actor_id=prior.operator_id,
            command_id=None,
        )
        selection = prior.selection.model_copy(
            update={"workflow_id": workflow.workflow_id, "step_run_id": step.step_run_id}
        )
    body = prior.role.model_dump(mode="json")
    body.update(
        protocol_version="workflow-role/1.40.0" if exact else "workflow-role/1.39.0",
        workflow_id=selection.workflow_id,
        step_run_id=selection.step_run_id,
    )
    body["output"]["native_visual_coverage"] = None
    if exact:
        extraction = body["output"]["learning_result"]
        extraction["schema_version"] = "material-learning-extraction-result/2.0"
        extraction["proposal"]["content"].update(
            schema_version="creative-source-item-draft/2.0",
            score={"state": "PRINTED", "points": points},
        )
    role = (MaterialLearningRoleResultV3 if exact else MaterialLearningRoleResultV2).model_validate(
        body
    )
    encoded = canonical_json_bytes(role.model_dump(mode="json"))
    path = tmp_path / "coverage-result.json"
    path.write_bytes(encoded)
    committed = prototype.artifacts.commit_file_set(
        files={"result.json": path},
        primary_file="result.json",
        artifact_type="workflow_support",
        idempotency_key="synthetic-material-coverage-result:" + uuid4().hex,
        request={"fixture": True},
        result={"fixture": True},
        file_metadata={
            "result.json": {
                "schema_ref": f"material-learning-result@{family}.0",
                "media_type": "application/json",
            }
        },
        expected_file_sha256={"result.json": sha256_bytes(encoded)},
    )
    resolved = replace(
        prior,
        selection=selection,
        role=role,
        result_pointer=ArtifactMemberPointer(
            artifact_id=committed.artifact_id,
            artifact_revision_id=committed.revision_id,
            member_path="result.json",
            schema_ref=f"material-learning-result@{family}.0",
            media_type="application/json",
            sha256=sha256_bytes(encoded),
        ),
        result_bytes=len(encoded),
    )
    monkeypatch.setattr(owner, "resolve_completed_material_task", lambda *args, **kwargs: resolved)

    def service():
        value = create()
        if exact:
            value.exact_score_pack_release_id = pack.content_pack_release_id
        else:
            value.coverage_pack_release_id = pack.content_pack_release_id
        return value

    return service, resolved


def test_coverage_concurrent_registration_replay_has_one_revision_and_exact_v2_lineage(
    creative_engine, coverage_registration
):
    create, resolved = coverage_registration
    barrier = Barrier(2)

    def register(_):
        service = create()
        barrier.wait(timeout=10)
        return service.register_completed(
            task_id=resolved.task_id, operator_id=resolved.operator_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(register, range(2))
    assert first.item_revision_id == second.item_revision_id
    assert sum((first.created, second.created)) == 1
    assert isinstance(first.lineage, MaterialItemLineageV2)
    assert first.lineage.role_result == resolved.result_pointer
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created and replay.lineage == first.lineage
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, replay.item_revision_id)
        assert revision.revision_state == "APPROVED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.registration_key == revision.registration_key)
            )
            == 1
        )
        source = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == replay.item_revision_id,
                ItemComponentRecord.component_type == "SOURCE_REFERENCE",
            )
        )
        assert source.schema_ref == MATERIAL_ITEM_LINEAGE_V2_REF


def test_coverage_registry_post_commit_interruption_resumes_without_duplicate(
    coverage_registration,
):
    create, resolved = coverage_registration
    service = create()
    register = service.registry.register

    def interrupted(command):
        register(command)
        raise RuntimeError("synthetic coverage post-commit interruption")

    service.registry.register = interrupted
    with pytest.raises(RuntimeError, match="post-commit interruption"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created and isinstance(replay.lineage, MaterialItemLineageV2)


def test_coverage_missing_pack_does_not_fall_back_or_write(creative_engine, coverage_registration):
    create, resolved = coverage_registration
    service = create()
    service.coverage_pack_release_id = None
    with Session(creative_engine) as session:
        before = session.scalar(select(func.count()).select_from(ItemRevisionRecord))
    with pytest.raises(ValueError, match="NOT_AUTHORIZED"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    with Session(creative_engine) as session:
        assert session.scalar(select(func.count()).select_from(ItemRevisionRecord)) == before
