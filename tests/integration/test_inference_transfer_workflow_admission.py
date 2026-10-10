"""Repository admission/uniqueness in a marker-guarded disposable owner DB only.

All requests/actors are explicitly synthetic and lack production source grants.
Ordinary tests use the shared outer rollback. The opt-in concurrency case
commits its synthetic seed/results only inside the already verified disposable
database; immutable history remains until that complete database is removed.
No command, worker, model, NAS or public submission is executed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    create_workflow_instance,
    load_persisted_inference_transfer_workflow_request,
)
from psycopg.errors import UniqueViolation
from sqlalchemy import Connection, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.unit.inference_transfer_workflow_fixtures import (
    OPERATOR_ID,
    OTHER_OPERATOR_ID,
    definition,
    submission_context,
    workflow_request,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _submit(
    session: Session,
    *,
    request: InferenceTransferWorkflowRequest,
    actor_id: str,
    idempotency_key: str,
) -> tuple[WorkflowInstanceRecord, bool]:
    target = definition()
    existing = session.scalar(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.definition_key == target.definition_key,
            WorkflowDefinitionRecord.definition_version == target.definition_version,
        )
    )
    if existing is None:
        session.add(target)
        session.flush()
    else:
        assert existing.definition_hash == target.definition_hash
        assert existing.canonical_definition == target.canonical_definition
        target = existing
    return create_workflow_instance(
        session,
        definition=target,
        request=request,
        idempotency_key=idempotency_key,
        actor_type="human",
        actor_id=actor_id,
        inference_transfer_context=submission_context(actor_id),
    )


def test_actual_repository_preserves_actor_local_replay_and_global_key_conflict(
    stage_owner_connection: Connection,
) -> None:
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        key = "synthetic-transfer-owner-replay-" + uuid4().hex
        value = workflow_request(request_id="transferrequest_" + uuid4().hex)
        first, created = _submit(session, request=value, actor_id=OPERATOR_ID, idempotency_key=key)
        assert created
        session.flush()
        same, created = _submit(session, request=value, actor_id=OPERATOR_ID, idempotency_key=key)
        assert not created and same.workflow_id == first.workflow_id
        active, created = _submit(
            session, request=value, actor_id=OPERATOR_ID, idempotency_key=key + "-new-key"
        )
        assert not created and active.workflow_id == first.workflow_id
        with pytest.raises(WorkflowError) as error:
            _submit(session, request=value, actor_id=OTHER_OPERATOR_ID, idempotency_key=key)
        assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE
        other, created = _submit(
            session, request=value, actor_id=OTHER_OPERATOR_ID, idempotency_key=key + "-other-actor"
        )
        assert created and other.workflow_id != first.workflow_id
        assert other.request_hash != first.request_hash
        assert first.created_actor_id == OPERATOR_ID
        assert other.created_actor_id == OTHER_OPERATOR_ID
        session.flush()
        session.expire_all()
        loaded = session.get(WorkflowInstanceRecord, first.workflow_id)
        assert loaded is not None
        assert loaded.stage == "INFERENCE_TRANSFER"
        assert load_persisted_inference_transfer_workflow_request(loaded.initial_request) == (value)
        assert loaded.initial_request["left_profile"]["extraction"]["prompt_sha256"] is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == first.workflow_id)
            )
            == 1
        )


@pytest.mark.parametrize(
    ("collision", "constraint"),
    (
        ("active_hash", "uq_workflow_active_request_hash"),
        ("idempotency_key", "workflow_instances_idempotency_key_key"),
    ),
)
def test_actual_unique_constraints_are_not_replaced_by_application_checks(
    stage_owner_connection: Connection, collision: str, constraint: str
) -> None:
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        key = "synthetic-transfer-constraint-" + uuid4().hex
        value = workflow_request(request_id="transferrequest_" + uuid4().hex)
        first, created = _submit(session, request=value, actor_id=OPERATOR_ID, idempotency_key=key)
        assert created
        session.flush()
        # This intentionally conflicting synthetic row tests PostgreSQL's guard;
        # production submissions always use create_workflow_instance above.
        duplicate = WorkflowInstanceRecord(
            workflow_id="workflow_" + uuid4().hex,
            definition_id=first.definition_id,
            definition_key=first.definition_key,
            definition_version=first.definition_version,
            definition_hash=first.definition_hash,
            protocol_version=first.protocol_version,
            role_schema_version=first.role_schema_version,
            state=first.state,
            stage=first.stage,
            current_step_key=first.current_step_key,
            request_payload=first.request_payload,
            initial_request=first.initial_request,
            runtime_context=first.runtime_context,
            idempotency_key=key if collision == "idempotency_key" else key + "-duplicate",
            request_hash=(
                first.request_hash if collision == "active_hash" else "sha256:" + uuid4().hex * 2
            ),
            lock_version=1,
            rework_cycle_count=0,
            created_actor_type="human",
            created_actor_id=OPERATOR_ID,
        )
        with pytest.raises(IntegrityError) as error, session.begin_nested():
            session.add(duplicate)
            session.flush()
        assert isinstance(error.value.orig, UniqueViolation)
        assert error.value.orig.diag.constraint_name == constraint
        session.refresh(first)
        assert first.created_actor_id == OPERATOR_ID
        assert first.state == "REQUESTED"


def test_two_concurrent_owner_submissions_create_one_exact_workflow_and_event(
    stage_owner_connection: Connection,
) -> None:
    # This engine is available only after database/user/schema marker/head
    # verification in stage_owner_connection. Never use an ambient fallback.
    engine = stage_owner_connection.engine
    target = definition()
    with Session(engine) as session, session.begin():
        existing = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == target.definition_key,
                WorkflowDefinitionRecord.definition_version == target.definition_version,
            )
        )
        if existing is None:
            session.add(target)
            session.flush()
            definition_id = target.definition_id
        else:
            assert existing.definition_hash == target.definition_hash
            assert existing.canonical_definition == target.canonical_definition
            definition_id = existing.definition_id
    # The committed seed is intentionally disposable test metadata, not a
    # runtime import or a release activation. Both workers now see one FK owner.
    key = "synthetic-transfer-concurrent-" + uuid4().hex
    request_value = workflow_request(request_id="transferrequest_" + uuid4().hex)
    barrier = Barrier(2)

    def submit(_number: int) -> tuple[str, bool]:
        with Session(engine) as session, session.begin():
            stored = session.get(WorkflowDefinitionRecord, definition_id)
            assert stored is not None
            barrier.wait(timeout=10)
            value, created = create_workflow_instance(
                session,
                definition=stored,
                request=request_value,
                idempotency_key=key,
                actor_type="human",
                actor_id=OPERATOR_ID,
                inference_transfer_context=submission_context(),
            )
            return value.workflow_id, created

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(submit, range(2)))
    ids = {workflow_id for workflow_id, _created in outcomes}
    assert len(ids) == 1
    assert sum(created for _workflow_id, created in outcomes) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == next(iter(ids)))
            )
            == 1
        )
