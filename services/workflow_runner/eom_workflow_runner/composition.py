"""Production composition root for the workflow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.control_command_processor import CodexControlCommandProcessor
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine

from eom_workflow_runner.actor_authorization import CompositeWorkflowActorAuthorizer
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
    StaticWorkflowActorAuthorizer,
)
from eom_workflow_runner.engine import PlatformRoleJobExecutor, WorkflowRunner
from eom_workflow_runner.readiness import WorkflowRuntimeReadiness
from eom_workflow_runner.settings import WorkflowSettings


@dataclass(frozen=True)
class WorkflowRuntime:
    engine: Engine
    runner: WorkflowRunner
    catalog: WorkflowCatalogService
    readiness: WorkflowRuntimeReadiness
    workflow_settings: WorkflowSettings
    platform_settings: Settings


def build_workflow_runtime(
    *,
    engine: Engine | None = None,
    workflow_settings: WorkflowSettings | None = None,
    platform_settings: Settings | None = None,
    catalog_settings: CatalogSettings | None = None,
) -> WorkflowRuntime:
    """Build the complete production runner graph without presentation-layer wiring."""
    actual_engine = engine or build_engine()
    actual_workflow_settings = workflow_settings or WorkflowSettings.from_environment()
    actual_platform_settings = platform_settings or Settings.from_environment()
    registry = resolve_worker_configuration(actual_platform_settings).registry
    available_roles = frozenset(slot.role for slot in registry.config.slots if slot.enabled)
    orchestrator = Orchestrator(actual_engine, actual_platform_settings)
    executor = PlatformRoleJobExecutor(
        actual_engine,
        actual_workflow_settings,
        orchestrator,
    )
    actual_catalog_settings = catalog_settings or CatalogSettings.from_environment()
    catalog = WorkflowCatalogService(actual_engine, actual_catalog_settings)
    actor_authorizer = CompositeWorkflowActorAuthorizer(
        operator=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(actual_engine)
        ),
        static=StaticWorkflowActorAuthorizer(actual_workflow_settings.load_actors()),
    )
    readiness = WorkflowRuntimeReadiness(
        workflow_settings=actual_workflow_settings,
        platform_settings=actual_platform_settings,
        catalog_settings=actual_catalog_settings,
        catalog_configured=True,
        actor_authorizer=actor_authorizer,
        runner_user="eom-workflow-runner",
    )
    runner_id = f"runner-{uuid4().hex}"
    control_processor = CodexControlCommandProcessor(
        build_session_factory(actual_engine),
        capability_policy_path=actual_platform_settings.codex_capability_policy,
        runner_id=runner_id,
    )
    runner = WorkflowRunner(
        actual_engine,
        actual_workflow_settings,
        executor,
        catalog=catalog,
        actor_authorizer=actor_authorizer,
        readiness=readiness,
        available_roles=available_roles,
        control_processor=control_processor,
        capacity_reconciler=orchestrator.capacity,
        runner_id=runner_id,
    )
    return WorkflowRuntime(
        engine=actual_engine,
        runner=runner,
        catalog=catalog,
        readiness=readiness,
        workflow_settings=actual_workflow_settings,
        platform_settings=actual_platform_settings,
    )
