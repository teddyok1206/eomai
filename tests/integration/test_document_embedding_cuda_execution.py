"""Actual disposable Workflow/claim/Artifact/index/parent history; IAM/root/model synthetic."""

from threading import Event, current_thread
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_models import EmbeddingIndexRecord
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import read_native_embedding_launch
from eom_workflow_runner import engine as engine_module
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.document_embedding_batch_driver import (
    drive_document_embedding_batch_once,
    start_document_embedding_batch,
)
from eom_workflow_runner.embedding_batch_execution import ActiveEmbeddingBatchExecution
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_embedding_submission import LocalEmbeddingWorkflowSubmitted
from eom_workflow_runner.local_indexing_service_runtime import IndexingRoleExecutionDisabled
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings
from sqlalchemy import event, select

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def purpose_runner(value):
    return WorkflowRunner(
        value.publisher.engine,
        WorkflowSettings(),
        catalog=WorkflowCatalogService(value.publisher.engine, value.owner.settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(value.publisher.engine)
        ),
        readiness=IndexingRoleExecutionDisabled(),
        available_roles=frozenset(),
        local_embedding_owner=value.owner,
        local_embedding_executor=value.executor,
        command_families=frozenset({CommandExecutionFamily.LOCAL_EMBEDDING}),
        command_actor_selection=NativeCommandActorSelection(
            "human", value.request.actor_context.operator_id
        ),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=1,
            max_commands_per_run=1,
        ),
    )


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_supported_start_and_actual_runner_own_claim_heartbeat_and_completion(
    execution, monkeypatch
):
    value = execution
    started = start_document_embedding_batch(value.executor)
    assert isinstance(started, LocalEmbeddingWorkflowSubmitted)
    replay = start_document_embedding_batch(value.executor)
    assert replay.workflow.workflow_id == started.workflow.workflow_id
    assert not replay.workflow_created and not replay.command_created
    runner = purpose_runner(value)
    tick = Event()
    original_renew = engine_module.renew_command_lease

    def renew(session, lease, **kwargs):
        result = original_renew(session, lease, **kwargs)
        if current_thread().name.startswith("workflow-command-heartbeat-"):
            event.listen(session, "after_commit", lambda _session: tick.set(), once=True)
        return result

    original_run = ActiveEmbeddingBatchExecution.run

    def run(self, *args, **kwargs):
        assert tick.wait(8), "real heartbeat transaction did not commit before numerical work"
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(engine_module, "renew_command_lease", renew)
    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", run)
    command = drive_document_embedding_batch_once(
        value.executor, runner, started.workflow.workflow_id
    )
    assert command is not None and command.state == "SUCCEEDED"
    assert tick.is_set()
    assert len(value.gpu.dispatches) == 1 and value.gpu.acked
    assert value.launcher.forwards == 0
    assert (
        drive_document_embedding_batch_once(value.executor, runner, started.workflow.workflow_id)
        is None
    )
    assert len(value.gpu.dispatches) == 1


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_broader_runner_is_rejected_without_worker_or_numerical_dispatch(execution):
    value = execution
    started = start_document_embedding_batch(value.executor)
    runner = purpose_runner(value)
    runner.available_roles = frozenset({"authoring"})
    with pytest.raises(ValueError, match="DOCUMENT_BATCH_DRIVER_RUNNER_INVALID"):
        drive_document_embedding_batch_once(value.executor, runner, started.workflow.workflow_id)
    assert not value.gpu.acked and not hasattr(value.gpu, "numeric")


@pytest.mark.parametrize("execution", ["cuda_bulk"], indirect=True)
def test_bulk_parent_composes_with_existing_native_wire_and_actual_index_runner(execution):
    value = execution
    assert (
        value.gpu.request.schema_version
        == value.gpu.selection.schema_version
        == "embedding-batch-plan/1.1"
    )
    started = start_document_embedding_batch(value.executor)
    command = drive_document_embedding_batch_once(
        value.executor, purpose_runner(value), started.workflow.workflow_id
    )
    assert command is not None and command.state == "SUCCEEDED"
    assert value.gpu.allocation.schema_version == "embedding-batch-plan/1.0"
    assert value.gpu.numeric.frames.bound.binding.schema_version == "embedding-batch-plan/1.0"
    assert len(value.gpu.dispatches) == 1 and value.gpu.acked
    assert value.launcher.forwards == 0


def native_history(value, workflow):
    with value.sessions.begin() as session:
        step = session.scalar(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                WorkflowStepRunRecord.step_key == "encode_batch",
            )
        )
        launch = read_native_embedding_launch(
            session,
            request=value.request,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
        )
        return launch.intent, NativeEmbeddingCoordinator(launch.intent, value.request).read(session)


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_existing_index_workflow_registers_cuda_rows_and_parent_receipt_without_cpu(execution):
    value = execution
    first = value.start()
    assert value.advance(*first) is True
    value.finish(*first)
    assert value.gpu.acked and len(value.gpu.dispatches) == 1
    assert len(value.gpu.numeric.result.children) == 1
    assert value.gpu.numeric.result.children[0].result.shard.space.runtime.device == "CUDA"
    assert value.launcher.forwards == 0
    with value.sessions.begin() as session:
        history = value.gpu.store.read(session)
        assert history.state == "SUCCEEDED" and history.bound is not None
        assert history.bound.children[0].workflow_id == first[0].workflow_id
        rows = tuple(
            session.scalars(
                select(EmbeddingIndexRecord).where(
                    EmbeddingIndexRecord.corpus_id == value.request.corpus_id
                )
            )
        )
        assert rows and all(row.space_sha256 == value.request.space.space_sha256 for row in rows)


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
@pytest.mark.parametrize(
    "boundary", ("owned_before", "owned_after", "receipt_before", "receipt_after")
)
def test_publication_interruptions_reuse_original_cuda_result_and_canonical_producers(
    execution, monkeypatch, boundary
):
    value = execution
    first = value.start()
    target = (
        EmbeddingArtifactStore
        if boundary.startswith("owned")
        else NativeEmbeddingCompletionPublisher
    )
    method = "publish_owned_batch" if boundary.startswith("owned") else "publish"
    original = getattr(target, method)
    failed = []

    def interrupt(self, *args, **kwargs):
        if not failed:
            failed.append(True)
            if boundary.endswith("after"):
                original(self, *args, **kwargs)
            raise RuntimeError("synthetic CUDA publication interruption")
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(RuntimeError, match="synthetic CUDA publication interruption"):
            value.advance(*first)
    assert failed and len(value.gpu.dispatches) == 1 and value.gpu.acked
    intent, prior = native_history(value, first[0])
    value.gpu.channel.require_direct_peer = Mock(side_effect=AssertionError("replay revived root"))
    assert value.advance(*first) is True
    value.finish(*first)
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0
    final_intent, completed = native_history(value, first[0])
    assert intent == final_intent and completed.records[: len(prior.records)] == prior.records
    assert completed.state == "SUCCEEDED" and len(completed.records) == 4


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_other_parent_workflow_relation_is_rejected_before_numerical_work(execution):
    value = execution
    first = value.start()
    value.gpu.adapter.workflow_key += "-foreign"
    with pytest.raises(ValueError, match="DOCUMENT_CUDA_EXECUTION_INVALID"):
        value.advance(*first)
    assert not value.gpu.acked and not hasattr(value.gpu, "numeric")
    assert value.launcher.forwards == 0
