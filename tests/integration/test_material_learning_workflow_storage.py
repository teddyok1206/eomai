"""The real Workflow owner persists only source-authorized material requests.

Authorization here is an explicit synthetic port, not live source access or a
worker execution. Rows/audit remain until guarded disposable DB cleanup.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedExecutionPlanV33
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from eom_workflow_runner import material_learning_start
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_step_run,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
    load_persisted_workflow_request,
    workflow_request_storage_document,
)
from eom_workflow_runner.state_machine import (
    StepState,
    WorkflowState,
    transition_step,
    transition_workflow,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_material_learning_contracts import work
from tests.unit.test_material_learning_role_contracts import material_plan

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]
OPERATOR = "operator_" + "a" * 32


@dataclass
class SyntheticMaterialSourceOwner:
    calls: int = 0
    deny_on_call: int | None = None

    def reauthorize(self, _session: Session, *, operator_id: str, work: MaterialLearningWork):
        self.calls += 1
        if operator_id != OPERATOR or self.calls == self.deny_on_call:
            raise ValueError("synthetic current source denial")
        return work


@pytest.fixture
def definition(creative_engine):
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v1.yaml", {"support"})
    with Session(creative_engine, expire_on_commit=False) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)
    return definition


def request():
    value = work()
    value["task_id"] = "materialtask_" + uuid4().hex
    value["input_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "input_sha256"}
    )
    return MaterialLearningWorkflowRequest(work_input=value)


def submit(session, definition, request, owner, key):
    return create_workflow_instance(
        session,
        definition=definition,
        request=request,
        idempotency_key=key,
        actor_type="human",
        actor_id=OPERATOR,
        material_learning_authorizer=owner,
    )


@pytest.fixture
def start_arguments(monkeypatch, definition):
    # Resolve-plan persistence/capacity has its own owner tests. This fixture
    # isolates real Workflow/READY/command atomicity with a declared plan port.
    def synthetic_plan(_session, **values):
        document = material_plan()
        document.update(
            workflow_id=values["workflow_id"],
            workflow_definition_sha256=values["workflow_definition_sha256"],
            work_input=values["work"].model_dump(mode="json"),
        )
        document["plan_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "plan_sha256"}
        )
        return ResolvedExecutionPlanV33.model_validate(document)

    monkeypatch.setattr(material_learning_start, "resolve_material_learning_plan", synthetic_plan)
    _logical, preset = _published_preset()
    return dict(
        definition=definition,
        work=request().work_input,
        operator_id=OPERATOR,
        expected_preset=ExecutionPresetRevision.model_validate(preset.canonical_document),
    )


def test_material_start_replay_has_one_ready_role_and_one_command(creative_engine, start_arguments):
    owner = SyntheticMaterialSourceOwner()
    key = "material-start-persistence-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        first = material_learning_start.submit_material_learning_workflow(
            session, **start_arguments, source_authorizer=owner, idempotency_key=key
        )
    with Session(creative_engine) as session, session.begin():
        replay = material_learning_start.submit_material_learning_workflow(
            session, **start_arguments, source_authorizer=owner, idempotency_key=key
        )
        assert replay.workflow_id == first.workflow_id and replay.command_id == first.command_id
        assert not replay.workflow_created
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == first.workflow_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )


def test_material_start_late_revocation_cannot_commit_orphan_role_or_command(
    creative_engine, start_arguments
):
    key = "material-late-start-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            material_learning_start.submit_material_learning_workflow(
                session,
                **start_arguments,
                source_authorizer=SyntheticMaterialSourceOwner(deny_on_call=4),
                idempotency_key=key,
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )


def test_concurrent_material_starts_reuse_original_command(creative_engine, start_arguments):
    barrier = Barrier(2)
    key = "material-concurrent-start-" + uuid4().hex

    def execute(_index):
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            return material_learning_start.submit_material_learning_workflow(
                session,
                **start_arguments,
                source_authorizer=SyntheticMaterialSourceOwner(),
                idempotency_key=key,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(execute, range(2)))
    assert len({value.workflow_id for value in results}) == 1
    assert len({value.command_id for value in results}) == 1
    assert sum(value.workflow_created for value in results) == 1


def test_start_replay_preserves_completed_terminal_and_advancement_history(
    creative_engine, start_arguments
):
    """A synthetic completed snapshot, using genuine lifecycle/command owners; no worker."""
    key = "material-terminal-replay-" + uuid4().hex
    owner = SyntheticMaterialSourceOwner()
    with Session(creative_engine) as session, session.begin():
        first = material_learning_start.submit_material_learning_workflow(
            session, **start_arguments, source_authorizer=owner, idempotency_key=key
        )
        transition_workflow(
            session,
            first.workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_STARTED",
            actor_type="human",
            actor_id=OPERATOR,
            command_id=None,
        )
        learn = session.get(WorkflowStepRunRecord, first.step_run_id)
        transition_step(learn, StepState.RUNNING)
        transition_step(learn, StepState.SUCCEEDED)
        terminal = create_step_run(
            session,
            workflow_id=first.workflow_id,
            step_key="complete",
            step_type="terminal",
            worker_role=None,
            result_schema=None,
            input_pointer_manifest={},
            max_attempts=1,
        )
        transition_step(terminal, StepState.RUNNING)
        transition_step(terminal, StepState.SUCCEEDED)
        terminal_step_id = terminal.step_run_id
        enqueue_command(
            session,
            workflow_id=first.workflow_id,
            command_type=CommandType.ADVANCE_WORKFLOW,
            payload={},
            actor_type="system",
            actor_id="synthetic",
            source="workflow_runner",
            idempotency_key="synthetic-advance:" + first.workflow_id,
        )
        transition_workflow(
            session,
            first.workflow_id,
            WorkflowState.COMPLETED,
            "SYNTHETIC_COMPLETED",
            actor_type="human",
            actor_id=OPERATOR,
            command_id=None,
        )
    with Session(creative_engine) as session, session.begin():
        replay = material_learning_start.submit_material_learning_workflow(
            session, **start_arguments, source_authorizer=owner, idempotency_key=key
        )
        assert replay.workflow_id == first.workflow_id and replay.command_id == first.command_id
        assert session.get(WorkflowStepRunRecord, first.step_run_id).state == "SUCCEEDED"
        assert session.get(WorkflowStepRunRecord, terminal_step_id).state == "SUCCEEDED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == first.workflow_id)
            )
            == 2
        )


def test_material_workflow_roundtrips_explicit_nulls_and_real_purpose(creative_engine, definition):
    selected = request()
    owner = SyntheticMaterialSourceOwner()
    key = "material-workflow-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        record, created = submit(session, definition, selected, owner, key)
        assert created and record.stage == "KNOWLEDGE_ANALYSIS"
        assert record.role_schema_version == "workflow-role/1.37.0"
        assert record.initial_request == workflow_request_storage_document(selected)
        assert record.initial_request["work_input"]["sources"][0]["office_catalog"] is None
        assert load_persisted_workflow_request(record.initial_request) == selected
        workflow_id = record.workflow_id
    with Session(creative_engine) as session, session.begin():
        replay, created = submit(session, definition, selected, owner, key)
        assert not created and replay.workflow_id == workflow_id
    assert owner.calls == 4


def test_missing_source_owner_cannot_submit_material_work(creative_engine, definition):
    with Session(creative_engine) as session, session.begin(), pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition,
            request=request(),
            idempotency_key="missing-" + uuid4().hex,
            actor_type="human",
            actor_id=OPERATOR,
        )


def test_late_source_revocation_rolls_back_even_when_caller_catches_then_commits(
    creative_engine, definition
):
    key = "late-revocation-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            submit(
                session, definition, request(), SyntheticMaterialSourceOwner(deny_on_call=2), key
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )


def test_replay_does_not_bypass_revoked_source(creative_engine, definition):
    key = "revoked-replay-" + uuid4().hex
    selected = request()
    with Session(creative_engine) as session, session.begin():
        record, _ = submit(session, definition, selected, SyntheticMaterialSourceOwner(), key)
        original = record.initial_request
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            submit(session, definition, selected, SyntheticMaterialSourceOwner(deny_on_call=1), key)
        preserved = session.scalar(
            select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
        )
        assert preserved.initial_request == original and preserved.state == "REQUESTED"


def test_concurrent_material_workflow_submit_has_one_exact_identity(creative_engine, definition):
    key = "material-race-" + uuid4().hex
    selected = request()
    barrier = Barrier(2)

    def invoke():
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            record, created = submit(
                session, definition, selected, SyntheticMaterialSourceOwner(), key
            )
            return record.workflow_id, created

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: invoke(), range(2)))
    assert len({value[0] for value in results}) == 1
    assert sum(value[1] for value in results) == 1


def test_technical_request_input_cannot_impersonate_worker_role(creative_engine, definition):
    with Session(creative_engine) as session, session.begin(), pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition,
            request=request(),
            idempotency_key="worker-actor-" + uuid4().hex,
            actor_type="worker",
            actor_id=OPERATOR,
            material_learning_authorizer=SyntheticMaterialSourceOwner(),
        )


def test_other_definition_cannot_adopt_material_request_or_authorizer(creative_engine, definition):
    original = definition.definition_key
    definition.definition_key = "external-item-learning"
    try:
        with Session(creative_engine) as session, session.begin(), pytest.raises(WorkflowError):
            submit(
                session,
                definition,
                request(),
                SyntheticMaterialSourceOwner(),
                "wrong-purpose-" + uuid4().hex,
            )
    finally:
        definition.definition_key = original
