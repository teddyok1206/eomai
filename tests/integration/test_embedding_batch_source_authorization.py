"""Opt-in disposable real command/Job/Artifact roots; IAM and numerics remain synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_workflow.compiler import compile_definition_data
from eom_workflow.reference_query_execution import (
    parse_reference_query_execution_policy,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    ReferenceQueryBatchSource,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.reference_query_native_executor import CatalogNativeReferenceQueryExecutor
from eom_workflow_runner.reference_query_owner_admission import build_reference_query_native_input
from eom_workflow_runner.reference_query_step_execution import advance_reference_query_step
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    claim_command_candidate,
    command_lease_identity,
    peek_command_candidate,
)
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_submission import (
    prepare_query,
)
from tests.integration.test_reference_query_submission import (
    prepared_query as prepared_query,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_source_authorization import batch_for

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class _BeforeNumericalExecution(Exception):
    pass


@pytest.fixture
def authorized(prepared_query, monkeypatch):
    value = prepared_query
    owner, publisher = value.source.owner, value.source.publisher
    # Publish a distinct disposable policy with the actual fixed CPU recipe.
    # The old generic fixture is 300s/32 tasks/16MiB; never relax its production guard.
    body = value.source.policy.model_dump(mode="json")
    body["resource_profile"] = seal(
        body["resource_profile"]
        | {
            "timeout_seconds": 180,
            "tasks_max": 64,
            "output_max_bytes": 64 * 1024**2,
        },
        "resource_profile_sha256",
    )
    policy = parse_reference_query_execution_policy(seal(body, "policy_sha256"))
    published = LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).publish_reference_query_policy(
        policy,
        idempotency_key="batch-source-fixed-profile:" + value.key,
        created_at=policy.created_at,
    )
    owner.configuration = replace(
        owner.configuration,
        native_execution_policy=published.member,
        native_execution_policy_sha256=policy.policy_sha256,
    )
    executor = CatalogNativeReferenceQueryExecutor(
        owner=owner,
        publisher=publisher,
        launcher=SimpleNamespace(
            checkpoint_schema_version="native-reference-query-coordinator/1.1"
        ),
        source_commit="a" * 40,
    )
    # Physical runtime is deliberately absent. Exercise actual original allocation only.
    monkeypatch.setattr(executor, "evaluate", lambda _: SimpleNamespace(ready=True))
    value.executor = executor
    with publisher.sessions.begin() as session:
        submitted = prepare_query(value, session)
        workflow_id = submitted.workflow.workflow_id
        selected_request = parse_supported_reference_query_workflow_request(
            submitted.workflow.initial_request
        )
        definition = session.get(WorkflowDefinitionRecord, submitted.workflow.definition_id)
        compiled = compile_definition_data(
            definition.canonical_definition, definition.source_path, set()
        )
    with publisher.sessions.begin() as session:
        candidate = peek_command_candidate(
            session, family=CommandExecutionFamily.REFERENCE_QUERY, workflow_id=workflow_id
        )
        command = claim_command_candidate(
            session,
            candidate,
            runner_id="batch-source-disposable",
            lease_seconds=900,
            reference_query_owner=owner,
            reference_query_executor=executor,
        )
        assert command is not None
        lease = command_lease_identity(command)

    @contextmanager
    def fenced():
        with publisher.sessions.begin() as session:
            owner.fence_mutation(session, selected_request, lease)
            yield session
            owner.fence_mutation(session, selected_request, lease)

    def no_numerics(**kwargs):
        raise _BeforeNumericalExecution()

    monkeypatch.setattr(executor, "execute", no_numerics)
    with pytest.raises(_BeforeNumericalExecution):
        advance_reference_query_step(
            workflow=submitted.workflow,
            compiled=compiled,
            request=selected_request,
            lease=lease,
            owner=owner,
            executor=executor,
            fenced_transaction=fenced,
            actor_type="human",
            actor_id=selected_request.operator_audit.operator_id,
        )
    with fenced() as session:
        step = session.scalar(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.step_key == "encode_reference_query",
            )
        )
        launch = read_native_reference_query_launch(
            session,
            request=selected_request,
            workflow_id=workflow_id,
            step_run_id=step.step_run_id,
        )
        assert launch is not None
        current = owner.resolve_execution_sources(
            session,
            selected_request,
            lease,
            workflow_id=workflow_id,
            step_run_id=step.step_run_id,
        )
        native = build_reference_query_native_input(
            current, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
        )
        original = NativeReferenceQueryCoordinator(selected_request, launch).read(session)
        assert len(original.records) == 1 and original.state == "RUNNING"
    batch = batch_for(
        native,
        purpose="REFERENCE_QUERY",
        actor=selected_request.operator_audit.operator_id,
        partition=native.rows[0].encoding.storage_partition,
        policy=selected_request.context_request.policy_sha256,
        resources=selected_request.resource_profile,
    )
    binding = ReferenceQueryBatchSource(owner, selected_request, launch, lease, fenced)
    fence = CatalogEmbeddingBatchSourceAuthorization(batch, (binding,))
    return SimpleNamespace(
        fence=fence,
        owner=owner,
        publisher=publisher,
        lease=lease,
        request=selected_request,
        launch=launch,
        history=original,
    )


def test_disposable_concurrent_child_fences_use_original_command_and_leave_history_unchanged(
    authorized,
):
    barrier = Barrier(2)

    def authorize():
        barrier.wait(timeout=10)
        authorized.fence.authorize_batch()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(authorize) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    with authorized.publisher.sessions.begin() as session:
        current = NativeReferenceQueryCoordinator(authorized.request, authorized.launch).read(
            session
        )
        assert current == authorized.history
        command = session.get(WorkflowCommandRecord, authorized.lease.command_id)
        assert command.lease_generation == authorized.lease.lease_generation
        assert command.state == "LEASED"


def test_disposable_expired_command_revokes_child_fence_without_new_job_or_state_repair(authorized):
    authorized.fence.authorize_batch()
    with authorized.publisher.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, authorized.lease.command_id)
        command.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(RuntimeError):
        authorized.fence.authorize_batch()
    with authorized.publisher.sessions.begin() as session:
        assert (
            NativeReferenceQueryCoordinator(authorized.request, authorized.launch).read(session)
            == authorized.history
        )
