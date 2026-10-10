"""Atomic submission metadata in the existing marker-guarded disposable DB.

The AuthorizedSubmission/actor and source grant are deliberately synthetic.
Existing control fixtures fake native candidate availability. These tests prove
transaction/replay/concurrency properties, not source authorization, installed
transport, protected bytes, model execution or educational quality. Only the
concurrency case commits synthetic metadata inside the guarded disposable DB.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_start_adapter import InferenceTransferStartAdapter
from eom_api.services.inference_transfer_submission import AuthorizedInferenceTransferSubmission
from eom_catalog_contracts.inference_transfer_invocation import InferenceTransferPairSubmitRequest
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.control_models import ExecutionPresetRecord, ResolvedExecutionPlanRecord
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from psycopg.errors import RaiseException
from sqlalchemy import Connection, func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_inference_transfer_plan_persistence import _controls
from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_prepare
from tests.unit.inference_transfer_workflow_fixtures import (
    OPERATOR_ID,
    OTHER_OPERATOR_ID,
    definition,
    workflow_request,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _actor(operator_id: str = OPERATOR_ID) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=operator_id,
        session_id="apisession_" + uuid4().hex,
        request_id="request_" + uuid4().hex,
        authentication_time=NOW,
        permissions=frozenset({PermissionKey.WORKFLOW_START, PermissionKey.WORKFLOW_READ}),
        source=ActorSource.APPLICATION_API,
    )


def _submission(actor: ActorContext) -> AuthorizedInferenceTransferSubmission:
    request = workflow_request(request_id="transferrequest_" + uuid4().hex)
    wrapper_body = request.model_dump(mode="json", exclude={"request_sha256"})
    wrapper_body["requester_permissions_sha256"] = content_sha256(
        sorted(permission.value for permission in actor.permissions)
    )
    wrapper = InferenceTransferWorkflowRequest.model_validate(
        wrapper_body | {"request_sha256": content_sha256(wrapper_body)}
    )
    prepare_body = snapshot_prepare().model_dump(mode="json", exclude={"prepare_sha256"})
    prepare_body.update(
        graph_snapshot=wrapper.left_profile.source_basis.graph_snapshot.model_dump(mode="json"),
        access_policy_revision_id=wrapper.access_policy_revision_id,
        access_policy_sha256=wrapper.access_policy_sha256,
    )
    prepare = InferenceTransferSnapshotPrepareRequest.model_validate(
        prepare_body | {"prepare_sha256": content_sha256(prepare_body)}
    )
    selection_body = {
        "schema_version": "inference-transfer-pair-submit/1.0",
        "comparison": wrapper.comparison.model_dump(mode="json"),
        "snapshot_prepare": prepare.model_dump(mode="json"),
        # Synthetic capture only: this digest does not represent a live snapshot.
        "expected_header_sha256": "sha256:" + "8" * 64,
    }
    selection = InferenceTransferPairSubmitRequest.model_validate(
        selection_body | {"submission_sha256": content_sha256(selection_body)}
    )
    return AuthorizedInferenceTransferSubmission(actor.actor_id, selection, wrapper)


def _definition(session: Session) -> None:
    target = definition()
    stored = session.scalar(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.definition_key == target.definition_key,
            WorkflowDefinitionRecord.definition_version == target.definition_version,
        )
    )
    if stored is None:
        session.add(target)
        session.flush()
    else:
        assert stored.definition_hash == target.definition_hash
        assert stored.canonical_definition == target.canonical_definition


def _adapter(connection: Connection) -> InferenceTransferStartAdapter:
    adapter = object.__new__(InferenceTransferStartAdapter)
    adapter.sessions = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return adapter


def _seed(connection: Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    with (
        Session(bind=connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        _definition(session)
        _controls(session, monkeypatch)


def test_actual_submission_atomically_records_workflow_v21_and_original_start_command(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    submission = _submission(actor)
    key = "synthetic-api-transfer-" + uuid4().hex
    command_id, workflow_id, version = _adapter(stage_owner_connection).start(
        submission, actor, idempotency_key=key
    )
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        command = session.get(WorkflowCommandRecord, command_id)
        plan = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow_id
            )
        )
        assert workflow is not None and command is not None and plan is not None
        assert version == workflow.lock_version == 1
        assert workflow.state == "REQUESTED" and workflow.stage == "INFERENCE_TRANSFER"
        assert workflow.initial_request == submission.workflow_request.model_dump(mode="json")
        assert (
            workflow.created_actor_id == actor.actor_id and workflow.created_actor_type == "human"
        )
        assert command.workflow_id == workflow_id and command.command_type == "START_WORKFLOW"
        assert command.actor_id == actor.actor_id and command.source == "application_api"
        assert command.state == "PENDING"
        assert plan.canonical_document["schema_version"] == "resolved-execution-plan/21.0"
        assert plan.canonical_document["comparison_request_sha256"] == (
            submission.workflow_request.comparison.request_sha256
        )
        assert workflow.runtime_context["execution_plan"] == {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "preset_id": plan.preset_id,
            "preset_revision_id": plan.preset_revision_id,
        }


def test_missing_released_controls_rolls_back_new_workflow_plan_and_start_together(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    with (
        Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "item-inference-transfer-comparison"
            )
        )
        assert logical is not None
        logical.current_revision_id = None
    actor = _actor()
    key = "synthetic-api-transfer-no-controls-" + uuid4().hex
    adapter = _adapter(stage_owner_connection)
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(entity))
            for entity in (
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                ResolvedExecutionPlanRecord,
            )
        )
    with pytest.raises(ApiError) as error:
        adapter.start(_submission(actor), actor, idempotency_key=key)
    assert error.value.status == 409 and str(error.value.error_code).startswith("CONTROL_")
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        after = tuple(
            session.scalar(select(func.count()).select_from(entity))
            for entity in (
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                ResolvedExecutionPlanRecord,
            )
        )
        assert after == before
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )


def test_exact_replay_keeps_initial_permission_digest_and_single_workflow_plan_start(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    original = _submission(actor)
    adapter = _adapter(stage_owner_connection)
    key = "synthetic-api-transfer-replay-" + uuid4().hex
    first = adapter.start(original, actor, idempotency_key=key)
    updated_actor = ActorContext.model_validate(
        actor.model_dump(mode="json")
        | {
            "permissions": sorted(
                {p.value for p in actor.permissions} | {PermissionKey.ITEM_READ.value}
            )
        }
    )
    changed_body = original.workflow_request.model_dump(mode="json", exclude={"request_sha256"})
    changed_body["requester_permissions_sha256"] = content_sha256(
        sorted(p.value for p in updated_actor.permissions)
    )
    updated = replace(
        original,
        workflow_request=InferenceTransferWorkflowRequest.model_validate(
            changed_body | {"request_sha256": content_sha256(changed_body)}
        ),
    )
    assert adapter.start(updated, updated_actor, idempotency_key=key) == first
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        stored = session.get(WorkflowInstanceRecord, first[1])
        assert stored is not None
        assert stored.initial_request["requester_permissions_sha256"] == (
            original.workflow_request.requester_permissions_sha256
        )
        assert stored.initial_request == original.workflow_request.model_dump(mode="json")
        for entity in (WorkflowCommandRecord, ResolvedExecutionPlanRecord):
            assert (
                session.scalar(
                    select(func.count()).select_from(entity).where(entity.workflow_id == first[1])
                )
                == 1
            )


@pytest.mark.parametrize("collision", ["changed_selection", "different_owner"])
def test_same_key_cannot_be_reused_for_other_public_selection_or_operator(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch, collision: str
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    original = _submission(actor)
    adapter = _adapter(stage_owner_connection)
    key = "synthetic-api-transfer-conflict-" + uuid4().hex
    adapter.start(original, actor, idempotency_key=key)
    if collision == "changed_selection":
        selection_body = original.selection.model_dump(mode="json", exclude={"submission_sha256"})
        selection_body["expected_header_sha256"] = "sha256:" + "7" * 64
        changed = replace(
            original,
            selection=InferenceTransferPairSubmitRequest.model_validate(
                selection_body | {"submission_sha256": content_sha256(selection_body)}
            ),
        )
    else:
        actor = _actor(OTHER_OPERATOR_ID)
        changed = replace(original, operator_id=actor.actor_id)
    with pytest.raises(ApiError) as error:
        adapter.start(changed, actor, idempotency_key=key)
    assert error.value.status == 409
    assert error.value.error_code == "INFERENCE_TRANSFER_SUBMISSION_CONFLICT"


def test_foreign_actor_is_denied_before_any_transaction_or_workflow_creation(
    stage_owner_connection: Connection,
) -> None:
    actor = _actor()
    with pytest.raises(ApiError) as error:
        _adapter(stage_owner_connection).start(
            _submission(actor),
            _actor(OTHER_OPERATOR_ID),
            idempotency_key="synthetic-foreign-" + uuid4().hex,
        )
    assert error.value.status == 403


@pytest.mark.parametrize(
    "drift",
    ["missing_plan_pin", "wrong_plan_sha", "other_plan_id"],
)
def test_replay_rejects_mutable_runtime_execution_pin_drift_without_new_identity(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    submission = _submission(actor)
    adapter = _adapter(stage_owner_connection)
    key = "synthetic-api-transfer-drift-" + uuid4().hex
    first = adapter.start(submission, actor, idempotency_key=key)
    with (
        Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        stored = session.get(WorkflowInstanceRecord, first[1])
        assert stored is not None
        runtime = deepcopy(stored.runtime_context)
        if drift == "missing_plan_pin":
            runtime.pop("execution_plan")
        elif drift == "wrong_plan_sha":
            runtime["execution_plan"]["plan_sha256"] = "sha256:" + "9" * 64
        else:
            runtime["execution_plan"]["plan_id"] = "execplan_" + "9" * 32
        stored.runtime_context = runtime
    with pytest.raises(ApiError) as error:
        adapter.start(submission, actor, idempotency_key=key)
    assert error.value.status == 409
    assert error.value.error_code == "INFERENCE_TRANSFER_SUBMISSION_CONFLICT"
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 1
        )
        for entity in (WorkflowCommandRecord, ResolvedExecutionPlanRecord):
            assert (
                session.scalar(
                    select(func.count()).select_from(entity).where(entity.workflow_id == first[1])
                )
                == 1
            )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("definition_hash", "sha256:" + "9" * 64),
        ("role_schema_version", "workflow-role/1.22.0"),
        ("request_hash", "sha256:" + "9" * 64),
    ],
)
def test_native_snapshot_immutability_blocks_drift_and_original_replay_remains_exact(
    stage_owner_connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    submission = _submission(actor)
    adapter = _adapter(stage_owner_connection)
    key = "synthetic-api-transfer-immutable-" + uuid4().hex
    first = adapter.start(submission, actor, idempotency_key=key)
    with (
        Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        stored = session.get(WorkflowInstanceRecord, first[1])
        assert stored is not None
        original_value = getattr(stored, field)
        with pytest.raises(ProgrammingError) as error, session.begin_nested():
            setattr(stored, field, replacement)
            session.flush()
        assert isinstance(error.value.orig, RaiseException)
        assert error.value.orig.sqlstate == "P0001"
        assert "workflow instance snapshot fields are immutable" in str(error.value.orig)
        session.refresh(stored)
        assert getattr(stored, field) == original_value
    assert adapter.start(submission, actor, idempotency_key=key) == first
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 1
        )
        for entity in (WorkflowCommandRecord, ResolvedExecutionPlanRecord):
            assert (
                session.scalar(
                    select(func.count()).select_from(entity).where(entity.workflow_id == first[1])
                )
                == 1
            )


def test_actual_concurrent_same_key_has_one_advisory_serialized_capture_and_start(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This engine exists only after the shared database/user/schema/head guard.
    # Commit the seed so independent connections share real native constraints.
    engine = stage_owner_connection.engine
    with Session(engine) as session, session.begin():
        _definition(session)
        _controls(session, monkeypatch)
    actor = _actor()
    submission = _submission(actor)
    key = "synthetic-api-transfer-concurrency-" + uuid4().hex
    barrier = Barrier(2)

    def start(_number: int) -> tuple[str, str, int]:
        barrier.wait(timeout=10)
        return InferenceTransferStartAdapter(engine).start(submission, actor, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(start, range(2)))
    assert len(set(outcomes)) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 1
        )
        for entity in (WorkflowCommandRecord, ResolvedExecutionPlanRecord):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(entity)
                    .where(entity.workflow_id == outcomes[0][1])
                )
                == 1
            )
