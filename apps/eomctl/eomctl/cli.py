"""Typer commands for the initial EOM vertical slice."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import typer
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.doctor import DoctorCheck, run_doctor, runtime_configuration_check
from eom_orchestrator.logging import configure_logging
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings, SettingsError
from eom_orchestrator.worker_registry import WorkerRegistry
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.doctor import run_workflow_doctor
from eom_workflow_runner.settings import WorkflowSettings
from sqlalchemy import select

from eomctl.catalog import (
    content_app,
    deliverable_app,
    item_app,
    registry_app,
    usage_app,
)
from eomctl.control_plane import control_plane_app
from eomctl.hwpx import hwpx_app
from eomctl.knowledge import knowledge_app
from eomctl.legacy_assessment import legacy_assessment_app
from eomctl.operator import operator_app
from eomctl.workflow import workflow_app

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
system_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
job_app = typer.Typer(no_args_is_help=True)
app.add_typer(system_app, name="system")
app.add_typer(worker_app, name="worker")
app.add_typer(job_app, name="job")
app.add_typer(workflow_app, name="workflow")
app.add_typer(hwpx_app, name="hwpx")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(legacy_assessment_app, name="legacy-assessment")
app.add_typer(content_app, name="content")
app.add_typer(item_app, name="item")
app.add_typer(deliverable_app, name="deliverable")
app.add_typer(usage_app, name="usage")
app.add_typer(registry_app, name="registry")
app.add_typer(operator_app, name="operator")
app.add_typer(control_plane_app, name="control-plane")


def _emit(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _job_dict(job: JobRecord) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "protocol_version": job.protocol_version,
        "idempotency_key": job.idempotency_key,
        "task_type": job.task_type,
        "status": job.status,
        "logical_artifact_id": job.logical_artifact_id,
        "revision_id": job.revision_id,
        "worker_slot": job.worker_slot_id,
        "worker_exit_code": job.worker_exit_code,
        "worker_stdout_path": job.worker_stdout_path,
        "worker_stderr_path": job.worker_stderr_path,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


def _event_dict(event: JobEventRecord) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "event": event.event,
        "data": event.data,
        "created_at": event.created_at,
    }


@system_app.command("doctor")
def system_doctor() -> None:
    configure_logging()
    try:
        settings = Settings.from_environment()
    except SettingsError as exc:
        _emit(
            {
                "passed": False,
                "checks": [
                    asdict(
                        DoctorCheck(
                            "orchestrator_runtime_configuration",
                            False,
                            type(exc).__name__,
                        )
                    )
                ],
            }
        )
        raise typer.Exit(1) from None
    configuration = runtime_configuration_check(settings)
    if not configuration.passed:
        _emit({"passed": False, "checks": [asdict(configuration)]})
        raise typer.Exit(1)
    engine = build_engine()
    runtime = build_workflow_runtime(
        engine=engine,
        workflow_settings=WorkflowSettings.from_environment(),
        platform_settings=settings,
    )
    try:
        checks = run_doctor(engine, settings)
        checks.extend(
            DoctorCheck(check.name, check.passed, check.detail)
            for check in run_workflow_doctor(
                runtime.runner.settings,
                settings,
                runtime.readiness,
            )
        )
        passed = all(check.passed for check in checks)
        _emit({"passed": passed, "checks": [asdict(check) for check in checks]})
        if not passed:
            raise typer.Exit(1)
    finally:
        engine.dispose()


@worker_app.command("list")
def worker_list() -> None:
    settings = Settings.from_environment()
    registry = WorkerRegistry.load(settings.worker_config)
    _emit(
        {
            "global_codex_concurrency": registry.global_codex_concurrency,
            "gpu_concurrency": registry.config.limits.gpu_concurrency,
            "slots": [slot.model_dump(mode="json") for slot in registry.config.slots],
        }
    )


@job_app.command("submit")
def job_submit(
    message: str = typer.Option(..., "--message"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
) -> None:
    configure_logging()
    orchestrator = Orchestrator(build_engine())
    job = orchestrator.submit(message, idempotency_key)
    _emit(_job_dict(job))
    if job.status != "SUCCEEDED":
        raise typer.Exit(1)


@job_app.command("list")
def job_list(limit: int = typer.Option(50, min=1, max=500)) -> None:
    sessions = build_session_factory(build_engine())
    with sessions() as session:
        jobs = list(
            session.scalars(select(JobRecord).order_by(JobRecord.created_at.desc()).limit(limit))
        )
        data = [_job_dict(job) for job in jobs]
    _emit(data)


@job_app.command("inspect")
def job_inspect(job_id: str) -> None:
    sessions = build_session_factory(build_engine())
    with sessions() as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            raise typer.BadParameter(f"unknown job: {job_id}")
        events = list(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        artifact = session.get(ArtifactRecord, job.logical_artifact_id)
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        data = {
            "job": _job_dict(job),
            "events": [_event_dict(event) for event in events],
            "artifact": (
                {
                    "logical_artifact_id": artifact.logical_artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "approved": artifact.approved,
                }
                if artifact
                else None
            ),
            "revision": (
                {
                    "revision_id": revision.revision_id,
                    "content_hash": revision.content_hash,
                    "manifest_hash": revision.manifest_hash,
                    "content_bytes": revision.content_bytes,
                    "nas_path": revision.nas_path,
                    "approved": revision.approved,
                    "manifest": revision.manifest,
                    "result": revision.result,
                }
                if revision
                else None
            ),
        }
    _emit(data)


@job_app.command("events")
def job_events(job_id: str) -> None:
    sessions = build_session_factory(build_engine())
    with sessions() as session:
        exists = session.get(JobRecord, job_id)
        if exists is None:
            raise typer.BadParameter(f"unknown job: {job_id}")
        events = list(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        data = [_event_dict(event) for event in events]
    _emit(data)


if __name__ == "__main__":
    app()
