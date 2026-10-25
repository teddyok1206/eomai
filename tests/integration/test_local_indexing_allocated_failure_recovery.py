"""Guarded PostgreSQL actual metadata recovery; original root OS and source admission synthetic."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from eom_catalog_service.embedding_retired_failure_read import ResolvedRetiredEmbeddingFailure
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.local_embedding_control_artifacts import (
    batch_execution_receipt_publication_key,
)
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.embedding_encoding_recovery import (
    encoding_failure_disposition,
    parse_supported_failure_recovery,
)
from eom_workflow_runner import local_indexing_allocated_failure_recovery as application
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.allocated_indexing_failure_fixtures import seed_allocated_failure
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = pytest.mark.integration


@pytest.fixture(params=["numerical_failed", "unpublished_success"])
def allocated(guarded_engine, monkeypatch, request):
    value = seed_allocated_failure(guarded_engine)
    if request.param == "unpublished_success":
        body = value.command.model_dump(mode="json")
        body["schema_version"] = "embedding-encoding-recovery/2.0"
        body["root"] |= dict(
            original_outcome="SUCCEEDED",
            controller_outcome="FAILED",
            controller_invocation_id="c" * 32,
        )
        value.command = parse_supported_failure_recovery(seal(body, "command_sha256"))
    value.late_failure = False
    value.barrier = None
    value.allocation_sha = value.parent.allocation.control_request.message_sha256

    @contextmanager
    def physical(proof):
        if value.barrier is not None:
            value.barrier.wait(timeout=10)
        yield ResolvedRetiredEmbeddingFailure(proof, value.allocation_sha)
        if value.late_failure:
            raise ValueError("SYNTHETIC_ORIGINAL_ROOT_CHANGED")

    monkeypatch.setattr(application, "read_retired_embedding_failure", physical)
    return value


def snapshot(case):
    with case.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, case.command.workflow_id)
        command = session.get(WorkflowCommandRecord, case.command.command_id)
        step = session.get(WorkflowStepRunRecord, case.step_id)
        ids = (
            case.association.intent.native_launch_job_id,
            *(j.job_reference.job_id for j in case.association.owned_jobs),
        )
        jobs = tuple(
            session.execute(
                select(JobRecord.job_id, JobRecord.status, JobRecord.error_code)
                .where(JobRecord.job_id.in_(ids))
                .order_by(JobRecord.job_id)
            )
        )
        return dict(
            states=(workflow.state, workflow.stage, command.state, step.state),
            jobs=jobs,
            original=(
                workflow.initial_request,
                command.lease_generation,
                command.lease_token,
                command.lease_expires_at,
                step.input_pointer_manifest,
            ),
            events=tuple(
                session.execute(
                    select(WorkflowEventRecord.event_type, WorkflowEventRecord.sequence)
                    .where(WorkflowEventRecord.workflow_id == workflow.workflow_id)
                    .order_by(WorkflowEventRecord.sequence)
                )
            ),
            job_events=tuple(
                session.execute(
                    select(JobEventRecord.job_id, JobEventRecord.sequence, JobEventRecord.event)
                    .where(JobEventRecord.job_id.in_(ids))
                    .order_by(JobEventRecord.job_id, JobEventRecord.sequence)
                )
            ),
            parent=case.store.read(session),
        )


def test_actual_exact_failure_replay_preserves_original_identity_and_successful_parent(allocated):
    before = snapshot(allocated)
    result = application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
    after = snapshot(allocated)
    assert result.state == "FAILED" and after["states"] == ("FAILED",) * 4
    assert (
        after["original"] == before["original"]
        and after["parent"] == before["parent"] == allocated.parent_history
    )
    assert {r.status for r in after["jobs"]} == {"FAILED"}
    assert {r.error_code for r in after["jobs"]} == {
        encoding_failure_disposition(allocated.command).code
    }
    assert (
        application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
        == result
    )
    assert snapshot(allocated) == after
    assert len(result.encoding_job_ids) == 2


def test_actual_late_root_change_rolls_back_all_workflow_native_encoding_events(allocated):
    before = snapshot(allocated)
    allocated.late_failure = True
    with pytest.raises(ValueError, match="SYNTHETIC_ORIGINAL_ROOT_CHANGED"):
        application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
    assert snapshot(allocated) == before
    allocated.late_failure = False
    assert (
        application.recover_retired_indexing_workflow(allocated.sessions, allocated.command).state
        == "FAILED"
    )


@pytest.mark.parametrize(
    "fault", ("generation", "fresh_lease", "parent", "request", "output", "allocation")
)
def test_actual_changed_generation_or_nonrecoverable_input_is_not_repaired(allocated, fault):
    body = allocated.command.model_dump(mode="json")
    if fault == "generation":
        body["lease_generation"] += 1
    elif fault == "parent":
        body["root"]["parent_request_sha256"] = "sha256:" + "0" * 64
    elif fault == "request":
        body["workflow_request_sha256"] = "sha256:" + "0" * 64
    elif fault == "allocation":
        allocated.allocation_sha = "sha256:" + "0" * 64
    else:
        with allocated.sessions.begin() as session:
            if fault == "fresh_lease":
                session.get(
                    WorkflowCommandRecord, allocated.command.command_id
                ).lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
            else:
                session.get(WorkflowStepRunRecord, allocated.step_id).output_pointer_manifest = {
                    "synthetic": "existing"
                }
    command = parse_supported_failure_recovery(seal(body, "command_sha256"))
    before = snapshot(allocated)
    with pytest.raises(application.AllocatedIndexingFailureRecoveryError):
        application.recover_retired_indexing_workflow(allocated.sessions, command)
    assert snapshot(allocated) == before


def test_actual_concurrent_recovery_has_one_canonical_failure_event(allocated):
    allocated.barrier = Barrier(2)

    def run():
        try:
            return application.recover_retired_indexing_workflow(
                allocated.sessions, allocated.command
            )
        except application.AllocatedIndexingFailureRecoveryError as error:
            assert error.code.endswith("BUSY")
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert any(r is not None for r in results)
    allocated.barrier = None
    result = application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
    assert all(r is None or r == result for r in results)
    with allocated.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == allocated.command.workflow_id,
                    WorkflowEventRecord.event_type == application.RECOVERY_EVENT,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id.in_(result.encoding_job_ids),
                    JobEventRecord.event
                    == encoding_failure_disposition(allocated.command).encoding_event,
                )
            )
            == 2
        )


def test_actual_nonowner_login_cannot_recover_even_with_a_proof_shaped_command(allocated):
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
    before = snapshot(allocated)
    try:
        with pytest.raises(ValueError, match="OWNER_REQUIRED"):
            application.recover_retired_indexing_workflow(
                build_session_factory(runtime), allocated.command
            )
    finally:
        runtime.dispose()
    assert snapshot(allocated) == before


def test_corrupt_parent_confirmation_is_not_a_completed_binding(allocated):
    # Deliberate corruption of only the disposable test history.
    with allocated.sessions.begin() as session:
        event = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == allocated.parent_history.job_id,
                JobEventRecord.sequence == 7,
            )
        )
        event.data = {"bound_record_sha256": "sha256:" + "0" * 64}
    with pytest.raises(ValueError):
        application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
    with allocated.sessions.begin() as session:
        assert session.get(WorkflowInstanceRecord, allocated.command.workflow_id).state == "RUNNING"
        assert (
            session.get(JobRecord, allocated.association.intent.native_launch_job_id).status
            == "RUNNING"
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == allocated.command.workflow_id,
                    WorkflowEventRecord.event_type == application.RECOVERY_EVENT,
                )
            )
            == 0
        )


@pytest.mark.parametrize("publication_state", ["CREATED", "SUCCEEDED"])
def test_existing_or_incomplete_publication_cannot_be_failed_and_retried(
    allocated, publication_state
):
    key = batch_execution_receipt_publication_key(
        allocated.parent.request.request_sha256, allocated.parent_history.allocation.record_sha256
    )
    with allocated.sessions.begin() as session:
        session.add(
            JobRecord(
                job_id=new_job_id(),
                protocol_version="embedding-encoding-job/1.0",
                task_type="control_embedding_batch_execution_receipt",
                idempotency_key=key,
                request_hash="sha256:" + "e" * 64,
                request={"fixture": "existing publication"},
                status=publication_state,
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )
        )
    before = snapshot(allocated)
    with pytest.raises(
        application.AllocatedIndexingFailureRecoveryError, match="PUBLICATION_EXISTS"
    ):
        application.recover_retired_indexing_workflow(allocated.sessions, allocated.command)
    assert snapshot(allocated) == before
