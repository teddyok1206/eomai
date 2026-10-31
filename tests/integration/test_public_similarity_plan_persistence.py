"""Guarded disposable PG plan transactions; source/QUERY/model authority is synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    record_knowledge_backed_execution_plan,
)
from eom_workflow.control_plane import (
    ExecutionPresetRevisionV2,
    ResolvedExecutionPlanV19,
    WorkerRole,
)
from eom_workflow.public_similarity_control import (
    bind_public_similarity_execution_plan,
    parse_public_similarity_execution_plan,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_control_plane_persistence import _complete_control_plane
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.public_similarity_plan_fixtures import public_plan_case
from tests.unit.test_similarity_plan_execution_binding import creation_arguments

pytestmark = pytest.mark.integration


@pytest.fixture(params=(False, True))
def stored_case(guarded_engine: Engine, tmp_path, monkeypatch, request):
    # Normal seed records live exclusively in the marked temporary DB. No real
    # model validation, source access or workflow execution is represented here.
    value = public_plan_case(tmp_path, monkeypatch, ordinary=request.param, registered=True)
    suffix = uuid4().hex
    with Session(guarded_engine) as session, session.begin():
        old_plan_id, _, _ = _complete_control_plane(
            session, roles=(WorkerRole.AUTHORING, WorkerRole.REVIEW)
        )
        old_plan = session.get(ResolvedExecutionPlanRecord, old_plan_id)
        old_preset = session.get(ExecutionPresetRevisionRecord, old_plan.preset_revision_id)
        seed_policy = old_preset.canonical_document["role_policies"][0]
        document = value["base"].model_dump(mode="json")
        document.update(
            plan_id="execplan_" + suffix,
            workflow_id="workflow_" + suffix,
            preset_id="execpreset_" + suffix,
            preset_revision_id="execpresetrev_" + suffix,
            capacity_policy_revision_id=old_plan.capacity_policy_revision_id,
        )
        for step in document["steps"]:
            step.update(
                instruction_bundle=seed_policy["instruction_bundle"],
                reference_bundle=seed_policy["reference_bundle"],
                worker_pool_key=step["role"],
                general_knowledge_mode="DENIED",
            )
        value["base"] = ResolvedExecutionPlanV19.model_validate(seal(document, "plan_sha256"))
        _, preset = creation_arguments(value)
        preset_body = preset.model_dump(mode="json")
        preset_body["compatible_workflow_protocols"] = ["workflow-role/1.24.0"]
        preset = ExecutionPresetRevisionV2.model_validate(seal(preset_body, "content_sha256"))
        document["preset_sha256"] = preset.content_sha256
        value["base"] = ResolvedExecutionPlanV19.model_validate(seal(document, "plan_sha256"))
        # The policy is immutable nominal fixture input. Its publication/model
        # validation is outside these persistence tests, not a runtime bypass.
        session.add(
            ExecutionPresetRecord(
                preset_id=preset.preset_id,
                preset_key="public-plan-" + suffix,
                state="ACTIVE",
                created_by="disposable-public-plan",
            )
        )
        session.flush()
        session.add(
            ExecutionPresetRevisionRecord(
                preset_id=preset.preset_id,
                preset_revision_id=preset.preset_revision_id,
                revision_number=preset.revision_number,
                schema_version=preset.schema_version,
                state="RELEASED",
                display_name=preset.display_name,
                description=preset.description,
                capacity_policy_revision_id=preset.capacity_policy_revision_id,
                general_knowledge_policy=preset.general_knowledge_policy,
                compatible_workflow_protocols=list(preset.compatible_workflow_protocols),
                content_sha256=preset.content_sha256,
                canonical_document=preset.model_dump(mode="json"),
                created_by="disposable-public-plan",
            )
        )
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == "generic-item-development",
                WorkflowDefinitionRecord.definition_version == "1.16.0",
            )
        )
        if definition is None:
            definition = WorkflowDefinitionRecord(
                definition_id="wfdef_" + suffix,
                definition_key="generic-item-development",
                definition_version="1.16.0",
                schema_version="1.0",
                canonical_definition={"test_only": True},
                definition_hash=document["workflow_definition_sha256"],
                active=True,
                source_path="disposable/public-plan-" + suffix,
            )
            session.add(definition)
            session.flush()
        document["workflow_definition_sha256"] = definition.definition_hash
        value["base"] = ResolvedExecutionPlanV19.model_validate(seal(document, "plan_sha256"))
        session.add(
            WorkflowInstanceRecord(
                workflow_id=document["workflow_id"],
                definition_id=definition.definition_id,
                definition_key=definition.definition_key,
                definition_version=definition.definition_version,
                definition_hash=definition.definition_hash,
                protocol_version="1.1.0",
                role_schema_version="workflow-role/1.24.0",
                state="REQUESTED",
                stage="AUTHORING",
                current_step_key="authoring",
                request_payload={"test_only": True},
                initial_request={"test_only": True},
                runtime_context={},
                idempotency_key="disposable-public-plan-" + suffix,
                request_hash="sha256:" + suffix * 2,
                lock_version=1,
                rework_cycle_count=0,
                created_actor_type="system",
                created_actor_id="disposable-public-plan",
            )
        )
    arguments, _ = creation_arguments(value)
    plan = bind_public_similarity_execution_plan(value["base"], value["delivery"], value["context"])
    return SimpleNamespace(engine=guarded_engine, plan=plan, dependencies=arguments["dependencies"])


def persist(case):
    with Session(case.engine) as session, session.begin():
        row = record_knowledge_backed_execution_plan(
            session, document=case.plan.model_dump(mode="json"), dependencies=case.dependencies
        )
        return row.plan_id, row.plan_sha256


def test_public_plan_transaction_replay_preserves_exact_plan_and_step_rows(stored_case):
    case = stored_case
    original = case.plan.model_dump(mode="json")
    assert persist(case) == persist(case) == (case.plan.plan_id, case.plan.plan_sha256)
    with Session(case.engine) as session:
        row = session.get(ResolvedExecutionPlanRecord, case.plan.plan_id)
        assert row.canonical_document == original
        assert parse_public_similarity_execution_plan(row.canonical_document) == case.plan
        steps = tuple(
            session.scalars(
                select(ResolvedExecutionPlanStepRecord).where(
                    ResolvedExecutionPlanStepRecord.plan_id == case.plan.plan_id
                )
            )
        )
        assert {step.step_key for step in steps} == {step.step_key for step in case.plan.steps}
        assert all(not isinstance(value, bytes) for value in row.canonical_document.values())


def test_public_plan_interruption_rolls_back_plan_and_steps_then_exact_retry_succeeds(stored_case):
    case = stored_case
    with (
        pytest.raises(RuntimeError, match="synthetic interruption"),
        Session(case.engine) as session,
        session.begin(),
    ):
        record_knowledge_backed_execution_plan(
            session, document=case.plan.model_dump(mode="json"), dependencies=case.dependencies
        )
        raise RuntimeError("synthetic interruption after actual plan/step flush")
    with Session(case.engine) as session:
        assert session.get(ResolvedExecutionPlanRecord, case.plan.plan_id) is None
        assert not tuple(
            session.scalars(
                select(ResolvedExecutionPlanStepRecord).where(
                    ResolvedExecutionPlanStepRecord.plan_id == case.plan.plan_id
                )
            )
        )
    assert persist(case) == (case.plan.plan_id, case.plan.plan_sha256)


def test_public_plan_concurrent_storage_keeps_one_winner_and_official_replay(stored_case):
    case = stored_case
    barrier = Barrier(2)

    def create(_number):
        barrier.wait(timeout=30)
        try:
            return persist(case)
        except IntegrityError as error:
            # Direct concurrent storage exercises the unique constraint. Normal
            # API creation additionally serializes through its workflow boundary.
            assert error.orig.sqlstate == "23505"
            assert error.orig.diag.constraint_name in {
                "resolved_execution_plans_pkey",
                "uq_execution_plan_workflow",
            }
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(create, range(2)))
    assert (case.plan.plan_id, case.plan.plan_sha256) in results
    assert persist(case) == (case.plan.plan_id, case.plan.plan_sha256)
    with Session(case.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResolvedExecutionPlanRecord)
                .where(ResolvedExecutionPlanRecord.workflow_id == case.plan.workflow_id)
            )
            == 1
        )
        assert session.scalar(
            select(func.count())
            .select_from(ResolvedExecutionPlanStepRecord)
            .where(ResolvedExecutionPlanStepRecord.plan_id == case.plan.plan_id)
        ) == len(case.plan.steps)


def test_public_plan_stored_identity_cannot_acquire_another_delivery(stored_case):
    case = stored_case
    persist(case)
    document = case.plan.model_dump(mode="json")
    document["similarity_delivery"]["context_member"]["artifact_id"] = "artifact_" + "0" * 32
    document = seal(document, "plan_sha256")
    with (
        pytest.raises(ControlPlaneError) as error,
        Session(case.engine) as session,
        session.begin(),
    ):
        record_knowledge_backed_execution_plan(
            session, document=document, dependencies=case.dependencies
        )
    assert error.value.code == "CONTROL_PLAN_CONFLICT"
    with Session(case.engine) as session:
        assert session.get(
            ResolvedExecutionPlanRecord, case.plan.plan_id
        ).canonical_document == case.plan.model_dump(mode="json")
