"""Disposable PostgreSQL original-publication/replay; synthetic source and numerical leaves."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_identity_service import activate_local_indexing_service, register_local_indexing_service
from eom_identity_service.local_indexing_service_models import (
    LocalIndexingServiceRecord,
    LocalIndexingServiceRevisionRecord,
)
from eom_operator_identity import local_indexing_service_reference
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import read_native_embedding_launch
from eom_workflow.index_publication_recovery import IndexPublicationRecoveryCommand
from eom_workflow.local_embedding_request_v2 import supported_local_embedding_request_service
from eom_workflow_runner import index_publication_recovery as recovery
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_command_fence import NativeCommandMutationFence
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_local_indexing_service_registry import identity
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def interrupted(execution, monkeypatch):
    started = execution.start()
    original = execution.owner.catalog.resolve_optional_index_publication
    monkeypatch.setattr(
        execution.owner.catalog,
        "resolve_optional_index_publication",
        Mock(side_effect=RuntimeError("publication interrupted")),
    )
    with pytest.raises(RuntimeError, match="publication interrupted"):
        execution.advance(*started)
    monkeypatch.setattr(execution.owner.catalog, "resolve_optional_index_publication", original)
    service = supported_local_embedding_request_service(execution.request)
    with execution.sessions.begin() as session:
        head = session.get(LocalIndexingServiceRecord, service.service_id)
        previous = (
            None
            if head is None
            else session.get(LocalIndexingServiceRevisionRecord, head.current_revision_id)
        )
        current_identity = identity(
            service_id=service.service_id,
            previous_service_revision_id=None if previous is None else previous.service_revision_id,
            revision_number=1 if previous is None else previous.revision_number + 1,
        )
        registered = register_local_indexing_service(
            session, current_identity, operation_key="recovery-test:" + uuid4().hex
        )
        current = local_indexing_service_reference(current_identity)
        activate_local_indexing_service(
            session,
            current,
            expected_resource_version=registered.status_after_operation.resource_version,
            operation_key="recovery-test:" + uuid4().hex,
        )
    with execution.sessions.begin() as session:
        step = session.scalar(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == started[0].workflow_id
            )
        )
        launch = read_native_embedding_launch(
            session,
            request=execution.request,
            workflow_id=started[0].workflow_id,
            step_run_id=step.step_run_id,
        )
        history = NativeEmbeddingCoordinator(launch.intent, execution.request).read(session)
        assert len(history.records) == 2
        body = dict(
            schema_version="index-publication-recovery/1.0",
            workflow_id=started[0].workflow_id,
            workflow_request_sha256=execution.request.request_sha256,
            native_intent_sha256=launch.intent.intent_sha256,
            registration_request_sha256=history.records[
                1
            ].payload.registration_command.request_sha256,
            current_service=current.model_dump(mode="json"),
            current_policy_revision_id="accessrev_" + "1" * 32,
            current_policy_sha256="sha256:" + "1" * 64,
        )
    command = IndexPublicationRecoveryCommand.model_validate(
        body | {"command_sha256": content_sha256(body)}
    )
    monkeypatch.setattr(recovery.os, "getresuid", lambda: (0, 0, 0))
    return execution, started, recovery.PreparedIndexRecoveryFence(command)


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_same_prepared_publication_completes_and_replays_without_numerical_execution(interrupted):
    case, started, fence = interrupted
    before = case.launcher.forwards
    owner = recovery.PreparedIndexPublicationExecutor(case.owner, case.publisher, fence)
    assert case.advance(*started, selected_executor=owner)
    case.finish(*started, selected_executor=owner)
    case.finish(*started, selected_executor=owner)
    assert case.launcher.forwards == before == 1
    with case.sessions.begin() as session:
        fence(session)
        assert session.get(WorkflowInstanceRecord, started[0].workflow_id).state == "COMPLETED"


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_exact_publication_fence_rejects_parallel_owner_and_wrong_hash(interrupted):
    case, _started, fence = interrupted
    with case.sessions.begin() as session:
        fence(session)

        def competitor():
            with case.sessions.begin() as other:
                recovery.PreparedIndexRecoveryFence(fence.command)(other)

        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(DBAPIError):
            pool.submit(competitor).result(timeout=15)
    body = fence.command.model_dump(mode="json") | {
        "registration_request_sha256": "sha256:" + "e" * 64
    }
    body["command_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "command_sha256"}
    )
    wrong = recovery.PreparedIndexRecoveryFence(
        IndexPublicationRecoveryCommand.model_validate(body)
    )
    with case.sessions.begin() as session, pytest.raises(ValueError, match="SCOPE_INVALID"):
        wrong(session)
    assert case.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_failed_history_is_never_reinterpreted(interrupted):
    case, started, fence = interrupted
    # Isolated negative fixture only; never mutate a production failure.
    with case.sessions.begin() as session:
        session.get(WorkflowInstanceRecord, started[0].workflow_id).state = "FAILED"
    with case.sessions.begin() as session, pytest.raises(ValueError, match="SCOPE_INVALID"):
        fence(session)


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_original_expired_command_reclaim_terminal_and_same_operation_replay(
    interrupted, monkeypatch
):
    case, started, fence = interrupted
    executor = recovery.PreparedIndexPublicationExecutor(case.owner, case.publisher, fence)
    monkeypatch.setattr(
        recovery, "build_publication_recovery_executor", lambda *args, **kwargs: executor
    )
    command_fence = NativeCommandMutationFence()

    def current_sources(session, request, lease):
        command_fence.acquire(session, request.request_sha256, lease)
        return case.owner.resolve_sources(session, request)

    monkeypatch.setattr(case.owner, "resolve_mutation_sources", current_sources)
    with case.sessions.begin() as session:
        session.get(WorkflowCommandRecord, started[1].command_id).lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    result = recovery.recover_prepared_index_publication(
        case.publisher, fence.command, source_commit="c" * 40
    )
    assert result.state == "COMPLETED" and result.resumed_commands >= 1
    repeated = recovery.recover_prepared_index_publication(
        case.publisher, fence.command, source_commit="c" * 40
    )
    assert repeated.index_revision_id == result.index_revision_id and repeated.resumed_commands == 0
    assert case.launcher.forwards == 1
