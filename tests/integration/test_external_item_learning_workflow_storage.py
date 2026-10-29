"""Creative Workflow replay/concurrency in the guarded disposable owner DB.

The source authorizer is explicitly synthetic. These tests prove persistence,
not production source permission, page Artifact validity, or worker admission.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_workflow.control_plane import ResolvedExecutionPlanV27
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner import external_item_learning_preparation as preparation
from eom_workflow_runner import external_item_learning_recovery as recovery
from eom_workflow_runner import external_item_learning_start as start
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import create_workflow_instance
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_workflow_admission import (
    OPERATOR,
    OTHER_OPERATOR,
    _definition,
    _owner,
    _request,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _unique_request() -> WorkflowRequest:
    value = _request().model_dump(mode="json")
    work = value["external_item_learning_work"]
    work["request_id"] = "extlearnreq_" + uuid4().hex
    work["page_artifact"]["artifact_revision_id"] = "rev_" + uuid4().hex
    work["request_sha256"] = content_sha256(
        {key: item for key, item in work.items() if key != "request_sha256"}
    )
    return WorkflowRequest.model_validate(value)


def _seed(session: Session) -> WorkflowDefinitionRecord:
    candidate = _definition()
    existing = session.get(WorkflowDefinitionRecord, candidate.definition_id)
    if existing is None:
        session.add(candidate)
        session.flush()
        return candidate
    assert existing.canonical_definition == candidate.canonical_definition
    assert existing.definition_hash == candidate.definition_hash
    return existing


def _submit(session: Session, request: WorkflowRequest, key: str, actor: str = OPERATOR):
    return create_workflow_instance(
        session,
        definition=_seed(session),
        request=request,
        idempotency_key=key,
        actor_type="human",
        actor_id=actor,
        external_item_learning_authorizer=_owner(request),
    )


def test_creative_storage_replays_exact_input_and_separates_owners(creative_engine: Engine):
    with creative_engine.connect() as connection, connection.begin() as outer:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            request = _unique_request()
            key = "synthetic-creative-" + uuid4().hex
            first, created = _submit(session, request, key)
            assert created and first.stage == "KNOWLEDGE_ANALYSIS"
            same, created = _submit(session, request, key)
            assert not created and same.workflow_id == first.workflow_id
            active, created = _submit(session, request, key + "-other-key")
            assert not created and active.workflow_id == first.workflow_id
            other, created = _submit(session, request, key + "-other-owner", OTHER_OPERATOR)
            assert created and other.request_hash != first.request_hash
            assert other.created_actor_id == OTHER_OPERATOR
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEventRecord)
                    .where(WorkflowEventRecord.workflow_id == first.workflow_id)
                )
                == 1
            )
            session.expire_all()
            assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == (
                request.model_dump(mode="json", exclude_none=True)
            )
        outer.rollback()


def test_creative_late_authorization_rejection_discards_workflow(creative_engine: Engine):
    request = _unique_request()
    key = "synthetic-creative-revoked-" + uuid4().hex
    with Session(creative_engine) as session:
        owner = _owner(request)
        owner.reauthorize.side_effect = [request.external_item_learning_work.source, ValueError()]
        with pytest.raises(WorkflowError):
            create_workflow_instance(
                session,
                definition=_seed(session),
                request=request,
                idempotency_key=key,
                actor_type="human",
                actor_id=OPERATOR,
                external_item_learning_authorizer=owner,
            )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )


@pytest.mark.parametrize("different_keys", [False, True])
def test_concurrent_creative_submits_preserve_one_workflow_and_event(
    creative_engine: Engine, different_keys: bool
):
    request = _unique_request()
    key = "synthetic-creative-concurrent-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        _seed(session)
    barrier = Barrier(2)

    def submit(index):
        with Session(creative_engine) as session, session.begin():
            barrier.wait(timeout=10)
            workflow, created = _submit(
                session, request, key + str(index) if different_keys else key
            )
            return workflow.workflow_id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, range(2)))
    assert len({identity for identity, _created in results}) == 1
    assert sum(created for _identity, created in results) == 1
    with Session(creative_engine) as session:
        stored = session.get(WorkflowInstanceRecord, results[0][0])
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.request_hash == stored.request_hash)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == results[0][0])
            )
            == 1
        )


def _preparation_ports(monkeypatch):
    """Synthetic source/pages/policy: only real DB transaction behavior is claimed."""

    def resolve(_session, **kwargs):
        raw = _plan()
        raw["workflow_id"] = kwargs["workflow_id"]
        raw["workflow_definition_sha256"] = kwargs["workflow_definition_sha256"]
        raw["work_input"] = kwargs["work"].model_dump(mode="json")
        raw["plan_sha256"] = content_sha256(
            {key: value for key, value in raw.items() if key != "plan_sha256"}
        )
        return ResolvedExecutionPlanV27.model_validate(raw)

    monkeypatch.setattr(preparation, "resolve_external_item_learning_plan", resolve)
    monkeypatch.setattr(preparation, "read_external_item_learning_page_artifact", lambda *_: None)


def _failed_before_job(creative_engine, monkeypatch):
    """Synthetic failure fixture, never a mutation of production/historical data."""
    _preparation_ports(monkeypatch)
    request = _unique_request()
    with Session(creative_engine) as session, session.begin():
        prepared = preparation.prepare_external_item_learning_workflow(
            session,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            idempotency_key="synthetic-no-job-predecessor-" + uuid4().hex,
            source_authorizer=_owner(request),
            page_publisher=None,
        )
        workflow = session.get(WorkflowInstanceRecord, prepared.selection.workflow_id)
        workflow.state = workflow.stage = "FAILED"
        workflow.failure_code = "WORKFLOW_STEP_FAILED"
        step = session.get(WorkflowStepRunRecord, prepared.selection.step_run_id)
        step.state = "FAILED"
        step.error_code = "WORKFLOW_STEP_FAILED"
    preset = SimpleNamespace(
        preset_revision_id=_plan()["preset_revision_id"], content_sha256=_plan()["preset_sha256"]
    )

    def replay_plan(_record, *, workflow_id, step_key, request):
        assert step_key == "extract"
        return preparation.resolve_external_item_learning_plan(
            None,
            workflow_id=workflow_id,
            workflow_definition_sha256=_definition().definition_hash,
            work=request.work_input,
        )

    monkeypatch.setattr(recovery, "validate_external_item_learning_execution_plan", replay_plan)
    return request, prepared.selection, preset


def test_concurrent_no_job_recovery_prepares_one_successor_and_preserves_failure(
    creative_engine, monkeypatch
):
    request, predecessor, preset = _failed_before_job(creative_engine, monkeypatch)
    barrier = Barrier(2)

    def prepare(_index):
        with Session(creative_engine) as session, session.begin():
            barrier.wait(timeout=10)
            return recovery.prepare_unstarted_external_item_learning_recovery(
                session,
                predecessor_workflow_id=predecessor.workflow_id,
                definition=_seed(session),
                work=request.external_item_learning_work,
                operator_id=OPERATOR,
                source_authorizer=_owner(request),
                page_publisher=None,
                expected_preset=preset,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = tuple(pool.map(prepare, range(2)))
    assert rows[0].selection == rows[1].selection
    assert sum(row.workflow_created for row in rows) == 1
    successor_id = rows[0].selection.workflow_id
    assert successor_id != predecessor.workflow_id
    with Session(creative_engine) as session:
        old = session.get(WorkflowInstanceRecord, predecessor.workflow_id)
        old_step = session.get(WorkflowStepRunRecord, predecessor.step_run_id)
        assert old.state == old.stage == old_step.state == "FAILED"
        assert old_step.platform_job_id is None
        successor = recovery.resolve_external_item_learning_recovery(session, old)
        assert successor.workflow_id == successor_id and successor.state == "REQUESTED"
        assert successor.initial_request == old.initial_request
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == predecessor.workflow_id,
                    WorkflowEventRecord.event_type == recovery.RECOVERY_EVENT,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(
                    WorkflowCommandRecord.workflow_id.in_((predecessor.workflow_id, successor_id))
                )
            )
            == 0
        )


def test_no_job_recovery_late_rejection_leaves_only_the_original_failure(
    creative_engine, monkeypatch
):
    request, predecessor, preset = _failed_before_job(creative_engine, monkeypatch)
    owner = _owner(request)
    owner.reauthorize.side_effect = [request.external_item_learning_work.source] * 3 + [
        ValueError("synthetic source revoked")
    ]
    with pytest.raises(WorkflowError), Session(creative_engine) as session, session.begin():
        recovery.prepare_unstarted_external_item_learning_recovery(
            session,
            predecessor_workflow_id=predecessor.workflow_id,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            source_authorizer=owner,
            page_publisher=None,
            expected_preset=preset,
        )
    with Session(creative_engine) as session:
        old = session.get(WorkflowInstanceRecord, predecessor.workflow_id)
        assert old.state == "FAILED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.request_hash == old.request_hash)
            )
            == 1
        )
        assert recovery.resolve_external_item_learning_recovery(session, old) is old


def test_no_job_recovery_preserves_an_unrelated_active_equivalent_workflow(
    creative_engine, monkeypatch
):
    request, predecessor, preset = _failed_before_job(creative_engine, monkeypatch)
    with Session(creative_engine) as session, session.begin():
        active = preparation.prepare_external_item_learning_workflow(
            session,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            idempotency_key="synthetic-other-ready-" + uuid4().hex,
            source_authorizer=_owner(request),
            page_publisher=None,
        )
    with (
        pytest.raises(ValueError, match="SUCCESSOR_CONFLICT"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        recovery.prepare_unstarted_external_item_learning_recovery(
            session,
            predecessor_workflow_id=predecessor.workflow_id,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            source_authorizer=_owner(request),
            page_publisher=None,
            expected_preset=preset,
        )
    with Session(creative_engine) as session:
        untouched = session.get(WorkflowInstanceRecord, active.selection.workflow_id)
        assert untouched.state == "REQUESTED"
        assert "creative_preexecution_recovery" not in untouched.runtime_context
        old = session.get(WorkflowInstanceRecord, predecessor.workflow_id)
        assert old.state == "FAILED"
        assert recovery.resolve_external_item_learning_recovery(session, old) is old


@pytest.mark.parametrize("different_keys", [False, True])
def test_concurrent_preparation_saves_one_ready_step_and_no_command(
    creative_engine: Engine, monkeypatch, different_keys: bool
):
    _preparation_ports(monkeypatch)
    request = _unique_request()
    key = "synthetic-creative-prepare-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        _seed(session)
    barrier = Barrier(2)

    def prepare(index):
        with Session(creative_engine) as session, session.begin():
            barrier.wait(timeout=10)
            return preparation.prepare_external_item_learning_workflow(
                session,
                definition=_seed(session),
                work=request.external_item_learning_work,
                operator_id=OPERATOR,
                idempotency_key=key + str(index) if different_keys else key,
                source_authorizer=_owner(request),
                page_publisher=None,  # synthetic page read above; never runtime authority
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(prepare, range(2)))
    assert results[0].selection == results[1].selection
    assert sum(result.workflow_created for result in results) == 1
    assert sum(result.step_created for result in results) == 1
    workflow_id = results[0].selection.workflow_id
    with Session(creative_engine) as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        assert workflow.state == "REQUESTED" and workflow.stage == "KNOWLEDGE_ANALYSIS"
        step = session.get(WorkflowStepRunRecord, results[0].selection.step_run_id)
        assert step.state == "READY" and step.platform_job_id is None
        for model, count in (
            (WorkflowCommandRecord, 0),
            (WorkflowStepRunRecord, 1),
            (WorkflowEventRecord, 2),
        ):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.workflow_id == workflow_id)
                )
                == count
            )


def test_preparation_late_source_rejection_rolls_back_ready_step_and_event(
    creative_engine: Engine, monkeypatch
):
    _preparation_ports(monkeypatch)
    request = _unique_request()
    key = "synthetic-creative-prepare-revoked-" + uuid4().hex
    owner = _owner(request)
    owner.reauthorize.side_effect = [request.external_item_learning_work.source] * 3 + [
        ValueError()
    ]
    with pytest.raises(WorkflowError), Session(creative_engine) as session, session.begin():
        preparation.prepare_external_item_learning_workflow(
            session,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            idempotency_key=key,
            source_authorizer=owner,
            page_publisher=None,
        )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )


def _prepared_start(creative_engine, monkeypatch):
    _preparation_ports(monkeypatch)
    monkeypatch.setattr(start, "read_external_item_learning_page_artifact", lambda *_: None)

    def plan(_record, *, workflow_id, step_key, request):
        assert step_key == "extract"
        return preparation.resolve_external_item_learning_plan(
            None,
            workflow_id=workflow_id,
            workflow_definition_sha256=_definition().definition_hash,
            work=request.work_input,
        )

    monkeypatch.setattr(start, "validate_external_item_learning_execution_plan", plan)
    request = _unique_request()
    with Session(creative_engine) as session, session.begin():
        prepared = preparation.prepare_external_item_learning_workflow(
            session,
            definition=_seed(session),
            work=request.external_item_learning_work,
            operator_id=OPERATOR,
            idempotency_key="synthetic-creative-start-" + uuid4().hex,
            source_authorizer=_owner(request),
            page_publisher=None,
        )
    return request, prepared.selection


def test_concurrent_prepared_starts_create_one_original_command(creative_engine, monkeypatch):
    request, selection = _prepared_start(creative_engine, monkeypatch)
    barrier = Barrier(2)

    def submit(_index):
        with Session(creative_engine) as session, session.begin():
            barrier.wait(timeout=10)
            return start.start_prepared_external_item_learning(
                session,
                selection=selection,
                operator_id=OPERATOR,
                source_authorizer=_owner(request),
                page_publisher=None,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, range(2)))
    assert len({r.command_id for r in results}) == 1
    assert sum(r.command_created for r in results) == 1
    with Session(creative_engine) as session:
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == selection.workflow_id
                )
            )
        )
        assert len(commands) == 1
        assert commands[0].state == "PENDING" and commands[0].attempts == 0
        assert session.get(WorkflowInstanceRecord, selection.workflow_id).state == "REQUESTED"
        assert session.get(WorkflowStepRunRecord, selection.step_run_id).state == "READY"


@pytest.mark.parametrize("failure", ["revoked", "interrupted"])
def test_prepared_start_failure_rolls_back_command_not_original_ready_role(
    creative_engine, monkeypatch, failure
):
    request, selection = _prepared_start(creative_engine, monkeypatch)
    owner = _owner(request)
    if failure == "revoked":
        owner.reauthorize.side_effect = [request.external_item_learning_work.source, ValueError()]
    with (
        pytest.raises((WorkflowError, RuntimeError)),
        Session(creative_engine) as session,
        session.begin(),
    ):
        start.start_prepared_external_item_learning(
            session,
            selection=selection,
            operator_id=OPERATOR,
            source_authorizer=owner,
            page_publisher=None,
        )
        raise RuntimeError("synthetic interruption before commit")
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == selection.workflow_id)
            )
            == 0
        )
        assert session.get(WorkflowInstanceRecord, selection.workflow_id).state == "REQUESTED"
        assert session.get(WorkflowStepRunRecord, selection.step_run_id).state == "READY"
