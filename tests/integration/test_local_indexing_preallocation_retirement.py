"""Actual guarded PostgreSQL failure/replay/locking; synthetic source admission.

No production rows, numerical execution, model, NAS, publication or source grant.
Committed synthetic immutable histories remain until the guarded DB is removed.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_workflow.local_indexing_preallocation_retirement import (
    parse_local_indexing_retirement_command,
)
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_submission import start_local_embedding_in_session
from eom_workflow_runner.local_indexing_preallocation_retirement import (
    RETIREMENT_EVENT,
    LocalIndexingRetirementError,
    retire_unallocated_indexing_workflow,
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
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowState,
    transition_command,
    transition_step,
    transition_workflow,
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
    request: object
    step_id: str


@pytest.fixture
def case(guarded_engine):
    sessions = build_session_factory(guarded_engine)
    service = identity()
    reference = local_indexing_service_reference(service)
    prefix = "synthetic-retirement:" + uuid4().hex
    with sessions.begin() as session:
        register_local_indexing_service(session, service, operation_key=prefix + ":register")
        activate_local_indexing_service(
            session, reference, expected_resource_version=1, operation_key=prefix + ":activate"
        )
    _scope, compiled = scope_fixture()
    native = service_fixture(service=reference, workflow_definition_sha256=compiled.sha256)
    request = native.request
    owner = SyntheticOwner(
        ResolvedLocalEmbeddingAdmission(request, native.base.plan, native.policy)
    )
    with sessions.begin() as session:
        EmbeddingEncodingReservationStorage.prepare_protocol(session)
        definition, _created = import_workflow_definition(session, compiled)
        submitted = start_local_embedding_in_session(
            session,
            definition=definition,
            request=request,
            idempotency_key=prefix + ":workflow",
            actor_type="local_indexing_service",
            actor_id=reference.service_id,
            owner=owner,
            executor=Mock(),
        )
        workflow_id, command_id = submitted.workflow.workflow_id, submitted.command.command_id
    fixture = ClaimFixture(guarded_engine, sessions, owner, Mock(), workflow_id, command_id)
    candidate = fixture.peek()
    with sessions.begin() as session:
        command = fixture.claim(session, candidate)
        transition_command(command, CommandState.PROCESSING)
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_PREALLOCATION_START",
            actor_type="local_indexing_service",
            actor_id=reference.service_id,
            command_id=command_id,
            step_key="encode_batch",
        )
        step = create_step_run(
            session,
            workflow_id=workflow_id,
            step_key="encode_batch",
            step_type="application",
            worker_role=None,
            result_schema="incremental-embedding-result@1.0",
            input_pointer_manifest={
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": request.source_plan_sha256,
            },
            max_attempts=1,
        )
        transition_step(step, StepState.RUNNING)
        step_id = step.step_run_id
    command = parse_local_indexing_retirement_command(
        seal(
            {
                "schema_version": "local-indexing-preallocation-retirement/1.0",
                "record_type": "COMMAND",
                "workflow_id": workflow_id,
                "workflow_request_sha256": request.request_sha256,
                "command_id": command_id,
                "lease_generation": 1,
                "service": reference.model_dump(mode="json"),
                "successor_source_commit": "f" * 40,
                "reason": "EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE",
            },
            "command_sha256",
        )
    )
    return Case(fixture, command, service, request, step_id)


def snapshot(case):
    with case.fixture.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, case.fixture.workflow_id)
        command = session.get(WorkflowCommandRecord, case.fixture.command_id)
        step = session.get(WorkflowStepRunRecord, case.step_id)
        return {
            "request": workflow.initial_request,
            "payload": workflow.request_payload,
            "request_hash": workflow.request_hash,
            "idempotency": workflow.idempotency_key,
            "runtime_context": workflow.runtime_context,
            "command_identity": (
                command.request_hash,
                command.idempotency_key,
                command.lease_generation,
                command.lease_token,
                command.lease_owner,
                command.lease_expires_at,
            ),
            "states": (workflow.state, workflow.stage, command.state, step.state),
            "events": tuple(
                session.scalars(
                    select(WorkflowEventRecord.event_type)
                    .where(WorkflowEventRecord.workflow_id == workflow.workflow_id)
                    .order_by(WorkflowEventRecord.sequence)
                )
            ),
            "jobs": session.scalar(select(func.count()).select_from(JobRecord)),
            "artifacts": session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)),
        }


def test_actual_failure_replay_keeps_request_lease_and_job_artifact_counts(case):
    before = snapshot(case)
    with case.fixture.sessions.begin() as session:
        result = retire_unallocated_indexing_workflow(session, case.command)
    after = snapshot(case)
    assert after["states"] == ("FAILED",) * 4
    assert after["events"] == before["events"] + (
        "LOCAL_INDEXING_PREALLOCATION_STAGE_FAILED",
        RETIREMENT_EVENT,
    )
    for key in set(before) - {"states", "events"}:
        assert after[key] == before[key]
    with case.fixture.sessions.begin() as session:
        replay = retire_unallocated_indexing_workflow(session, case.command)
    assert replay == result and snapshot(case) == after
    # A historical replay does not reactivate a now-disabled service.
    with case.fixture.sessions.begin() as session:
        disable_local_indexing_service(
            session,
            case.service.service_id,
            expected_resource_version=2,
            operation_key="synthetic-retirement-disable:" + uuid4().hex,
        )
    with case.fixture.sessions.begin() as session:
        assert retire_unallocated_indexing_workflow(session, case.command) == result


def test_actual_retirement_root_rollback_leaves_no_partial_failure(case):
    before = snapshot(case)
    with (
        pytest.raises(RuntimeError, match="synthetic rollback"),
        case.fixture.sessions.begin() as session,
    ):
        retire_unallocated_indexing_workflow(session, case.command)
        raise RuntimeError("synthetic rollback")
    assert snapshot(case) == before


@pytest.mark.parametrize(
    "fault",
    [
        "live_lease",
        "output",
        "empty_output",
        "wrong_input",
        "finished",
        "extra_command",
        "extra_step",
        "allocated_job",
        "disabled",
    ],
)
def test_actual_non_preallocation_or_noncurrent_scope_is_never_retired(case, fault):
    with case.fixture.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, case.fixture.command_id)
        step = session.get(WorkflowStepRunRecord, case.step_id)
        if fault == "live_lease":
            command.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        elif fault in {"output", "empty_output"}:
            step.output_pointer_manifest = {"saved": True} if fault == "output" else {}
        elif fault == "wrong_input":
            step.input_pointer_manifest = {}
        elif fault == "finished":
            transition_step(step, StepState.FAILED)
        elif fault == "extra_command":
            enqueue_command(
                session,
                workflow_id=case.fixture.workflow_id,
                command_type=CommandType.ADVANCE_WORKFLOW,
                payload={},
                actor_type="local_indexing_service",
                actor_id=case.service.service_id,
                source="synthetic_retirement",
                idempotency_key="synthetic-extra:" + uuid4().hex,
            )
        elif fault == "extra_step":
            create_step_run(
                session,
                workflow_id=case.fixture.workflow_id,
                step_key="encode_batch",
                step_type="application",
                worker_role=None,
                result_schema=step.result_schema,
                input_pointer_manifest=step.input_pointer_manifest,
                max_attempts=2,
            )
        elif fault == "allocated_job":
            create_native_embedding_launch(
                session,
                request=case.request,
                workflow_id=case.fixture.workflow_id,
                step_run_id=step.step_run_id,
                command_id=command.command_id,
                runner_id=command.lease_owner,
                lease_generation=1,
            )
        else:
            disable_local_indexing_service(
                session,
                case.service.service_id,
                expected_resource_version=2,
                operation_key="synthetic-denial:" + uuid4().hex,
            )
    before = snapshot(case)
    with (
        pytest.raises((LocalIndexingRetirementError, LocalIndexingServiceError)),
        case.fixture.sessions.begin() as session,
    ):
        retire_unallocated_indexing_workflow(session, case.command)
    assert snapshot(case) == before


def test_actual_changed_retirement_command_conflicts_without_adding_events(case):
    with case.fixture.sessions.begin() as session:
        retire_unallocated_indexing_workflow(session, case.command)
    before = snapshot(case)
    changed = parse_local_indexing_retirement_command(
        seal(
            case.command.model_dump(mode="json") | {"successor_source_commit": "e" * 40},
            "command_sha256",
        )
    )
    with (
        pytest.raises(LocalIndexingRetirementError, match="REPLAY_CONFLICT"),
        case.fixture.sessions.begin() as session,
    ):
        retire_unallocated_indexing_workflow(session, changed)
    assert snapshot(case) == before


@pytest.mark.parametrize(
    "field", ["workflow_request_sha256", "command_id", "lease_generation", "service", "same_source"]
)
def test_actual_validly_hashed_but_different_control_intent_is_denied(case, field):
    body = case.command.model_dump(mode="json")
    if field == "lease_generation":
        body[field] += 1
    elif field == "service":
        body[field]["service_revision_id"] = "localindexservicerev_" + uuid4().hex
    elif field == "same_source":
        body["successor_source_commit"] = case.service.runtime_source_commit
    else:
        body[field] = "sha256:" + "e" * 64 if field.endswith("sha256") else "wfcmd_" + uuid4().hex
    command = parse_local_indexing_retirement_command(seal(body, "command_sha256"))
    before = snapshot(case)
    with pytest.raises(LocalIndexingRetirementError), case.fixture.sessions.begin() as session:
        retire_unallocated_indexing_workflow(session, command)
    assert snapshot(case) == before


def test_actual_nonowner_login_cannot_retire(case):
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
            pytest.raises(LocalIndexingRetirementError, match="OWNER_REQUIRED"),
            Session(runtime) as session,
            session.begin(),
        ):
            retire_unallocated_indexing_workflow(session, case.command)
    finally:
        runtime.dispose()
    assert snapshot(case) == before


def test_actual_concurrent_owners_append_only_one_retirement(case):
    barrier = Barrier(2)

    def run():
        try:
            with case.fixture.sessions.begin() as session:
                barrier.wait(timeout=5)
                return retire_unallocated_indexing_workflow(session, case.command).receipt_sha256
        except LocalIndexingRetirementError as error:
            assert error.code == "LOCAL_INDEXING_RETIREMENT_BUSY"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run(), range(2)))
    assert any(results) and len({result for result in results if result}) == 1
    assert snapshot(case)["events"].count(RETIREMENT_EVENT) == 1
    with case.fixture.sessions.begin() as session:
        assert retire_unallocated_indexing_workflow(session, case.command).receipt_sha256 in results


def test_actual_held_command_lock_refuses_retirement_without_wait_or_partial_effect(case):
    before = snapshot(case)
    with case.fixture.sessions.begin() as holder:
        holder.scalar(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.command_id == case.fixture.command_id)
            .with_for_update()
        )
        with (
            pytest.raises(LocalIndexingRetirementError, match="BUSY"),
            case.fixture.sessions.begin() as session,
        ):
            retire_unallocated_indexing_workflow(session, case.command)
    assert snapshot(case) == before
