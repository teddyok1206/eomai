from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import yaml
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow import WorkflowRequest, compile_definition, compile_definition_data
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    admitted_workflow_definition,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
    workflow_business_fingerprint,
)
from eom_workflow_runner.state_machine import (
    WorkflowStage,
    WorkflowState,
    transition_stage,
    transition_workflow,
)
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration
ROLE_SLOTS = {"authoring", "review", "image", "item_management", "support"}

ADMITTED_DEFINITION_PATHS = (
    "config/workflows/generic-item-development.v1.7.yaml",
    "config/workflows/knowledge-analysis.v1.yaml",
    "config/workflows/knowledge-analysis.v4.yaml",
    "config/workflows/knowledge-analysis.v8.yaml",
    "config/workflows/legacy-item-extraction.v1.yaml",
    "config/workflows/legacy-item-editorial-compatibility.v1.yaml",
)


def _definition(session: Session, suffix: str) -> WorkflowDefinitionRecord:
    raw = yaml.safe_load(
        Path("config/workflows/generic-item-development.v1.yaml").read_text(encoding="utf-8")
    )
    raw["definition_key"] = f"submission-test-{suffix[:16]}"
    compiled = compile_definition_data(raw, "test-workflow-submission", ROLE_SLOTS)
    definition, created = import_workflow_definition(session, compiled)
    assert created
    return definition


def test_admission_policy_preserves_historical_definition_and_instance(
    db_session: Session,
) -> None:
    for path in ADMITTED_DEFINITION_PATHS:
        import_workflow_definition(
            db_session,
            compile_definition(Path(path), ROLE_SLOTS),
        )
    historical, _ = import_workflow_definition(
        db_session,
        compile_definition(
            Path("config/workflows/generic-item-development.v1.yaml"),
            ROLE_SLOTS,
        ),
    )
    historical.active = True  # represent the pre-convergence production registry
    workflow, created = create_workflow_instance(
        db_session,
        definition=historical,
        request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip"),
        idempotency_key=f"historical-admission:{uuid4().hex}",
        actor_type="human",
        actor_id="author_01",
    )
    assert created

    assert (
        admitted_workflow_definition(
            db_session,
            definition_key=historical.definition_key,
            definition_version=historical.definition_version,
        )
        is None
    )
    current = admitted_workflow_definition(
        db_session,
        definition_key="generic-item-development",
        definition_version="1.7.0",
    )
    assert current is not None
    assert historical.active is True
    assert workflow.definition_id == historical.definition_id
    assert workflow.definition_version == "1.0.0"


def _submit(
    session: Session,
    definition: WorkflowDefinitionRecord,
    request: WorkflowRequest,
    key: str,
) -> tuple[WorkflowInstanceRecord, bool, str | None]:
    workflow, created = create_workflow_instance(
        session,
        definition=definition,
        request=request,
        idempotency_key=key,
        actor_type="human",
        actor_id="author_01",
    )
    command_id = None
    if created:
        command, command_created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id="author_01",
            source="test",
            idempotency_key=f"start:{workflow.workflow_id}",
        )
        assert command_created
        command_id = command.command_id
    return workflow, created, command_id


def _terminate(session: Session, workflow_id: str, target: WorkflowState) -> None:
    workflow = session.get(WorkflowInstanceRecord, workflow_id)
    assert workflow is not None
    if target is WorkflowState.FAILED:
        workflow.failure_code = "TEST_INFRASTRUCTURE_FAILURE"
        workflow.failure_summary = "test workflow occurrence failed"
    transition_stage(
        session,
        workflow_id,
        WorkflowStage(target.value),
        workflow.current_step_key,
        f"WORKFLOW_{target.value}_STAGE_ENTERED",
        actor_type="system",
        actor_id="test",
        command_id=None,
    )
    transition_workflow(
        session,
        workflow_id,
        target,
        f"WORKFLOW_{target.value}",
        actor_type="system",
        actor_id="test",
        command_id=None,
        step_key=workflow.current_step_key,
    )


def _cleanup(engine: Engine, definition_id: str) -> None:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        session.execute(
            delete(WorkflowInstanceRecord).where(
                WorkflowInstanceRecord.definition_id == definition_id
            )
        )
        # Released definitions remain immutable until the guarded disposable
        # database is removed as a whole.


@pytest.mark.parametrize("terminal", (WorkflowState.FAILED, WorkflowState.CANCELLED))
def test_terminal_unsuccessful_occurrence_permits_new_submission_and_is_preserved(
    integration_engine: Engine, terminal: WorkflowState
) -> None:
    sessions = build_session_factory(integration_engine)
    suffix = uuid4().hex
    request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    definition_id = ""
    try:
        with transaction(sessions) as session:
            created_definition = _definition(session, suffix)
            definition_id = created_definition.definition_id
            first, created, first_command_id = _submit(
                session, created_definition, request, f"submission-old-{suffix}"
            )
            assert created and first_command_id is not None
            first_id = first.workflow_id
            request_hash = first.request_hash
        with transaction(sessions) as session:
            _terminate(session, first_id, terminal)
        with sessions() as session:
            old = session.get(WorkflowInstanceRecord, first_id)
            assert old is not None
            old_snapshot = (
                old.state,
                old.stage,
                old.failure_code,
                old.failure_summary,
                old.created_at,
                old.completed_at,
                old.request_hash,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEventRecord)
                    .where(WorkflowEventRecord.workflow_id == first_id)
                ),
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowCommandRecord)
                    .where(WorkflowCommandRecord.workflow_id == first_id)
                ),
            )
        with transaction(sessions) as session:
            stored_definition = session.get(WorkflowDefinitionRecord, definition_id)
            assert stored_definition is not None
            second, second_created, second_command_id = _submit(
                session, stored_definition, request, f"submission-new-{suffix}"
            )
            assert second_created and second.workflow_id != first_id
            assert second_command_id is not None
            assert second.state == WorkflowState.REQUESTED.value
            assert second.request_hash == request_hash
            second_id = second.workflow_id
        with transaction(sessions) as session:
            stored_definition = session.get(WorkflowDefinitionRecord, definition_id)
            assert stored_definition is not None
            replay, replay_created, _ = _submit(
                session, stored_definition, request, f"submission-new-{suffix}"
            )
            assert not replay_created and replay.workflow_id == second_id
        with sessions() as session:
            old = session.get(WorkflowInstanceRecord, first_id)
            new_command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == second_id,
                    WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
                )
            )
            assert old is not None and new_command is not None
            assert old_snapshot == (
                old.state,
                old.stage,
                old.failure_code,
                old.failure_summary,
                old.created_at,
                old.completed_at,
                old.request_hash,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEventRecord)
                    .where(WorkflowEventRecord.workflow_id == first_id)
                ),
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowCommandRecord)
                    .where(WorkflowCommandRecord.workflow_id == first_id)
                ),
            )
            assert new_command.attempts == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowInstanceRecord)
                    .where(WorkflowInstanceRecord.request_hash == request_hash)
                )
                == 2
            )
    finally:
        if definition_id:
            _cleanup(integration_engine, definition_id)


def test_active_and_completed_equivalents_preserve_v0_deduplication(
    integration_engine: Engine,
) -> None:
    sessions = build_session_factory(integration_engine)
    suffix = uuid4().hex
    request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required")
    definition_id = ""
    try:
        with transaction(sessions) as session:
            created_definition = _definition(session, suffix)
            definition_id = created_definition.definition_id
            first, created, _ = _submit(
                session, created_definition, request, f"active-old-{suffix}"
            )
            assert created
            first_id = first.workflow_id
            active, active_created, _ = _submit(
                session, created_definition, request, f"active-new-{suffix}"
            )
            assert not active_created and active.workflow_id == first_id
        with transaction(sessions) as session:
            for target in (
                WorkflowState.RUNNING,
                WorkflowState.AWAITING_HUMAN_APPROVAL,
                WorkflowState.APPROVED,
                WorkflowState.REGISTERING,
                WorkflowState.COMPLETED,
            ):
                transition_workflow(
                    session,
                    first_id,
                    target,
                    f"TEST_{target.value}",
                    actor_type="system",
                    actor_id="test",
                    command_id=None,
                )
        with transaction(sessions) as session:
            stored_definition = session.get(WorkflowDefinitionRecord, definition_id)
            assert stored_definition is not None
            completed, completed_created, _ = _submit(
                session, stored_definition, request, f"completed-new-{suffix}"
            )
            assert not completed_created and completed.workflow_id == first_id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowInstanceRecord)
                    .where(
                        WorkflowInstanceRecord.request_hash
                        == workflow_business_fingerprint(stored_definition, request)
                    )
                )
                == 1
            )
    finally:
        if definition_id:
            _cleanup(integration_engine, definition_id)


@pytest.mark.parametrize("prior_failed", (False, True))
def test_concurrent_equivalent_submissions_create_one_active_occurrence(
    integration_engine: Engine, prior_failed: bool
) -> None:
    sessions = build_session_factory(integration_engine)
    suffix = uuid4().hex
    request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    definition_id = ""
    prior_id: str | None = None
    try:
        with transaction(sessions) as session:
            created_definition = _definition(session, suffix)
            definition_id = created_definition.definition_id
            if prior_failed:
                prior, created, _ = _submit(
                    session, created_definition, request, f"concurrent-prior-{suffix}"
                )
                assert created
                prior_id = prior.workflow_id
        if prior_id is not None:
            with transaction(sessions) as session:
                _terminate(session, prior_id, WorkflowState.FAILED)

        barrier = Barrier(2)

        def submit(number: int) -> tuple[str, bool]:
            barrier.wait(timeout=5)
            with transaction(sessions) as session:
                stored_definition = session.get(WorkflowDefinitionRecord, definition_id)
                assert stored_definition is not None
                workflow, created, _ = _submit(
                    session, stored_definition, request, f"concurrent-{number}-{suffix}"
                )
                return workflow.workflow_id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, range(2)))

        assert len({workflow_id for workflow_id, _created in outcomes}) == 1
        assert sum(created for _workflow_id, created in outcomes) == 1
        with sessions() as session:
            stored_definition = session.get(WorkflowDefinitionRecord, definition_id)
            assert stored_definition is not None
            request_hash = workflow_business_fingerprint(stored_definition, request)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowInstanceRecord)
                    .where(
                        WorkflowInstanceRecord.request_hash == request_hash,
                        WorkflowInstanceRecord.state.in_(
                            (
                                WorkflowState.REQUESTED.value,
                                WorkflowState.RUNNING.value,
                                WorkflowState.AWAITING_HUMAN_APPROVAL.value,
                                WorkflowState.REWORK_REQUESTED.value,
                                WorkflowState.APPROVED.value,
                                WorkflowState.REGISTERING.value,
                            )
                        ),
                    )
                )
                == 1
            )
            if prior_id is not None:
                stored_prior = session.get(WorkflowInstanceRecord, prior_id)
                assert stored_prior is not None
                assert stored_prior.state == WorkflowState.FAILED.value
    finally:
        if definition_id:
            _cleanup(integration_engine, definition_id)
