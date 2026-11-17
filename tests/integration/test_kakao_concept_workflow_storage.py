"""Guarded disposable Workflow transactions; synthetic source/plan ports, no model or NAS."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import uuid4

import pytest
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import KakaoConceptWork, KakaoConceptWorkflowRequest
from eom_workflow_runner import kakao_concept_start
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandType,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
    load_persisted_workflow_request,
    workflow_request_storage_document,
)
from eom_workflow_runner.state_machine import WorkflowState, transition_workflow
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_kakao_concept_contracts import ROOT, plan_request
from tests.unit.test_kakao_concept_workflow_contracts import plan_value, rehash, work_value

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
OPERATOR = "operator_" + "a" * 32


@dataclass
class SyntheticConceptSourceOwner:
    calls: int = 0
    deny_on_call: int | None = None

    def reauthorize(self, _session: Session, *, operator_id: str, work: KakaoConceptWork):
        self.calls += 1
        if operator_id != OPERATOR or self.calls == self.deny_on_call:
            raise ValueError("synthetic current source denial")
        return work


@pytest.fixture
def definition(creative_engine):
    compiled = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    with Session(creative_engine, expire_on_commit=False) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)
    return definition


def request():
    value = plan_request().model_copy(update={"task_id": "kakaoconcepttask_" + uuid4().hex})
    return KakaoConceptWorkflowRequest(work_input=work_value(value))


def submit(session, definition, selected, owner, key):
    return create_workflow_instance(
        session,
        definition=definition,
        request=selected,
        idempotency_key=key,
        actor_type="human",
        actor_id=OPERATOR,
        kakao_concept_authorizer=owner,
    )


@pytest.fixture
def start_arguments(monkeypatch, definition):
    # This isolates the genuine Workflow/command transaction. Source, released
    # preset/capacity and plan persistence must be verified independently.
    def synthetic_plan(_session, **values):
        document = plan_value()
        document.update(
            workflow_id=values["workflow_id"],
            workflow_definition_sha256=values["workflow_definition_sha256"],
            work_input=values["work"].model_dump(mode="json"),
        )
        return KakaoConceptExecutionPlan.model_validate(rehash(document))

    monkeypatch.setattr(kakao_concept_start, "resolve_kakao_concept_plan", synthetic_plan)
    _, preset = _published_preset()
    return dict(
        definition=definition,
        work=request().work_input,
        operator_id=OPERATOR,
        expected_preset=ExecutionPresetRevision.model_validate(preset.canonical_document),
    )


def test_concept_work_roundtrips_without_private_question_bytes(creative_engine, definition):
    selected = request()
    owner = SyntheticConceptSourceOwner()
    key = "kakao-concept-roundtrip-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        record, created = submit(session, definition, selected, owner, key)
        assert created and record.stage == "KNOWLEDGE_ANALYSIS"
        assert record.role_schema_version == "workflow-role/1.41.0"
        assert record.initial_request == workflow_request_storage_document(selected)
        assert "student" not in record.initial_request["work_input"]
        assert load_persisted_workflow_request(record.initial_request) == selected
        identity = record.workflow_id
    with Session(creative_engine) as session, session.begin():
        replay, created = submit(session, definition, selected, owner, key)
        assert not created and replay.workflow_id == identity
    assert owner.calls == 4


def test_missing_source_owner_fails_before_persistence(creative_engine, definition):
    with Session(creative_engine) as session, session.begin(), pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition,
            request=request(),
            idempotency_key="kakao-missing-" + uuid4().hex,
            actor_type="human",
            actor_id=OPERATOR,
        )


@pytest.mark.parametrize("call", [1, 2])
def test_source_denial_rolls_back_even_if_caller_catches_and_commits(
    creative_engine, definition, call
):
    key = "kakao-revoked-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            submit(
                session, definition, request(), SyntheticConceptSourceOwner(deny_on_call=call), key
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )


def test_one_command_survives_reconstruction_and_idempotent_replay(
    creative_engine, start_arguments
):
    key = "kakao-start-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        first = kakao_concept_start.submit_kakao_concept_workflow(
            session,
            **start_arguments,
            source_authorizer=SyntheticConceptSourceOwner(),
            idempotency_key=key,
        )
    with Session(creative_engine) as session, session.begin():
        replay = kakao_concept_start.submit_kakao_concept_workflow(
            session,
            **start_arguments,
            source_authorizer=SyntheticConceptSourceOwner(),
            idempotency_key=key,
        )
        assert replay.workflow_id == first.workflow_id
        assert replay.command_id == first.command_id and not replay.workflow_created
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )


def test_concurrent_submissions_do_not_create_duplicate_workflows_or_commands(
    creative_engine, start_arguments
):
    barrier = Barrier(2)
    key = "kakao-concurrent-" + uuid4().hex

    def execute(_):
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            return kakao_concept_start.submit_kakao_concept_workflow(
                session,
                **start_arguments,
                source_authorizer=SyntheticConceptSourceOwner(),
                idempotency_key=key,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(execute, range(2)))
    assert len({result.workflow_id for result in results}) == 1
    assert len({result.command_id for result in results}) == 1
    assert sum(result.workflow_created for result in results) == 1


def test_late_source_denial_leaves_no_orphan_command(creative_engine, start_arguments):
    key = "kakao-late-start-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            kakao_concept_start.submit_kakao_concept_workflow(
                session,
                **start_arguments,
                source_authorizer=SyntheticConceptSourceOwner(deny_on_call=4),
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


def test_failed_history_is_preserved_and_not_resubmitted_as_success(
    creative_engine, start_arguments
):
    key = "kakao-failed-replay-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        first = kakao_concept_start.submit_kakao_concept_workflow(
            session,
            **start_arguments,
            source_authorizer=SyntheticConceptSourceOwner(),
            idempotency_key=key,
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
        transition_workflow(
            session,
            first.workflow_id,
            WorkflowState.FAILED,
            "SYNTHETIC_FAILED",
            actor_type="human",
            actor_id=OPERATOR,
            command_id=None,
        )
    with Session(creative_engine) as session, session.begin():
        replay = kakao_concept_start.submit_kakao_concept_workflow(
            session,
            **start_arguments,
            source_authorizer=SyntheticConceptSourceOwner(),
            idempotency_key=key,
        )
        assert replay.workflow_id == first.workflow_id and replay.command_id == first.command_id
        assert session.get(WorkflowInstanceRecord, first.workflow_id).state == "FAILED"


def test_unrelated_start_command_is_not_adopted(creative_engine, start_arguments):
    selected = KakaoConceptWorkflowRequest(work_input=start_arguments["work"])
    key = "kakao-other-history-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        record, _ = submit(
            session, start_arguments["definition"], selected, SyntheticConceptSourceOwner(), key
        )
        enqueue_command(
            session,
            workflow_id=record.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id=OPERATOR,
            source="unrelated",
            idempotency_key="other:" + record.workflow_id,
        )
    with (
        Session(creative_engine) as session,
        session.begin(),
        pytest.raises(ValueError, match="unrelated command history"),
    ):
        kakao_concept_start.submit_kakao_concept_workflow(
            session,
            **start_arguments,
            source_authorizer=SyntheticConceptSourceOwner(),
            idempotency_key=key,
        )
