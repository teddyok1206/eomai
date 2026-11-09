"""Disposable PostgreSQL original-publication/replay; synthetic source and numerical leaves."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.registered_public_solution_registry import (
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import register_embedding_index
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index_revision,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_identity_service import activate_local_indexing_service, register_local_indexing_service
from eom_identity_service.local_indexing_service_models import (
    LocalIndexingServiceRecord,
    LocalIndexingServiceRevisionRecord,
)
from eom_operator_identity import local_indexing_service_reference
from eom_orchestrator import native_embedding_index_handoff as handoff
from eom_orchestrator.embedding_artifact_store import EmbeddingIndexPublicationScope
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import read_native_embedding_launch
from eom_workflow.index_publication_recovery import (
    IndexPublicationRecoveryCommand,
    UnpreparedIndexPublicationRecoveryCommand,
)
from eom_workflow.local_embedding_request_v2 import supported_local_embedding_request_service
from eom_workflow.local_embedding_source_plan_v4 import parse_local_embedding_source_plan_v4
from eom_workflow_runner import index_publication_recovery as recovery
from eom_workflow_runner import index_publication_successor as successor
from eom_workflow_runner.local_embedding_execution_context import native_embedding_registry_scope
from eom_workflow_runner.local_embedding_publications import native_embedding_publications
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
def interrupted(execution, monkeypatch, tmp_path):
    started = execution.start()
    unprepared = execution.request.schema_version == "local-embedding-workflow-request/4.0"
    if unprepared:
        # Reproduce the live drift: selected request4, whole population index5.
        original_basis = execution.owner.catalog.prepare_registered_public_index_basis

        def upgraded_basis(*args, **kwargs):
            basis = original_basis(*args, **kwargs)
            body = basis.full_plan.model_dump(mode="json", exclude={"plan_sha256"})
            body["schema_version"] = "local-embedding-source-plan/5.0"
            plan = parse_local_embedding_source_plan_v4(
                body | {"plan_sha256": content_sha256(body)}
            )
            return replace(basis, full_plan=plan)

        monkeypatch.setattr(
            execution.owner.catalog, "prepare_registered_public_index_basis", upgraded_basis
        )
    original = execution.owner.catalog.resolve_optional_index_publication
    monkeypatch.setattr(
        execution.owner.catalog,
        "resolve_optional_index_publication",
        Mock(side_effect=RuntimeError("publication interrupted")),
    )
    error_type, message = (
        (ValueError, "REGISTERED_PUBLIC_REGISTRATION_SCHEMA_INVALID")
        if unprepared
        else (RuntimeError, "publication interrupted")
    )
    with pytest.raises(error_type, match=message):
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
        assert len(history.records) == (1 if unprepared else 2)
        body = dict(
            schema_version="index-publication-recovery/2.0"
            if unprepared
            else "index-publication-recovery/1.0",
            workflow_id=started[0].workflow_id,
            workflow_request_sha256=execution.request.request_sha256,
            native_intent_sha256=launch.intent.intent_sha256,
            current_service=current.model_dump(mode="json"),
            current_policy_revision_id="accessrev_" + "1" * 32,
            current_policy_sha256="sha256:" + "1" * 64,
        )
        if unprepared:
            staged = (
                handoff.OWNER_ROOT
                / launch.intent.native_launch_job_id.removeprefix("job_")
                / "index.json"
            )
            body.update(
                allocation_checkpoint_sha256=history.records[0].checkpoint_sha256,
                staged_index_member_sha256=sha256_bytes(staged.read_bytes()),
            )
        else:
            body["registration_request_sha256"] = history.records[
                1
            ].payload.registration_command.request_sha256
    command_type = (
        UnpreparedIndexPublicationRecoveryCommand if unprepared else IndexPublicationRecoveryCommand
    )
    command = command_type.model_validate(body | {"command_sha256": content_sha256(body)})
    monkeypatch.setattr(recovery.os, "getresuid", lambda: (0, 0, 0))
    # Isolated filesystem root only. Recovery must traverse the actual staged
    # metadata boundary, not the service-owned workspace creation function.
    monkeypatch.setattr(
        handoff,
        "TemporaryDirectory",
        lambda **kw: TemporaryDirectory(prefix=kw["prefix"], dir=tmp_path),
    )
    return execution, started, recovery.PreparedIndexRecoveryFence(command)


@pytest.mark.parametrize(
    "execution", ["native_office_public", "native_office_public_cuda"], indirect=True
)
def test_same_prepared_publication_completes_and_replays_without_numerical_execution(interrupted):
    case, started, fence = interrupted
    before = case.launcher.forwards
    owner = recovery.PreparedIndexPublicationExecutor(
        case.owner, case.publisher, fence, device=case.request.space.runtime.device
    )
    assert case.advance(*started, selected_executor=owner)
    case.finish(*started, selected_executor=owner)
    case.finish(*started, selected_executor=owner)
    assert case.launcher.forwards == before == 1
    with case.sessions.begin() as session:
        fence(session)
        assert session.get(WorkflowInstanceRecord, started[0].workflow_id).state == "COMPLETED"


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_recovery_materialization_is_exact_temporary_and_preserves_original(interrupted):
    case, _started, fence = interrupted
    with case.sessions.begin() as session:
        fence(session)
        _, _, _, coordinator, history = fence.original(session)
    execution_id = coordinator.intent.native_launch_job_id.removeprefix("job_")
    original = handoff.OWNER_ROOT / execution_id / "index.json"
    before = original.stat()
    digest = history.records[1].payload.registration_command.index_manifest.sha256
    with handoff.materialize_prepared_index_publication(execution_id, digest) as (directory, index):
        assert directory != original.parent and directory.exists()
        assert (
            index.index_revision_id
            == history.records[1].payload.registration_command.index_revision_id
        )
    assert not directory.exists()
    after = original.stat()
    # Reading may legitimately update atime; identity/content metadata must not change.
    for field in (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_gid",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    ):
        assert getattr(after, field) == getattr(before, field)
    with (
        pytest.raises(ValueError, match="PREPARED_HASH_MISMATCH"),
        handoff.materialize_prepared_index_publication(execution_id, "sha256:" + "0" * 64),
    ):
        pytest.fail("wrong hash must not enter publication")
    assert case.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["native_office_public", "registered_public"], indirect=True)
def test_exact_publication_fence_rejects_parallel_owner_and_wrong_hash(interrupted):
    case, _started, fence = interrupted
    with case.sessions.begin() as session:
        fence(session)

        def competitor():
            with case.sessions.begin() as other:
                recovery.PreparedIndexRecoveryFence(fence.command)(other)

        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(DBAPIError):
            pool.submit(competitor).result(timeout=15)
    unprepared = isinstance(fence.command, UnpreparedIndexPublicationRecoveryCommand)
    field = "allocation_checkpoint_sha256" if unprepared else "registration_request_sha256"
    body = fence.command.model_dump(mode="json") | {field: "sha256:" + "e" * 64}
    body["command_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "command_sha256"}
    )
    wrong = recovery.PreparedIndexRecoveryFence(type(fence.command).model_validate(body))
    with case.sessions.begin() as session, pytest.raises(ValueError, match="SCOPE_INVALID"):
        wrong(session)
    assert case.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["native_office_public"], indirect=True)
def test_recovery_fence_is_admitted_in_root_then_retained_across_savepoints(interrupted):
    case, _started, fence = interrupted
    with case.sessions.begin() as session:
        with session.begin_nested(), pytest.raises(ValueError, match="SCOPE_INVALID"):
            fence(session)
        fence(session)
        nested = session.begin_nested()
        fence(session)
        nested.rollback()
        fence(session)
    with (
        case.sessions.begin() as session,
        session.begin_nested(),
        pytest.raises(ValueError, match="SCOPE_INVALID"),
    ):
        fence(session)
    assert case.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["native_office_public", "registered_public"], indirect=True)
def test_failed_history_is_never_reinterpreted(interrupted):
    case, started, fence = interrupted
    # Isolated negative fixture only; never mutate a production failure.
    with case.sessions.begin() as session:
        session.get(WorkflowInstanceRecord, started[0].workflow_id).state = "FAILED"
    with case.sessions.begin() as session, pytest.raises(ValueError, match="SCOPE_INVALID"):
        fence(session)


@pytest.mark.parametrize("execution", ["registered_public"], indirect=True)
def test_unprepared_stage_is_parsed_once_per_locked_root_not_per_registry_fence(
    interrupted, monkeypatch
):
    case, _, fence = interrupted
    materialize = Mock(wraps=recovery.materialize_prepared_index_publication)
    monkeypatch.setattr(recovery, "materialize_prepared_index_publication", materialize)
    with case.sessions.begin() as session:
        fence(session)
        for _ in range(12):
            fence(session)
            fence.original(session)
        with session.begin_nested():
            fence(session)
        assert materialize.call_count == 1
    # Root-local admission is not a cross-transaction cache or retry bypass.
    with case.sessions.begin() as session:
        fence(session)
        assert materialize.call_count == 2
    materialize.side_effect = ValueError("NATIVE_INDEX_PREPARED_HASH_MISMATCH")
    with case.sessions.begin() as session, pytest.raises(ValueError, match="HASH_MISMATCH"):
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
    # This fixture deliberately supplies operator-style synthetic IAM. Use its
    # real Catalog basis for the read, not a fabricated empty predecessor.
    monkeypatch.setattr(
        case.owner.catalog,
        "resolve_indexing_namespace_predecessor",
        lambda s, c, q: case.owner.catalog.prepare_registered_public_index_basis(s, c, q).previous,
    )
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


@pytest.mark.parametrize("execution", ["native_office_public", "registered_public"], indirect=True)
def test_newer_publication_recovery_preserves_rows_and_replays(interrupted, monkeypatch, tmp_path):
    case, started, fence = interrupted
    # A competing owner publishes a real partial index after the old owner's
    # prepared checkpoint, using the same verified numeric file set.
    publications = native_embedding_publications(case.publisher, "a" * 40)
    with case.sessions.begin() as session:
        fence(session)
        request, _, _, coordinator, history = fence.original(session)
        unprepared = isinstance(fence.command, UnpreparedIndexPublicationRecoveryCommand)
        command = None if unprepared else history.records[1].payload.registration_command
        workspace = handoff.OWNER_ROOT / coordinator.intent.native_launch_job_id.removeprefix(
            "job_"
        )
        original = publications.artifacts.read_staged_registered_public_index(
            workspace=workspace,
            expected_sha256=fence.command.staged_index_member_sha256
            if unprepared
            else command.index_manifest.sha256,
        )
        caller = case.owner.registry_caller(request)
        basis = case.owner.catalog.prepare_registered_public_index_basis(
            session, caller, native_embedding_registry_scope(request)
        )
        if unprepared:
            from eom_protocol.artifact_members import ArtifactMemberPointer

            allocation = history.records[0].payload
            value = dict(
                schema_version="embedding-registry-registration-command/5.0",
                operation="REGISTER_EMBEDDING_INDEX",
                operation_key="test:prepared:" + uuid4().hex,
                corpus_id=request.corpus_id,
                namespace=request.namespace.model_dump(mode="json"),
                index_id=original.index_id,
                index_revision_id=original.index_revision_id,
                index_manifest=ArtifactMemberPointer(
                    artifact_id=allocation.index_producer.artifact_id,
                    artifact_revision_id=allocation.index_producer.artifact_revision_id,
                    member_path="index.json",
                    media_type="application/json",
                    schema_ref="eom://schemas/knowledge/embedding-index-manifest/5.0",
                    sha256=fence.command.staged_index_member_sha256,
                ).model_dump(mode="json"),
                index_sha256=original.index_sha256,
                graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=request.access_policy_revision_id,
                policy_sha256=request.access_policy_sha256,
                expected_current_index_revision_id=None,
                expected_lock_version=basis.expected_lock_version,
                source_set_sha256=basis.full_plan.source_set_sha256,
                binding_set_sha256=content_sha256([b.binding_sha256 for b in original.bindings]),
                eligible_source_count=len(basis.full_plan.sources),
                binding_count=len(original.bindings),
                requested_at=allocation.created_at.isoformat().replace("+00:00", "Z"),
            )
            command = RegisterPublicSolutionIndexCommandV4.model_validate(
                value | {"request_sha256": content_sha256(value)}
            )
        resolved = case.owner.catalog.resolve_prepared_index(session, caller, command, original)
        subset = assemble_registered_public_solution_index_revision(
            basis.full_plan,
            available_rows=(
                RegisteredEmbeddingRow(original.bindings[0].encoding, original.bindings[0].row_ref),
            ),
            shards=resolved.shards,
            index_id=original.index_id,
            index_revision_id="embeddingindexrev_" + uuid4().hex,
            previous_manifest=None,
            created_at=datetime.now(UTC),
        )
        local = tmp_path / "competing"
        local.mkdir(mode=0o700)
        saved = publications.artifacts.publish_index(
            index=subset.index,
            shards=subset.shards,
            previous=None,
            scope=EmbeddingIndexPublicationScope(
                request.graph_snapshot,
                request.access_policy_revision_id,
                request.access_policy_sha256,
            ),
            workspace=local,
        )
        body = command.model_dump(mode="json") | dict(
            operation_key="competing:" + uuid4().hex,
            index_revision_id=subset.index.index_revision_id,
            index_sha256=subset.index.index_sha256,
            index_manifest=saved.index_manifest.model_dump(mode="json"),
            binding_count=len(subset.index.bindings),
            binding_set_sha256=content_sha256([b.binding_sha256 for b in subset.index.bindings]),
        )
        body["request_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "request_sha256"}
        )
        register_embedding_index(
            session,
            caller,
            RegisterPublicSolutionIndexCommandV4.model_validate(body),
            case.owner.catalog,
        )
    before_launches = case.launcher.forwards
    original_registration = case.owner.catalog.resolve_registration

    def fenced_registration(session, caller, command):
        # The real Catalog rechecks maintenance authority inside the Registry's
        # uniqueness savepoint, after admission in the outer transaction.
        fence(session)
        return original_registration(session, caller, command)

    monkeypatch.setattr(case.owner.catalog, "resolve_registration", fenced_registration)
    executor = recovery.PreparedIndexPublicationExecutor(case.owner, case.publisher, fence)
    monkeypatch.setattr(successor, "build_publication_recovery_executor", lambda *a, **kw: executor)
    monkeypatch.setattr(
        successor,
        "TemporaryDirectory",
        lambda **kw: TemporaryDirectory(prefix=kw["prefix"], dir=tmp_path),
    )
    with case.sessions.begin() as session:
        basis = case.owner.catalog.prepare_registered_public_index_basis(
            session,
            case.owner.registry_caller(case.request),
            native_embedding_registry_scope(case.request),
        )
        assert basis.previous is not None
        previous = basis.previous[1]
        session.get(WorkflowCommandRecord, started[1].command_id).lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    plan = successor.PreparedIndexSuccessorPlan(
        recovery=fence.command,
        expected_index_revision_id=previous.index_revision_id,
        expected_index_sha256=previous.index_sha256,
        created_at=datetime.now(UTC),
        source_commit="c" * 40,
    )
    wrong = plan.model_copy(update={"expected_index_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="SUCCESSOR_INVALID"):
        successor.publish_recovered_index_successor(case.publisher, wrong)
    retirement = "retire_unprepared_publication" if unprepared else "retire_replaced_publication"
    retire = getattr(NativeEmbeddingCoordinator, retirement)
    monkeypatch.setattr(
        NativeEmbeddingCoordinator,
        retirement,
        Mock(side_effect=RuntimeError("after index registration")),
    )
    with pytest.raises(RuntimeError, match="after index registration"):
        successor.publish_recovered_index_successor(case.publisher, plan)
    monkeypatch.setattr(NativeEmbeddingCoordinator, retirement, retire)
    # Artifact commit may survive; index head/old workflow must roll back together.
    with case.sessions.begin() as session:
        assert session.get(WorkflowInstanceRecord, started[0].workflow_id).state == "RUNNING"
        same = case.owner.catalog.prepare_registered_public_index_basis(
            session,
            case.owner.registry_caller(case.request),
            native_embedding_registry_scope(case.request),
        )
        assert same.previous[1].index_revision_id == previous.index_revision_id
    result = successor.publish_recovered_index_successor(case.publisher, plan)
    assert result.registration.previous_index_revision_id == previous.index_revision_id
    assert result.binding_count >= len(previous.bindings)
    assert result.replayed is False
    replay = successor.publish_recovered_index_successor(case.publisher, plan)
    assert replay.registration == result.registration and replay.replayed
    assert case.launcher.forwards == before_launches
    with case.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, started[0].workflow_id)
        assert workflow.state == "FAILED" and workflow.failure_code == successor.EVENT
        event = session.scalar(
            select(recovery.WorkflowEventRecord).where(
                recovery.WorkflowEventRecord.workflow_id == workflow.workflow_id,
                recovery.WorkflowEventRecord.event_type == successor.EVENT,
            )
        )
        assert all(
            session.get(JobRecord, key).status == "SUCCEEDED"
            for key in event.payload["preserved_encoding_job_ids"]
        )
