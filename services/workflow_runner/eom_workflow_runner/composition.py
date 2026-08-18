"""Production composition root for the workflow runtime."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.database import build_engine
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine

from eom_workflow_runner.engine import PlatformRoleJobExecutor, WorkflowRunner
from eom_workflow_runner.settings import WorkflowSettings


@dataclass(frozen=True)
class WorkflowRuntime:
    engine: Engine
    runner: WorkflowRunner


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
    orchestrator = Orchestrator(actual_engine, actual_platform_settings)
    executor = PlatformRoleJobExecutor(
        actual_engine,
        actual_workflow_settings,
        orchestrator,
    )
    catalog = WorkflowCatalogService(actual_engine, catalog_settings)
    runner = WorkflowRunner(
        actual_engine,
        actual_workflow_settings,
        executor,
        catalog=catalog,
    )
    return WorkflowRuntime(engine=actual_engine, runner=runner)
