"""Production composition root for the workflow runtime."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.database import build_engine
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerRegistry
from sqlalchemy import Engine

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
    registry = WorkerRegistry.load(actual_platform_settings.worker_config)
    available_roles = frozenset(slot.role for slot in registry.config.slots if slot.enabled)
    orchestrator = Orchestrator(actual_engine, actual_platform_settings)
    executor = PlatformRoleJobExecutor(
        actual_engine,
        actual_workflow_settings,
        orchestrator,
    )
    actual_catalog_settings = catalog_settings or CatalogSettings.from_environment()
    catalog = WorkflowCatalogService(actual_engine, actual_catalog_settings)
    readiness = WorkflowRuntimeReadiness(
        workflow_settings=actual_workflow_settings,
        platform_settings=actual_platform_settings,
        catalog_settings=actual_catalog_settings,
        catalog_configured=True,
    )
    runner = WorkflowRunner(
        actual_engine,
        actual_workflow_settings,
        executor,
        catalog=catalog,
        readiness=readiness,
        available_roles=available_roles,
    )
    return WorkflowRuntime(
        engine=actual_engine,
        runner=runner,
        catalog=catalog,
        readiness=readiness,
        workflow_settings=actual_workflow_settings,
        platform_settings=actual_platform_settings,
    )
