"""Opt-in disposable PostgreSQL QUERY Job/Artifact transactions, never live authority.

Current IAM/Workflow SQL and numerical observations remain explicit synthetic
seams. The existing marker/owner/schema/head guard is mandatory for all writes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    native_reference_query_launch_key,
    read_native_reference_query_launch,
)
from eom_orchestrator.settings import Settings
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    parse_reference_query_execution_policy,
    parse_reference_query_workflow_request,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_admission import ResolvedReferenceQueryAdmission
from eom_workflow_runner.reference_query_step_execution import advance_reference_query_step
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    CommandLeaseIdentity,
    claim_command_candidate,
    peek_command_candidate,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_submission import atomic as atomic
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_consumer_read import make_completed_read_case, read
from tests.unit.test_reference_query_native_executor import ExecutorCase, make_executor_case

pytestmark = pytest.mark.integration


@pytest.fixture
def query(guarded_engine: Engine, tmp_path: Path, monkeypatch) -> ExecutorCase:
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    artifacts, workspace = tmp_path / "artifacts", tmp_path / "workspace"
    artifacts.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=artifacts, workspace_root=workspace
        ),
    )
    value = make_executor_case(tmp_path, monkeypatch, publisher=publisher)
    # The shared disposable DB retains prior tests; every context is a new identity.
    value.workflow.workflow_id, value.step.step_run_id = (
        "workflow_" + uuid4().hex,
        "steprun_" + uuid4().hex,
    )
    return value


def assert_exact_completed_producers(value: ExecutorCase) -> None:
    history = value.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    allocation = history.records[0].payload
    assert isinstance(allocation, NativeQueryAllocation)
    ids = (
        history.launch.native_launch_job_id,
        allocation.query_producer.job_id,
        allocation.receipt_producer.job_id,
    )
    with value.publisher.sessions.begin() as session:
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(jobs) == 3 and all(job.status == "SUCCEEDED" for job in jobs)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id.in_(ids))
            )
            == 2
        )


def test_postgres_query_checkpoint_commit_receipt_and_exact_replay(query):
    output = query.execute()
    assert isinstance(output, ReferenceQueryStepOutput)
    history = query.history()
    assert query.execute(generation=2) == output
    assert query.history() == history and len(query.runs) == 1
    assert_exact_completed_producers(query)


def test_postgres_completed_query_read_uses_original_job_and_canonical_members(query, monkeypatch):
    current = make_completed_read_case(query, monkeypatch)
    first = read(current)
    assert read(current) == first and len(query.runs) == 1
    assert first.request.job_id == query.history().launch.native_launch_job_id
    assert_exact_completed_producers(query)


@pytest.mark.parametrize(
    "boundary", ("query_before", "query_after", "receipt_before", "receipt_after")
)
def test_postgres_crash_recovery_never_reencodes_or_reallocates(query, monkeypatch, boundary):
    owner_type = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    method = owner_type.publish_reference_query

    def crash(self, *args, **kwargs):
        if boundary.endswith("after"):
            method(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic owner death; not a new inference grant")

    with monkeypatch.context() as patch:
        patch.setattr(owner_type, "publish_reference_query", crash)
        with pytest.raises(KeyboardInterrupt):
            query.execute()
    original = query.history()
    assert len(original.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(query.execute(generation=2), ReferenceQueryStepOutput)
    assert query.history().records[: len(original.records)] == original.records
    assert len(query.runs) == 1
    assert_exact_completed_producers(query)


@pytest.mark.parametrize("fault", ("none", "allocation_before", "allocation_after", "late_root"))
def test_postgres_step_start_and_original_allocation_commit_or_rollback_together(
    query, atomic, monkeypatch, fault
):
    """Actual Workflow/step/Job root; explicit synthetic IAM/source/lease-admission seams."""
    from eom_workflow.compiler import compile_definition_data

    # These control/source seams are synthetic, but their released pointer/hash
    # closure must still agree with the actual compiled Workflow definition.
    policy = parse_reference_query_execution_policy(
        seal(
            query.sources.policy.model_dump(mode="json")
            | {"workflow_definition_sha256": atomic.definition.definition_hash},
            "policy_sha256",
        )
    )
    policy_member = query.request.native_execution_policy.model_copy(
        update={
            "artifact_id": "artifact_" + uuid4().hex,
            "artifact_revision_id": "rev_" + uuid4().hex,
            "sha256": sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json"))),
        }
    )
    request = parse_reference_query_workflow_request(
        seal(
            query.request.model_dump(mode="json")
            | {
                "workflow_definition_sha256": atomic.definition.definition_hash,
                "operator_audit": atomic.scope.request.operator_audit.model_dump(mode="json"),
                "native_execution_policy": policy_member.model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    query.request = request
    query.sources = replace(query.sources, request=request, policy=policy)
    query.owner.configuration = replace(
        query.owner.configuration,
        native_execution_policy=policy_member,
        native_execution_policy_sha256=policy.policy_sha256,
    )
    atomic.scope = ResolvedReferenceQueryAdmission(
        request, query.sources.policy, query.sources.bundle
    )

    def current(session, actual):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert actual == request
        return atomic.scope

    atomic.owner.resolve_submission.side_effect = current
    atomic.owner.resolve_claim.return_value = atomic.scope
    with Session(atomic.engine, expire_on_commit=False) as session, session.begin():
        submitted = atomic.submit(session)
        workflow_id = submitted.workflow.workflow_id
    with Session(atomic.engine, expire_on_commit=False) as session, session.begin():
        candidate = peek_command_candidate(
            session, family=CommandExecutionFamily.REFERENCE_QUERY, workflow_id=workflow_id
        )
        assert candidate is not None
        command = claim_command_candidate(
            session,
            candidate,
            runner_id="synthetic-atomic-allocation",
            lease_seconds=900,
            reference_query_owner=atomic.owner,
            reference_query_executor=query.service,
        )
        assert command is not None
        lease = CommandLeaseIdentity(
            command.command_id, command.lease_owner, command.lease_token, command.lease_generation
        )
    compiled = compile_definition_data(
        atomic.definition.canonical_definition, atomic.definition.source_path, set()
    )

    @contextmanager
    def fenced() -> Iterator[Session]:
        assert query.root_depth == 0
        query.root_depth += 1
        try:
            with Session(atomic.engine, expire_on_commit=False) as session, session.begin():
                yield session
                if fault == "late_root":
                    raise ValueError("synthetic late current fence denial")
        finally:
            query.root_depth -= 1

    observed = []

    def physical(**kwargs):
        assert query.root_depth == 0
        with Session(atomic.engine) as session, session.begin():
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            step = session.get(WorkflowStepRunRecord, kwargs["step"].step_run_id)
            assert workflow.state == step.state == "RUNNING"
            launch = read_native_reference_query_launch(
                session, request=request, workflow_id=workflow_id, step_run_id=step.step_run_id
            )
            assert launch is not None
            history = NativeReferenceQueryCoordinator(request, launch).read(session)
            assert len(history.records) == 1 and history.records[0].record_type == "ALLOCATION"
            observed.append(launch)
        raise KeyboardInterrupt("synthetic process death before physical launch")

    original_allocate = query.service.allocate_execution
    attempted_steps = []

    def allocate(**kwargs):
        attempted_steps.append(kwargs["step"].step_run_id)
        if fault == "allocation_before":
            raise ValueError("synthetic allocation admission failure")
        result = original_allocate(**kwargs)
        if fault == "allocation_after":
            raise ValueError("synthetic failure after allocation before root commit")
        return result

    monkeypatch.setattr(query.service, "allocate_execution", allocate)
    monkeypatch.setattr(query.service, "execute", physical)
    with pytest.raises(KeyboardInterrupt if fault == "none" else ValueError):
        advance_reference_query_step(
            workflow=submitted.workflow,
            compiled=compiled,
            request=request,
            lease=lease,
            owner=atomic.owner,
            executor=query.service,
            fenced_transaction=fenced,
            actor_type="human",
            actor_id=request.operator_audit.operator_id,
        )
    with Session(atomic.engine) as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        steps = tuple(
            session.scalars(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id
                )
            )
        )
        if fault == "none":
            assert workflow.state == "RUNNING" and len(steps) == len(observed) == 1
            launch = read_native_reference_query_launch(
                session,
                request=request,
                workflow_id=workflow_id,
                step_run_id=steps[0].step_run_id,
            )
            assert launch == observed[0]
        else:
            assert workflow.state == "REQUESTED" and steps == () and observed == []
            assert not session.scalar(
                select(JobRecord.job_id).where(
                    JobRecord.idempotency_key.in_(
                        native_reference_query_launch_key(
                            workflow_id, step_id, request.request_sha256
                        )
                        for step_id in attempted_steps
                    )
                )
            )
    assert query.runs == []
    query.launcher.run.assert_not_called()
