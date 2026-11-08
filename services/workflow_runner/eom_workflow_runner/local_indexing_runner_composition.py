"""Purpose-only existing INDEX Runner composition, never a scheduler or role worker."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings


class IndexingRoleExecutionDisabled:
    """Explicit failure for non-native readiness, never a fake READY role adapter."""

    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "role_execution",
                    ReadinessStatus.FAIL,
                    "LOCAL_INDEXING_ROLE_EXECUTION_DISABLED",
                    "this installed owner processes only its own native INDEX commands",
                ),
            )
        )


class IndexingRunnerExecutor(LocalEmbeddingNativeExecutor, Protocol):
    owner: CatalogLocalEmbeddingOwnerAdmission
    publisher: ControlFileSetPublisher


def build_local_indexing_workflow_runner(
    executor: IndexingRunnerExecutor, selection: NativeCommandActorSelection
) -> WorkflowRunner:
    return WorkflowRunner(
        executor.publisher.engine,
        settings=WorkflowSettings(),
        catalog=WorkflowCatalogService(executor.publisher.engine, executor.owner.settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(executor.publisher.engine)
        ),
        readiness=IndexingRoleExecutionDisabled(),
        available_roles=frozenset(),
        local_embedding_owner=executor.owner,
        local_embedding_executor=executor,
        command_families=frozenset({CommandExecutionFamily.LOCAL_EMBEDDING}),
        command_actor_selection=selection,
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=64,
        ),
    )
