"""Workflow runtime checks shared by the runner CLI and platform doctor."""

from __future__ import annotations

from dataclasses import dataclass

from alembic.runtime.migration import MigrationContext
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine, text

from eom_workflow_runner.readiness import (
    ReadinessStatus,
    WorkflowExecutionReadiness,
)
from eom_workflow_runner.settings import WorkflowSettings


@dataclass(frozen=True)
class WorkflowDoctorCheck:
    name: str
    status: ReadinessStatus
    code: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status != ReadinessStatus.FAIL

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "code": self.code,
            "detail": self.detail,
            "passed": self.passed,
        }


def run_workflow_doctor(
    settings: WorkflowSettings,
    platform_settings: Settings,
    readiness: WorkflowExecutionReadiness,
    *,
    engine: Engine | None = None,
) -> list[WorkflowDoctorCheck]:
    checks: list[WorkflowDoctorCheck] = []
    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = MigrationContext.configure(connection).get_current_revision()
            checks.append(_check("workflow_postgresql", True, "connected", "DATABASE_UNAVAILABLE"))
            checks.append(
                _check(
                    "workflow_migration_revision",
                    revision == CURRENT_MIGRATION_REVISION,
                    revision or "not migrated",
                    "MIGRATION_REVISION_MISMATCH",
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "workflow_postgresql",
                    False,
                    type(exc).__name__,
                    "DATABASE_UNAVAILABLE",
                )
            )
            checks.append(
                _check(
                    "workflow_migration_revision",
                    False,
                    "unavailable",
                    "MIGRATION_REVISION_MISMATCH",
                )
            )

    for item in readiness.evaluate().checks:
        checks.append(WorkflowDoctorCheck(item.name, item.status, item.code, item.detail))

    try:
        runner = settings.load_runner()
        checks.append(
            _check(
                "workflow_runner_config",
                True,
                f"poll={runner.poll_interval_seconds},lease={runner.command_lease_seconds}",
                "WORKFLOW_RUNNER_CONFIG_INVALID",
            )
        )
        checks.append(
            _check(
                "workflow_command_lease",
                runner.command_lease_seconds > platform_settings.worker_timeout_seconds,
                (
                    f"lease={runner.command_lease_seconds}s,"
                    f"worker_timeout={platform_settings.worker_timeout_seconds}s"
                ),
                "WORKFLOW_COMMAND_LEASE_INVALID",
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                "workflow_runner_config",
                False,
                type(exc).__name__,
                "WORKFLOW_RUNNER_CONFIG_INVALID",
            )
        )
        checks.append(
            _check(
                "workflow_command_lease",
                False,
                "unavailable",
                "WORKFLOW_COMMAND_LEASE_INVALID",
            )
        )
    try:
        actors = settings.load_actors()
        roles = {actor.role for actor in actors.actors if actor.enabled}
        checks.append(
            _check(
                "workflow_actor_config",
                {"requester", "reviewer", "admin"}.issubset(roles),
                f"{len(actors.actors)} actors",
                "WORKFLOW_ACTOR_CONFIG_INVALID",
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                "workflow_actor_config",
                False,
                type(exc).__name__,
                "WORKFLOW_ACTOR_CONFIG_INVALID",
            )
        )
    return checks


def _check(name: str, passed: bool, detail: str, failure_code: str) -> WorkflowDoctorCheck:
    return WorkflowDoctorCheck(
        name=name,
        status=ReadinessStatus.PASS if passed else ReadinessStatus.FAIL,
        code="READY" if passed else failure_code,
        detail=detail,
    )
