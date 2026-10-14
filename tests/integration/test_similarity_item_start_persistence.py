"""Actual disposable PostgreSQL item/plan/selector transactions; never live admission.

Catalog source Evidence, instruction-file metadata, operator authentication and
native QUERY selection are synthetic. No worker, model, operating corpus or NAS
is used. The existing independent DB owner/marker/schema/head guard is mandatory.
Synthetic setup/history is retained only in the disposable database.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.services import command_adapter as module
from eom_api.services.command_adapter import CommandAdapter, _workflow_request_from_api
from eom_api.services.item_similarity_start import SIMILARITY_PREPARATION_ACCEPTANCE_KEY
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import (
    publish_bundle_revision,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_bundle_revision,
    record_capacity_policy_revision,
    record_execution_preset_revision,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.settings import Settings
from eom_orchestrator.similarity_context_artifact import publish_similarity_context
from eom_workflow.control_plane import (
    ControlArtifactPointer,
    InstructionBundleManifest,
    WorkerCapacityPolicy,
)
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow.similarity_control import PreparedSimilarityPlan
from eom_workflow_runner.item_similarity_preparation import PreparedItemSimilarity
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import import_workflow_definition
from eom_workflow_runner.similarity_role_preparation import SIMILARITY_QUERY_CONTEXT_KEY
from psycopg.errors import ForeignKeyViolation, RaiseException, UniqueViolation
from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.test_control_plane_persistence import _seed_protocols_and_slots
from tests.integration.test_inference_transfer_plan_persistence import _synthetic_artifact
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_execution_fixtures import transfer_instruction
from tests.unit.item_similarity_start_fixtures import start_source

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
OWNER = "synthetic-similarity-item-start-persistence"


def controls(session, preset):
    """Real validated DB dependencies, deliberately not file/model availability proof."""
    _seed_protocols_and_slots(session)
    for protocol in ("workflow-role/1.24.0", TRANSFER_PAIR_PROTOCOL):
        ensure_protocol_version(session, protocol, role_schema_bundle_hash(protocol))
    body = transfer_instruction().model_dump(mode="json")
    body.update(
        bundle_id="instrbundle_" + uuid4().hex, bundle_revision_id="instrrev_" + uuid4().hex
    )
    for component in body["components"]:
        component["artifact"].update(
            artifact_id="artifact_" + uuid4().hex, artifact_revision_id="rev_" + uuid4().hex
        )
    instruction = InstructionBundleManifest.model_validate(seal(body, "content_sha256"))
    manifest = ControlArtifactPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        sha256=content_sha256(instruction.model_dump(mode="json")),
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
        logical_name="manifest.json",
    )
    for pointer in (manifest, *(component.artifact for component in instruction.components)):
        _synthetic_artifact(session, pointer)
    record_bundle_revision(
        session,
        bundle_key="synthetic-similarity-" + uuid4().hex,
        manifest_artifact=manifest,
        document=instruction.model_dump(mode="json"),
        created_by=OWNER,
    )
    publish_bundle_revision(
        session, bundle_id=instruction.bundle_id, bundle_revision_id=instruction.bundle_revision_id
    )
    roles = ("authoring", "review", "image", "item_management")
    capacity = WorkerCapacityPolicy.model_validate(
        seal(
            {
                "schema_version": "worker-capacity-policy/1.0",
                "capacity_policy_id": "capacity_" + uuid4().hex,
                "capacity_policy_revision_id": "capacityrev_" + uuid4().hex,
                "revision_number": 1,
                "state": "RELEASED",
                "max_configured_slots": 5,
                "max_active_codex": 3,
                "max_active_per_slot": 1,
                "max_active_gpu": 1,
                "max_active_knowledge_analysis": 1,
                "pools": [
                    {
                        "pool_key": role,
                        "roles": [role],
                        "slot_keys": [f"slot{index:02d}"],
                        "max_active": 1,
                    }
                    for index, role in enumerate(roles, 1)
                ],
                "created_at": instruction.created_at.isoformat().replace("+00:00", "Z"),
            },
            "content_sha256",
        )
    )
    record_capacity_policy_revision(
        session,
        policy_key="synthetic-similarity-" + uuid4().hex,
        document=capacity.model_dump(mode="json"),
        created_by=OWNER,
    )
    publish_capacity_policy_revision(
        session,
        capacity_policy_id=capacity.capacity_policy_id,
        capacity_policy_revision_id=capacity.capacity_policy_revision_id,
    )
    body = preset.model_dump(mode="json")
    body.update(
        preset_id="execpreset_" + uuid4().hex,
        preset_revision_id="execpresetrev_" + uuid4().hex,
        revision_number=1,
        capacity_policy_revision_id=capacity.capacity_policy_revision_id,
    )
    for policy in body["role_policies"]:
        policy.update(
            instruction_bundle={
                "bundle_id": instruction.bundle_id,
                "bundle_revision_id": instruction.bundle_revision_id,
                "manifest_artifact": manifest.model_dump(mode="json"),
                "manifest_sha256": manifest.sha256,
            },
            reference_bundle=None,
            worker_pool_key=policy["role"],
        )
    resolved = type(preset).model_validate(seal(body, "content_sha256"))
    key = "synthetic-similarity-" + uuid4().hex
    record_execution_preset_revision(
        session, preset_key=key, document=resolved.model_dump(mode="json"), created_by=OWNER
    )
    publish_execution_preset_revision(
        session, preset_id=resolved.preset_id, preset_revision_id=resolved.preset_revision_id
    )
    return key, resolved


@pytest.fixture
def item(guarded_engine: Engine, tmp_path, monkeypatch):
    assert guarded_engine.dialect.name == "postgresql"
    data = start_source(tmp_path, monkeypatch)
    sessions = build_session_factory(guarded_engine)
    with sessions.begin() as session:
        key, preset = controls(session, data.source.preset)
        definition, _ = import_workflow_definition(session, data.compiled)
    request = data.request.model_copy(update={"execution_preset_key": key})
    domain_request = _workflow_request_from_api(request)
    resolution = data.source.resolution.model_copy(
        update={
            "execution_preset_id": preset.preset_id,
            "execution_preset_revision_id": preset.preset_revision_id,
            "execution_preset_key": key,
            "execution_preset_content_sha256": preset.content_sha256,
        }
    )
    artifact_root, workspace = tmp_path / "pg-artifacts", tmp_path / "pg-workspace"
    artifact_root.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "pg-staging",
            nas_artifact_root=artifact_root,
            workspace_root=workspace,
        ),
    )
    context = data.source.value.case["context"]
    publication = publish_similarity_context(
        publisher,
        context=context,
        expected_request=context.request,
        idempotency_key="synthetic-pg-similarity-" + uuid4().hex,
        source_commit="a" * 40,
    )
    prepared = PreparedItemSimilarity(
        plan=PreparedSimilarityPlan(publication.delivery, context),
        publication=publication,
        workflow_request_sha256=content_sha256(domain_request.model_dump(mode="json")),
        evidence_result_sha256=data.source.evidence.result_sha256,
        preset_content_sha256=preset.content_sha256,
        resolution=resolution,
        query_selection=CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + uuid4().hex,
            workflow_request_sha256="sha256:" + "9" * 64,
            context_request_sha256=context.request.request_sha256,
        ),
        operator_id=data.actor.actor_id,
    )
    client = SimpleNamespace(
        create_item_production_evidence=Mock(return_value=data.source.evidence)
    )
    adapter = CommandAdapter(guarded_engine, catalog_application=client)
    adapter.catalog = SimpleNamespace(
        bind_request=Mock(side_effect=lambda *a, **kw: deepcopy(data.runtime))
    )
    adapter._resolve_past_exam_source_material_requirement = Mock(return_value=None)
    return SimpleNamespace(
        engine=guarded_engine,
        sessions=sessions,
        data=data,
        request=request,
        definition=definition,
        prepared=prepared,
        adapter=adapter,
        client=client,
        key="api:" + uuid4().hex * 2,
        publication=publication,
    )


def start(value):
    return value.adapter.start_workflow(
        value.request,
        value.data.actor,
        idempotency_key=value.key,
        prepared_similarity=value.prepared,
    )


def assert_rows(value, receipt):
    with value.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, receipt[1])
        record = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        )
        assert record.canonical_document["schema_version"] == "resolved-execution-plan/23.0"
        assert record.plan_sha256 == workflow.runtime_context["execution_plan"]["plan_sha256"]
        assert workflow.runtime_context[
            SIMILARITY_QUERY_CONTEXT_KEY
        ] == value.prepared.query_selection.model_dump(mode="json")
        assert workflow.runtime_context[SIMILARITY_PREPARATION_ACCEPTANCE_KEY].startswith("sha256:")
        steps = tuple(
            session.scalars(
                select(ResolvedExecutionPlanStepRecord).where(
                    ResolvedExecutionPlanStepRecord.plan_id == record.plan_id
                )
            )
        )
        assert len(steps) == 4
        assert {step.role for step in steps} == {"authoring", "review", "image", "item_management"}
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id
                )
            )
        )
        assert len(commands) == 1 and commands[0].command_id == receipt[0]
        return record.plan_id


def test_actual_postgres_first_plan_selector_steps_start_and_exact_replay(item):
    original = start(item)
    assert_rows(item, original)
    item.client.create_item_production_evidence.side_effect = AssertionError("no new source action")
    assert start(item) == original
    assert (
        item.adapter.start_workflow(item.request, item.data.actor, idempotency_key=item.key)
        == original
    )
    assert_rows(item, original)


def test_actual_postgres_concurrent_same_key_has_one_plan_and_command(item):
    barrier = Barrier(2)
    evidence = item.data.source.evidence

    def current(_command):
        barrier.wait(timeout=10)
        return evidence

    item.client.create_item_production_evidence.side_effect = current
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: start(item), range(2)))
    assert results[0] == results[1]
    assert_rows(item, results[0])
    with item.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == item.key)
            )
            == 1
        )


def test_actual_postgres_changed_preparation_conflicts_without_upgrading(item):
    original = start(item)
    item.prepared = replace(item.prepared, evidence_result_sha256="sha256:" + "0" * 64)
    with pytest.raises(ApiError) as caught:
        start(item)
    assert caught.value.error_code == "CONTROL_SIMILARITY_PREPARATION_CONFLICT"
    assert_rows(item, original)


def test_actual_postgres_competing_preparations_accept_only_one_binding(item):
    barrier = Barrier(2)
    evidence = item.data.source.evidence
    alternate = replace(
        item.prepared,
        query_selection=item.prepared.query_selection.model_copy(
            update={"workflow_id": "workflow_" + uuid4().hex}
        ),
    )

    def current(_command):
        barrier.wait(timeout=10)
        return evidence

    def attempt(prepared):
        try:
            return item.adapter.start_workflow(
                item.request,
                item.data.actor,
                idempotency_key=item.key,
                prepared_similarity=prepared,
            )
        except ApiError as exc:
            return exc.error_code

    item.client.create_item_production_evidence.side_effect = current
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, (item.prepared, alternate)))
    winners = [result for result in results if isinstance(result, tuple)]
    assert len(winners) == 1
    assert results.count("CONTROL_SIMILARITY_PREPARATION_CONFLICT") == 1
    winner = item.prepared if isinstance(results[0], tuple) else alternate
    item.prepared = winner
    assert_rows(item, winners[0])
    item.client.create_item_production_evidence.side_effect = AssertionError("metadata replay only")
    assert start(item) == winners[0]


def test_actual_postgres_enqueue_failure_rolls_back_new_plan_and_workflow(item, monkeypatch):
    reached = []

    def fail_after_plan(session, *, workflow_id, **_kwargs):
        plan_id = session.scalar(
            select(ResolvedExecutionPlanRecord.plan_id).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow_id
            )
        )
        assert plan_id is not None
        reached.append((workflow_id, plan_id))
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr(module, "enqueue_command", fail_after_plan)
    with pytest.raises(RuntimeError, match="synthetic enqueue failure"):
        start(item)
    with item.sessions() as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.idempotency_key == item.key
                )
            )
            is None
        )
        assert len(reached) == 1
        workflow_id, plan_id = reached[0]
        assert session.get(WorkflowInstanceRecord, workflow_id) is None
        assert session.get(ResolvedExecutionPlanRecord, plan_id) is None
        assert (
            session.scalar(
                select(ResolvedExecutionPlanStepRecord).where(
                    ResolvedExecutionPlanStepRecord.plan_id == plan_id
                )
            )
            is None
        )
        for model in (WorkflowCommandRecord, WorkflowEventRecord):
            assert session.scalar(select(model).where(model.workflow_id == workflow_id)) is None
    # Prior real context publication remains committed independently.
    with item.sessions() as session:
        pin = item.publication.delivery.context_member
        assert session.get(ArtifactRevisionRecord, pin.artifact_revision_id).approved


def test_actual_postgres_plan_immutability_unique_workflow_and_foreign_key(item):
    original = start(item)
    plan_id = assert_rows(item, original)
    with item.sessions.begin() as session:
        with pytest.raises(DBAPIError) as caught, session.begin_nested():
            session.execute(
                update(ResolvedExecutionPlanRecord)
                .where(ResolvedExecutionPlanRecord.plan_id == plan_id)
                .values(resolver_version="changed")
            )
        assert isinstance(caught.value.orig, RaiseException)
        row = session.get(ResolvedExecutionPlanRecord, plan_id)
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        with pytest.raises(IntegrityError) as caught, session.begin_nested():
            session.add(
                ResolvedExecutionPlanRecord(**(values | {"plan_id": "execplan_" + uuid4().hex}))
            )
            session.flush()
        assert isinstance(caught.value.orig, UniqueViolation)
        assert caught.value.orig.diag.constraint_name == "uq_execution_plan_workflow"
        with pytest.raises(IntegrityError) as caught, session.begin_nested():
            session.add(
                ResolvedExecutionPlanRecord(
                    **(
                        values
                        | {
                            "plan_id": "execplan_" + uuid4().hex,
                            "workflow_id": "workflow_" + uuid4().hex,
                        }
                    )
                )
            )
            session.flush()
        assert isinstance(caught.value.orig, ForeignKeyViolation)
    assert_rows(item, original)
