"""Real disposable workflow/Job transitions; root OS and immutable Artifact leaves synthetic."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.embedding_retired_failure_read import ResolvedRetiredEmbeddingFailure
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_SCHEMA_REF,
    NativeEmbeddingFailureRecoveryCommand,
)
from eom_workflow_runner import local_indexing_routed_preparation_recovery as application
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
from tests.integration.allocated_indexing_failure_fixtures import (
    parent_case,
    seed_allocated_execution,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = pytest.mark.integration


@pytest.fixture(params=["1.2", "3.0"])
def original(guarded_engine, monkeypatch, request):
    value = seed_allocated_execution(
        guarded_engine,
        request_family=request.param,
        preparation_only=True,
    )
    parent = parent_case(value.request, value.association, value.native_input)
    value.store = EmbeddingBatchPlanStore(parent.request, parent.selection, parent.policy)
    with value.sessions.begin() as session:
        value.store.allocate(session, parent.allocation)
        history = value.store.route(session, parent.route)
        transition_command(
            session.get(WorkflowCommandRecord, value.origin_command_id), CommandState.SUCCEEDED
        )
        advance, _ = enqueue_command(
            session,
            workflow_id=value.workflow_id,
            command_type=CommandType.ADVANCE_WORKFLOW,
            payload={},
            actor_type="local_indexing_service",
            actor_id=value.service.service_id,
            source="synthetic_routed_preparation",
            idempotency_key="routed-preparation:" + uuid4().hex,
        )
        value.advance_id = advance.command_id
    value.command = NativeEmbeddingFailureRecoveryCommand.model_validate(
        seal(
            dict(
                schema_version="embedding-encoding-recovery/1.0",
                record_type="RECOVER",
                workflow_id=value.workflow_id,
                workflow_request_sha256=value.request.request_sha256,
                command_id=value.origin_command_id,
                lease_generation=1,
                root=dict(
                    allocation_attempt_id=history.allocation.control_request.allocation_attempt_id,
                    invocation_id="f" * 32,
                    retirement_sha256="sha256:" + "f" * 64,
                    retired_at="2026-10-31T15:01:00Z",
                    parent_plan_job_id=history.job_id,
                    parent_request_sha256=parent.request.request_sha256,
                    original_outcome="FAILED",
                    stored_descriptors=0,
                ),
            ),
            "command_sha256",
        )
    )
    value.raw = canonical_json_bytes(value.command)
    value.evidence = ArtifactMemberPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        member_path=application.ROUTED_PREPARATION_RECOVERY_MEMBER,
        media_type="application/json",
        schema_ref=ENCODING_RECOVERY_SCHEMA_REF,
        sha256=sha256_bytes(value.raw),
    )
    value.late = False
    value.parent = parent
    value.physical_calls = 0

    @contextmanager
    def physical(proof):
        value.physical_calls += 1
        assert proof == value.command.root
        yield ResolvedRetiredEmbeddingFailure(
            proof, parent.allocation.control_request.message_sha256
        )
        if value.late:
            raise ValueError("SYNTHETIC_ORIGINAL_ROOT_CHANGED")

    class Reader:
        def prefetch(self, values):
            assert values == ((value.evidence.artifact_id, value.evidence.artifact_revision_id),)

        def read_pinned(self, **kwargs):
            assert kwargs["sha256"] == value.evidence.sha256
            return SimpleNamespace(payload=value.raw)

        def revalidate_provenance(self):
            pass

    monkeypatch.setattr(application.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(application, "read_retired_embedding_failure", physical)
    monkeypatch.setattr(application.PinnedArtifactReadContext, "for_session", lambda *a: Reader())
    monkeypatch.setattr(
        application,
        "resolve_embedding_batch_plan_controls",
        lambda *a: (parent.selection, parent.policy),
    )
    return value


def snapshot(case):
    with case.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, case.workflow_id)
        start = session.get(WorkflowCommandRecord, case.origin_command_id)
        advance = session.get(WorkflowCommandRecord, case.advance_id)
        step = session.get(WorkflowStepRunRecord, case.step_id)
        return dict(
            states=(workflow.state, workflow.stage, step.state, advance.state),
            failure=(workflow.failure_code, step.error_code),
            start=(
                start.state,
                start.processed_at,
                start.lease_generation,
                start.lease_token,
                start.lease_expires_at,
            ),
            parent=case.store.read(session),
            native=case.coordinator.read(session),
            events=tuple(
                session.execute(
                    select(WorkflowEventRecord.sequence, WorkflowEventRecord.event_type)
                    .where(
                        WorkflowEventRecord.workflow_id == case.workflow_id,
                    )
                    .order_by(WorkflowEventRecord.sequence)
                )
            ),
            native_events=tuple(
                session.execute(
                    select(JobEventRecord.sequence, JobEventRecord.event)
                    .where(
                        JobEventRecord.job_id == case.coordinator.intent.native_launch_job_id,
                    )
                    .order_by(JobEventRecord.sequence)
                )
            ),
            encodings=session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(
                    JobRecord.task_type == "embedding_encoding",
                )
            ),
        )


def test_original_successful_start_preserved_exact_replay_and_no_encoding(original):
    before = snapshot(original)
    result = application.recover_retired_routed_preparation(
        original.sessions, original.command, original.evidence
    )
    after = snapshot(original)
    assert after["states"] == ("FAILED", "FAILED", "FAILED", "CANCELLED")
    assert after["start"] == before["start"] and after["encodings"] == before["encodings"]
    assert after["native"].state == after["parent"].state == "FAILED"
    assert after["parent"].route == before["parent"].route and after["parent"].bound is None
    assert (
        application.recover_retired_routed_preparation(
            original.sessions, original.command, original.evidence
        )
        == result
    )
    assert snapshot(original) == after


def test_late_physical_change_rolls_back_all_transitions(original):
    before = snapshot(original)
    original.late = True
    with pytest.raises(ValueError, match="SYNTHETIC_ORIGINAL_ROOT_CHANGED"):
        application.recover_retired_routed_preparation(
            original.sessions, original.command, original.evidence
        )
    assert snapshot(original) == before


@pytest.mark.parametrize(
    "fault", ["claimed", "association", "bound", "publication", "payload", "generation", "nonroot"]
)
def test_nonrecoverable_is_not_reclassified(original, monkeypatch, fault):
    if fault == "claimed":
        with original.sessions.begin() as session:
            row = session.get(WorkflowCommandRecord, original.advance_id)
            row.state = "LEASED"
            row.attempts = row.lease_generation = 1
            row.lease_owner = "synthetic-live-runner"
            row.lease_expires_at = datetime.now(UTC)
    elif fault == "association":
        monkeypatch.setattr(
            application, "read_native_embedding_launch_association", lambda *a: original.association
        )
    elif fault == "bound":
        with original.sessions.begin() as session:
            original.store.bind(
                session,
                original.parent.bound,
                original.parent.batch,
                authorize_child=lambda child: None,
            )
    elif fault == "publication":
        monkeypatch.setattr(application, "batch_execution_publication_exists", lambda *a, **k: True)
    elif fault == "payload":
        original.raw = b"{}"
    elif fault == "generation":
        original.command = NativeEmbeddingFailureRecoveryCommand.model_validate(
            seal(
                original.command.model_dump(mode="json") | dict(lease_generation=2),
                "command_sha256",
            )
        )
    else:
        monkeypatch.setattr(application.os, "getresuid", lambda: (1000, 1000, 1000))
    before = snapshot(original)
    with pytest.raises(application.RoutedPreparationRecoveryError):
        application.recover_retired_routed_preparation(
            original.sessions, original.command, original.evidence
        )
    assert snapshot(original) == before


def test_nonowner_database_principal_cannot_mutate_even_with_root_os_proof(original):
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
    before = snapshot(original)
    try:
        with pytest.raises(ValueError, match="OWNER_REQUIRED"):
            application.recover_retired_routed_preparation(
                build_session_factory(runtime),
                original.command,
                original.evidence,
            )
    finally:
        runtime.dispose()
    assert snapshot(original) == before


def test_two_concurrent_maintainers_record_one_event(original):
    def run(_):
        try:
            return application.recover_retired_routed_preparation(
                original.sessions, original.command, original.evidence
            )
        except application.RoutedPreparationRecoveryError as error:
            assert error.code.endswith("BUSY")
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    result = application.recover_retired_routed_preparation(
        original.sessions, original.command, original.evidence
    )
    assert any(value is not None for value in results)
    assert all(value is None or value == result for value in results)
    with original.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == original.workflow_id,
                    WorkflowEventRecord.event_type == application.ROUTED_PREPARATION_RECOVERY_EVENT,
                )
            )
            == 1
        )
