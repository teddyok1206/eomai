"""Workflow-specific checks appended to eomctl system doctor."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerRegistry
from eom_workflow import compile_definition
from eom_workflow.schemas import (
    RESULT_SCHEMA_FILES,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
)

from eom_workflow_runner.settings import WorkflowSettings


@dataclass(frozen=True)
class WorkflowDoctorCheck:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run_workflow_doctor(
    settings: WorkflowSettings, platform_settings: Settings
) -> list[WorkflowDoctorCheck]:
    checks: list[WorkflowDoctorCheck] = []
    try:
        load_definition_schema()
        for role in ("authoring", "image", "review", "item_management"):
            load_role_input_schema(role)
        for schema_id in RESULT_SCHEMA_FILES:
            load_role_result_schema(schema_id)
        checks.append(WorkflowDoctorCheck("workflow_schemas", True, "9 loaded"))
    except Exception as exc:
        checks.append(WorkflowDoctorCheck("workflow_schemas", False, type(exc).__name__))
    try:
        registry = WorkerRegistry.load(platform_settings.worker_config)
        roles = {slot.role for slot in registry.config.slots if slot.enabled}
        compiled = compile_definition(settings.definition_path, roles)
        checks.append(
            WorkflowDoctorCheck(
                "generic_workflow_definition",
                True,
                f"{compiled.definition.definition_key}@{compiled.definition.definition_version}",
            )
        )
        expected = {
            "authoring": "eom-cdx-01",
            "review": "eom-cdx-02",
            "image": "eom-cdx-03",
            "item_management": "eom-cdx-04",
        }
        actual = {role: registry.select(role).linux_user for role in expected}
        checks.append(
            WorkflowDoctorCheck(
                "workflow_worker_mapping",
                actual == expected,
                ",".join(f"{role}={actual[role]}" for role in expected),
            )
        )
    except Exception as exc:
        checks.append(WorkflowDoctorCheck("generic_workflow_definition", False, type(exc).__name__))
        checks.append(WorkflowDoctorCheck("workflow_worker_mapping", False, "unavailable"))
    try:
        runner = settings.load_runner()
        checks.append(
            WorkflowDoctorCheck(
                "workflow_runner_config",
                True,
                f"poll={runner.poll_interval_seconds},lease={runner.command_lease_seconds}",
            )
        )
        checks.append(
            WorkflowDoctorCheck(
                "workflow_command_lease",
                runner.command_lease_seconds > platform_settings.worker_timeout_seconds,
                (
                    f"lease={runner.command_lease_seconds}s,"
                    f"worker_timeout={platform_settings.worker_timeout_seconds}s"
                ),
            )
        )
    except Exception as exc:
        checks.append(WorkflowDoctorCheck("workflow_runner_config", False, type(exc).__name__))
        checks.append(WorkflowDoctorCheck("workflow_command_lease", False, "unavailable"))
    try:
        actors = settings.load_actors()
        roles = {actor.role for actor in actors.actors if actor.enabled}
        checks.append(
            WorkflowDoctorCheck(
                "workflow_actor_config",
                {"requester", "reviewer", "admin"}.issubset(roles),
                f"{len(actors.actors)} actors",
            )
        )
    except Exception as exc:
        checks.append(WorkflowDoctorCheck("workflow_actor_config", False, type(exc).__name__))
    return checks
