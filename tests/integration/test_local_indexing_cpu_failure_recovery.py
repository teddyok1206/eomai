"""Guarded real PostgreSQL closure/replay. OS, model and source execution are synthetic.

Fixtures use the real service registry and native admission/queue/encoding storage;
the read-only actual old CPU unit is a separate live gate, not this test's proof.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.native_cpu_index_failure_read import ResolvedRetiredNativeCpuIndexFailure
from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_identity_service import activate_local_indexing_service, register_local_indexing_service
from eom_operator_identity import local_indexing_service_reference
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.embedding_artifact_store import owned_embedding_publication_key
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_workflow.embedding_cpu_failure_recovery import CpuEmbeddingFailureRecoveryCommand
from eom_workflow.embedding_encoding_recovery import ENCODING_RETRY_SUCCESSOR_EVENT
from eom_workflow_runner import local_indexing_cpu_failure_recovery as application
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import CommandType, enqueue_command
from eom_workflow_runner.state_machine import CommandState, transition_command
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.allocated_indexing_failure_fixtures import seed_allocated_execution
from tests.integration.test_local_embedding_runner import ClaimFixture
from tests.integration.test_local_indexing_service_registry import identity
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cpu_failure_recovery import cpu_root
from tests.unit.test_embedding_encoding_reservations import SyntheticAdmission

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def cpu(guarded_engine, monkeypatch, request):
    variant = getattr(request, "param", 3)
    value = seed_allocated_execution(
        guarded_engine, device="CPU", request_family="2.0" if variant == "mixed" else "1.2"
    )
    count = 3 if variant == "mixed" else variant
    with value.sessions.begin() as session:
        transition_command(
            session.get(WorkflowCommandRecord, value.origin_command_id), CommandState.SUCCEEDED
        )
    for ordinal in range(count):
        with value.sessions.begin() as session:
            pending, _ = enqueue_command(
                session,
                workflow_id=value.workflow_id,
                command_type=CommandType.ADVANCE_WORKFLOW,
                payload={},
                actor_type="local_indexing_service",
                actor_id=value.service.service_id,
                source="synthetic_cpu_deferred",
                idempotency_key="cpu-failure-test:" + uuid4().hex,
            )
            command_id = pending.command_id
        claim = ClaimFixture(
            guarded_engine, value.sessions, value.owner, Mock(), value.workflow_id, command_id
        )
        with value.sessions.begin() as session:
            current = claim.claim(session, claim.peek())
            assert current is not None and current.command_id == command_id
            transition_command(current, CommandState.PROCESSING)
            current.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
            if ordinal < count - 1:
                transition_command(current, CommandState.SUCCEEDED)
    successor = identity(
        service_id=value.service.service_id,
        previous_service_revision_id=value.service.service_revision_id,
        revision_number=2,
        runtime_source_commit="4" * 40,
    )
    current_service = local_indexing_service_reference(successor)
    with value.sessions.begin() as session:
        registered = register_local_indexing_service(
            session, successor, operation_key="cpu-test-register:" + uuid4().hex
        )
        activate_local_indexing_service(
            session,
            current_service,
            expected_resource_version=registered.status_after_operation.resource_version,
            operation_key="cpu-test-activate:" + uuid4().hex,
        )
    value.command = CpuEmbeddingFailureRecoveryCommand.model_validate(
        seal(
            dict(
                schema_version="embedding-encoding-recovery/3.0",
                record_type="RECOVER",
                workflow_id=value.workflow_id,
                workflow_request_sha256=value.request.request_sha256,
                command_id=command_id,
                lease_generation=1,
                native_intent_sha256=value.association.intent.intent_sha256,
                current_service=current_service.model_dump(mode="json"),
                root=cpu_root(native_job_id=value.association.intent.native_launch_job_id),
            ),
            "command_sha256",
        )
    )
    value.physical_calls, value.late_failure = 0, False

    @contextmanager
    def physical(proof):
        value.physical_calls += 1
        yield ResolvedRetiredNativeCpuIndexFailure(proof)
        if value.late_failure:
            raise ValueError("SYNTHETIC_ORIGINAL_CPU_CHANGED")

    monkeypatch.setattr(application, "read_retired_native_cpu_index_failure", physical)
    monkeypatch.setattr(application.os, "getresuid", lambda: (0, 0, 0))
    return value


def snapshot(case):
    with case.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, case.workflow_id)
        current = session.get(WorkflowCommandRecord, case.command.command_id)
        step = session.get(WorkflowStepRunRecord, case.step_id)
        ids = (
            case.association.intent.native_launch_job_id,
            *(owned.job_reference.job_id for owned in case.association.owned_jobs),
        )
        return dict(
            state=(workflow.state, workflow.stage, current.state, step.state),
            jobs=tuple(
                session.execute(
                    select(JobRecord.job_id, JobRecord.status, JobRecord.error_code)
                    .where(JobRecord.job_id.in_(ids))
                    .order_by(JobRecord.job_id)
                )
            ),
            preserved=tuple(
                session.execute(
                    select(
                        WorkflowCommandRecord.command_id,
                        WorkflowCommandRecord.state,
                        WorkflowCommandRecord.attempts,
                        WorkflowCommandRecord.lease_generation,
                    )
                    .where(
                        WorkflowCommandRecord.workflow_id == case.workflow_id,
                        WorkflowCommandRecord.command_id != case.command.command_id,
                    )
                    .order_by(WorkflowCommandRecord.command_id)
                )
            ),
            workflow_events=tuple(
                session.execute(
                    select(WorkflowEventRecord.event_type, WorkflowEventRecord.sequence)
                    .where(WorkflowEventRecord.workflow_id == case.workflow_id)
                    .order_by(WorkflowEventRecord.sequence)
                )
            ),
            job_events=tuple(
                session.execute(
                    select(JobEventRecord.job_id, JobEventRecord.event, JobEventRecord.sequence)
                    .where(JobEventRecord.job_id.in_(ids))
                    .order_by(JobEventRecord.job_id, JobEventRecord.sequence)
                )
            ),
        )


@pytest.mark.parametrize("cpu", [3, 128, "mixed"], indirect=True)
def test_exact_failed_cpu_closure_preserves_all_previous_commands_and_replays_read_only(cpu):
    before = snapshot(cpu)
    first = application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
    after = snapshot(cpu)
    assert first.state == "FAILED" and first.preserved_command_count == len(before["preserved"])
    assert after["state"] == ("FAILED",) * 4 and after["preserved"] == before["preserved"]
    assert all(
        row[1:] == ("FAILED", "EMBEDDING_NATIVE_KNOWN_FAILED_RETIRED") for row in after["jobs"]
    )
    assert application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command) == first
    assert snapshot(cpu) == after and cpu.physical_calls == 1


def test_late_cpu_identity_change_rolls_back_every_event_job_and_state(cpu):
    before = snapshot(cpu)
    cpu.late_failure = True
    with pytest.raises(ValueError, match="SYNTHETIC_ORIGINAL_CPU_CHANGED"):
        application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
    assert snapshot(cpu) == before
    cpu.late_failure = False
    assert (
        application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command).state
        == "FAILED"
    )


@pytest.mark.parametrize(
    "fault", ("generation", "intent", "request", "fresh", "output", "publication")
)
def test_changed_or_nonrecoverable_context_never_rewrites_cpu_history(cpu, fault):
    body = cpu.command.model_dump(mode="json")
    if fault == "generation":
        body["lease_generation"] += 1
    elif fault == "intent":
        body["native_intent_sha256"] = "sha256:" + "f" * 64
    elif fault == "request":
        body["workflow_request_sha256"] = "sha256:" + "f" * 64
    else:
        with cpu.sessions.begin() as session:
            if fault == "fresh":
                session.get(WorkflowCommandRecord, cpu.command.command_id).lease_expires_at = (
                    datetime.now(UTC) + timedelta(minutes=5)
                )
            elif fault == "output":
                session.get(WorkflowStepRunRecord, cpu.step_id).output_pointer_manifest = {
                    "synthetic": "existing"
                }
            else:
                native = session.get(JobRecord, cpu.association.intent.native_launch_job_id)
                session.add(
                    JobRecord(
                        job_id=new_job_id(),
                        protocol_version=native.protocol_version,
                        task_type="synthetic_conflicting_output",
                        request={},
                        request_hash=content_sha256({}),
                        idempotency_key=owned_embedding_publication_key(
                            cpu.association, workflow_request_sha256=cpu.request.request_sha256
                        ),
                        status="CREATED",
                        logical_artifact_id=new_logical_artifact_id(),
                        revision_id=new_revision_id(),
                    )
                )
    command = CpuEmbeddingFailureRecoveryCommand.model_validate(seal(body, "command_sha256"))
    before = snapshot(cpu)
    with pytest.raises(application.CpuIndexingFailureRecoveryError):
        application.recover_retired_cpu_indexing_workflow(cpu.sessions, command)
    assert snapshot(cpu) == before and cpu.physical_calls == 0


def test_concurrent_same_command_has_one_failure_receipt_and_no_duplicate_mutation(cpu):
    barrier = Barrier(2)

    def run(_):
        barrier.wait(timeout=10)
        try:
            return application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
        except application.CpuIndexingFailureRecoveryError as error:
            assert error.code.endswith("BUSY")
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, range(2)))
    result = application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
    assert any(item is not None for item in results)
    assert all(item is None or item == result for item in results)
    with cpu.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == cpu.workflow_id,
                    WorkflowEventRecord.event_type == application.CPU_FAILURE_RECOVERY_EVENT,
                )
            )
            == 1
        )


@pytest.mark.parametrize("cpu", [3, "mixed"], indirect=True)
def test_ordinary_concurrent_retry_creates_one_successor_and_preserves_failed_cpu_jobs(cpu):
    application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
    # Only admission/source/Workflow execution are synthetic; producer claims,
    # retry edges and competing fresh native launch identities use actual PG.
    candidates = []
    with cpu.sessions.begin() as session:
        for _ in range(2):
            launch = create_native_embedding_launch(
                session,
                request=cpu.request,
                workflow_id="workflow_" + uuid4().hex,
                step_run_id="steprun_" + uuid4().hex,
                command_id="wfcmd_" + uuid4().hex,
                runner_id="synthetic-cpu-retry",
                lease_generation=1,
            )
            scope = SimpleNamespace(
                request=cpu.request,
                plan=cpu.gate.fixture.plan,
                policy=cpu.gate.fixture.policy,
                association=SimpleNamespace(intent=launch.intent),
            )
            candidates.append(
                (
                    EmbeddingEncodingReservations(cpu.sessions, SyntheticAdmission(scope)),
                    launch.intent,
                )
            )
    requests = tuple(owned.request for owned in cpu.association.owned_jobs)
    barrier = Barrier(2)

    def run(candidate):
        owner, intent = candidate
        barrier.wait(timeout=10)
        return owner.retry_known_failed(requests, intent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, candidates))
    new_refs = {row.owned_job.job_reference for row in results[0]}
    old_refs = {owned.job_reference for owned in cpu.association.owned_jobs}
    assert new_refs == {row.owned_job.job_reference for row in results[1]}
    assert new_refs.isdisjoint(old_refs)
    assert sorted({row.status for row in rows}.pop() for rows in results) == ["BORROWED", "OWNED"]
    for (owner, intent), rows in zip(candidates, results, strict=True):
        assert owner.retry_known_failed(requests, intent) == rows
    with cpu.sessions.begin() as session:
        old_ids = tuple(ref.job_id for ref in old_refs)
        assert set(
            session.scalars(select(JobRecord.status).where(JobRecord.job_id.in_(old_ids)))
        ) == {"FAILED"}
        assert session.scalar(
            select(func.count())
            .select_from(JobEventRecord)
            .where(
                JobEventRecord.job_id.in_(old_ids),
                JobEventRecord.event == ENCODING_RETRY_SUCCESSOR_EVENT,
            )
        ) == len(old_refs)


def test_exact_terminal_replay_needs_no_new_physical_action(cpu, monkeypatch):
    first = application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command)
    before = snapshot(cpu)

    def forbidden(_):
        pytest.fail("historical exact replay must not depend on live unit retention")

    monkeypatch.setattr(application, "read_retired_native_cpu_index_failure", forbidden)
    assert application.recover_retired_cpu_indexing_workflow(cpu.sessions, cpu.command) == first
    assert snapshot(cpu) == before


def test_actual_runtime_database_role_cannot_recover_cpu_history(cpu):
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
    before = snapshot(cpu)
    try:
        with pytest.raises(ValueError, match="OWNER_REQUIRED"):
            application.recover_retired_cpu_indexing_workflow(
                build_session_factory(runtime), cpu.command
            )
    finally:
        runtime.dispose()
    assert snapshot(cpu) == before
