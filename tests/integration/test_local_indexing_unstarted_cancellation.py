"""Guarded real PostgreSQL cancellation/replay/claim races; no production or model."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_identity_service import (
    activate_local_indexing_service,
    disable_local_indexing_service,
    register_local_indexing_service,
)
from eom_operator_identity import LocalIndexingServiceError, local_indexing_service_reference
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.compiler import compile_definition
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow.local_indexing_unstarted_cancellation import (
    parse_local_indexing_cancellation_command,
)
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_submission import start_local_embedding_in_session
from eom_workflow_runner.local_indexing_unstarted_cancellation import (
    CANCELLATION_EVENT,
    LocalIndexingCancellationError,
    cancel_unstarted_indexing_workflow,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_step_run,
    enqueue_command,
    import_workflow_definition,
)
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_local_embedding_runner import ClaimFixture, SyntheticOwner
from tests.integration.test_local_indexing_service_registry import identity
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_public_solution_native_carriers import public_native_fixture

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in():
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


@dataclass
class Case:
    fixture: ClaimFixture
    command: object
    service: object


@pytest.fixture(params=("legacy", "public"))
def case(guarded_engine, request):
    sessions = build_session_factory(guarded_engine)
    service = identity()
    reference = local_indexing_service_reference(service)
    prefix = "synthetic-unstarted:" + uuid4().hex
    with sessions.begin() as session:
        register_local_indexing_service(session, service, operation_key=prefix + ":register")
        activate_local_indexing_service(
            session, reference, expected_resource_version=1, operation_key=prefix + ":activate"
        )
    _scope, compiled = scope_fixture()
    if request.param == "public":
        compiled = compile_definition(
            Path(__file__).resolve().parents[2] / "config/workflows/local-embedding-index.v2.yaml",
            set(),
        )
    native = service_fixture(service=reference, workflow_definition_sha256=compiled.sha256)
    if request.param == "public":
        public = public_native_fixture()
        body = public["request"].model_dump(mode="json") | {
            "workflow_definition_sha256": compiled.sha256,
            "actor_context": native.request.actor_context.model_dump(mode="json"),
            "native_execution_policy": native.request.native_execution_policy.model_dump(
                mode="json"
            ),
            "native_execution_policy_sha256": native.policy.policy_sha256,
        }
        selected = parse_supported_local_embedding_request(seal(body, "request_sha256"))
        native = replace(
            native,
            request=selected,
            base=replace(native.base, request=selected, plan=public["plan"]),
        )
    owner = SyntheticOwner(
        ResolvedLocalEmbeddingAdmission(native.request, native.base.plan, native.policy)
    )
    with sessions.begin() as session:
        EmbeddingEncodingReservationStorage.prepare_protocol(session)
        definition, _ = import_workflow_definition(session, compiled)
        submitted = start_local_embedding_in_session(
            session,
            definition=definition,
            request=native.request,
            idempotency_key=prefix + ":workflow",
            actor_type="local_indexing_service",
            actor_id=reference.service_id,
            owner=owner,
            executor=Mock(),
        )
        workflow_id = submitted.workflow.workflow_id
        command_id = submitted.command.command_id
    fixture = ClaimFixture(guarded_engine, sessions, owner, Mock(), workflow_id, command_id)
    command = parse_local_indexing_cancellation_command(
        seal(
            {
                "schema_version": "local-indexing-unstarted-cancellation/1.0",
                "record_type": "COMMAND",
                "workflow_id": workflow_id,
                "workflow_request_sha256": native.request.request_sha256,
                "command_id": command_id,
                "service": reference.model_dump(mode="json"),
                "successor_source_commit": "f" * 40,
                "reason": "NATIVE_RUNTIME_RELEASE_SUPERSEDED",
            },
            "command_sha256",
        )
    )
    return Case(fixture, command, service)


def snapshot(case):
    with case.fixture.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, case.fixture.workflow_id)
        command = session.get(WorkflowCommandRecord, case.fixture.command_id)
        return {
            "immutable": (
                workflow.initial_request,
                workflow.request_payload,
                workflow.request_hash,
                workflow.idempotency_key,
                workflow.runtime_context,
                command.request_hash,
                command.idempotency_key,
                command.lease_generation,
                command.attempts,
                command.lease_token,
                command.lease_owner,
                command.lease_expires_at,
            ),
            "states": (workflow.state, workflow.stage, command.state),
            "completed_at": workflow.completed_at,
            "processed_at": command.processed_at,
            "events": tuple(
                session.scalars(
                    select(WorkflowEventRecord.event_type)
                    .where(WorkflowEventRecord.workflow_id == workflow.workflow_id)
                    .order_by(WorkflowEventRecord.sequence)
                )
            ),
            "steps": session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow.workflow_id)
            ),
            "jobs": session.scalar(select(func.count()).select_from(JobRecord)),
            "artifacts": session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)),
        }


def test_actual_cancel_replay_keeps_identity_request_and_zero_execution(case):
    before = snapshot(case)
    assert before["states"] == ("REQUESTED", "LOCAL_EMBEDDING", "PENDING")
    with case.fixture.sessions.begin() as session:
        receipt = cancel_unstarted_indexing_workflow(session, case.command)
    after = snapshot(case)
    assert after["states"] == ("CANCELLED",) * 3
    assert after["completed_at"] is not None and after["processed_at"] is not None
    assert after["events"] == before["events"] + (
        "LOCAL_INDEXING_UNSTARTED_STAGE_CANCELLED",
        CANCELLATION_EVENT,
    )
    for key in ("immutable", "steps", "jobs", "artifacts"):
        assert after[key] == before[key]
    with case.fixture.sessions.begin() as session:
        assert cancel_unstarted_indexing_workflow(session, case.command) == receipt
    assert snapshot(case) == after
    successor = identity(
        **(
            case.service.model_dump(mode="json")
            | {
                "service_revision_id": "localindexservicerev_" + uuid4().hex,
                "previous_service_revision_id": case.service.service_revision_id,
                "revision_number": 2,
                "runtime_source_commit": "f" * 40,
            }
        )
    )
    with case.fixture.sessions.begin() as session:
        register_local_indexing_service(
            session, successor, operation_key="synthetic-successor-register:" + uuid4().hex
        )
        activate_local_indexing_service(
            session,
            local_indexing_service_reference(successor),
            expected_resource_version=3,
            operation_key="synthetic-successor-activate:" + uuid4().hex,
        )
    with case.fixture.sessions.begin() as session:
        assert cancel_unstarted_indexing_workflow(session, case.command) == receipt
    assert snapshot(case) == after
    with case.fixture.sessions.begin() as session:
        disable_local_indexing_service(
            session,
            case.service.service_id,
            expected_resource_version=4,
            operation_key="synthetic-unstarted-disable:" + uuid4().hex,
        )
    with case.fixture.sessions.begin() as session:
        assert cancel_unstarted_indexing_workflow(session, case.command) == receipt
    assert snapshot(case) == after


def test_actual_rollback_preserves_original_pending_work(case):
    before = snapshot(case)
    with pytest.raises(RuntimeError), case.fixture.sessions.begin() as session:
        cancel_unstarted_indexing_workflow(session, case.command)
        raise RuntimeError("synthetic rollback")
    assert snapshot(case) == before


@pytest.mark.parametrize("fault", ["claim", "step", "extra_command", "payload", "disabled"])
def test_actual_started_ambiguous_or_noncurrent_work_is_refused(case, fault):
    if fault == "claim":
        candidate = case.fixture.peek()
        with case.fixture.sessions.begin() as session:
            assert case.fixture.claim(session, candidate) is not None
    else:
        with case.fixture.sessions.begin() as session:
            if fault == "step":
                create_step_run(
                    session,
                    workflow_id=case.fixture.workflow_id,
                    step_key="encode_batch",
                    step_type="application",
                    worker_role=None,
                    result_schema="incremental-embedding-result@1.0",
                    input_pointer_manifest={},
                    max_attempts=1,
                )
            elif fault == "extra_command":
                enqueue_command(
                    session,
                    workflow_id=case.fixture.workflow_id,
                    command_type=CommandType.ADVANCE_WORKFLOW,
                    payload={},
                    actor_type="local_indexing_service",
                    actor_id=case.service.service_id,
                    source="synthetic_unstarted",
                    idempotency_key="synthetic-extra:" + uuid4().hex,
                )
            elif fault == "payload":
                session.get(WorkflowCommandRecord, case.fixture.command_id).payload = {
                    "extra": True
                }
            else:
                disable_local_indexing_service(
                    session,
                    case.service.service_id,
                    expected_resource_version=2,
                    operation_key="synthetic-disabled:" + uuid4().hex,
                )
    before = snapshot(case)
    with (
        pytest.raises((ValueError, LocalIndexingServiceError)),
        case.fixture.sessions.begin() as session,
    ):
        cancel_unstarted_indexing_workflow(session, case.command)
    assert snapshot(case) == before


@pytest.mark.parametrize(
    "field", ["workflow_request_sha256", "command_id", "service", "same_source"]
)
def test_actual_wrong_exact_control_pointer_is_refused(case, field):
    body = case.command.model_dump(mode="json")
    if field == "service":
        body[field]["service_revision_id"] = "localindexservicerev_" + uuid4().hex
    elif field == "same_source":
        body["successor_source_commit"] = case.service.runtime_source_commit
    else:
        body[field] = "sha256:" + "e" * 64 if field.endswith("sha256") else "wfcmd_" + uuid4().hex
    command = parse_local_indexing_cancellation_command(seal(body, "command_sha256"))
    before = snapshot(case)
    with pytest.raises(ValueError), case.fixture.sessions.begin() as session:
        cancel_unstarted_indexing_workflow(session, command)
    assert snapshot(case) == before


def test_actual_conflicting_replay_has_no_new_events(case):
    with case.fixture.sessions.begin() as session:
        cancel_unstarted_indexing_workflow(session, case.command)
    before = snapshot(case)
    changed = parse_local_indexing_cancellation_command(
        seal(
            case.command.model_dump(mode="json") | {"successor_source_commit": "e" * 40},
            "command_sha256",
        )
    )
    with (
        pytest.raises(LocalIndexingCancellationError, match="REPLAY_CONFLICT"),
        case.fixture.sessions.begin() as session,
    ):
        cancel_unstarted_indexing_workflow(session, changed)
    assert snapshot(case) == before


def test_actual_two_cancellations_append_one_receipt(case):
    barrier = Barrier(2)

    def run():
        try:
            with case.fixture.sessions.begin() as session:
                barrier.wait(timeout=5)
                return cancel_unstarted_indexing_workflow(session, case.command).receipt_sha256
        except LocalIndexingCancellationError as error:
            assert error.code == "LOCAL_INDEXING_CANCELLATION_BUSY"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run(), range(2)))
    assert any(results) and len({result for result in results if result}) == 1
    assert snapshot(case)["events"].count(CANCELLATION_EVENT) == 1


def test_actual_held_workflow_lock_refuses_cancellation_without_wait(case):
    before = snapshot(case)
    with case.fixture.sessions.begin() as holder:
        holder.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == case.fixture.workflow_id)
            .with_for_update()
        )
        with (
            pytest.raises(LocalIndexingCancellationError, match="BUSY"),
            case.fixture.sessions.begin() as session,
        ):
            cancel_unstarted_indexing_workflow(session, case.command)
    assert snapshot(case) == before


def test_actual_claim_wins_then_cancellation_refuses_without_allocation(case):
    candidate = case.fixture.peek()
    with case.fixture.sessions.begin() as owner:
        assert case.fixture.claim(owner, candidate) is not None
        with (
            pytest.raises(LocalIndexingCancellationError, match="BUSY"),
            case.fixture.sessions.begin() as other,
        ):
            cancel_unstarted_indexing_workflow(other, case.command)
    before = snapshot(case)
    assert before["states"][-1] == "LEASED"
    with (
        pytest.raises(LocalIndexingCancellationError, match="UNSTARTED_UNPROVEN"),
        case.fixture.sessions.begin() as other,
    ):
        cancel_unstarted_indexing_workflow(other, case.command)
    assert snapshot(case) == before


def test_actual_cancellation_wins_then_same_claim_cannot_execute(case):
    candidate = case.fixture.peek()
    with case.fixture.sessions.begin() as session:
        cancel_unstarted_indexing_workflow(session, case.command)
    before = snapshot(case)
    with case.fixture.sessions.begin() as session:
        assert case.fixture.claim(session, candidate) is None
    assert snapshot(case) == before


def test_actual_nonowner_login_cannot_cancel(case):
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = make_url(values["EOM_API_DATABASE_URL"])
    assert url.username == manifest.runtime_role and url.database == manifest.database
    runtime = build_engine(
        url.set(query={"options": "-csearch_path=app,pg_catalog"}).render_as_string(
            hide_password=False
        )
    )
    before = snapshot(case)
    try:
        with (
            pytest.raises(LocalIndexingCancellationError, match="OWNER_REQUIRED"),
            Session(runtime) as session,
            session.begin(),
        ):
            cancel_unstarted_indexing_workflow(session, case.command)
    finally:
        runtime.dispose()
    assert snapshot(case) == before
