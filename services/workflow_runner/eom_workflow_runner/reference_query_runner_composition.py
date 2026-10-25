"""One purpose-only Runner composition shared by standalone and routed reference QUERY."""

from __future__ import annotations

from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings


class ReferenceQueryRoleExecutionDisabled:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "role_execution",
                    ReadinessStatus.FAIL,
                    "REFERENCE_QUERY_ROLE_DISABLED",
                    "native QUERY only",
                ),
            )
        )


def build_reference_query_workflow_runner(
    publisher: ControlFileSetPublisher,
    owner: CatalogReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
    *,
    operator_id: str,
) -> WorkflowRunner:
    """Selection is a queue filter, never human authority; owner fences remain mandatory."""
    if (
        publisher.engine is not owner.catalog.engine
        or publisher.settings.nas_artifact_root != owner.settings.nas_artifact_root
    ):
        raise ValueError("REFERENCE_QUERY_RUNNER_COMPOSITION_INVALID")
    return WorkflowRunner(
        publisher.engine,
        WorkflowSettings(),
        catalog=WorkflowCatalogService(publisher.engine, owner.settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(publisher.engine)
        ),
        readiness=ReferenceQueryRoleExecutionDisabled(),
        available_roles=frozenset(),
        reference_query_owner=owner,
        reference_query_executor=executor,
        command_families=frozenset({CommandExecutionFamily.REFERENCE_QUERY}),
        command_actor_selection=NativeCommandActorSelection("human", operator_id),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=1,
        ),
    )
