"""CLI adapters that enqueue workflow commands without mutating workflow state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerRegistry
from eom_workflow import WorkflowRequest, compile_definition
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    active_approval,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
)
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

workflow_app = typer.Typer(no_args_is_help=True)
definition_app = typer.Typer(no_args_is_help=True)
workflow_app.add_typer(definition_app, name="definition")


def _emit(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _available_roles() -> set[str]:
    registry = WorkerRegistry.load(Settings.from_environment().worker_config)
    return {slot.role for slot in registry.config.slots if slot.enabled}


@definition_app.command("validate")
def definition_validate(path: Path) -> None:
    compiled = compile_definition(path.resolve(), _available_roles())
    _emit(
        {
            "valid": True,
            "definition_key": compiled.definition.definition_key,
            "definition_version": compiled.definition.definition_version,
            "definition_hash": compiled.sha256,
            "steps": len(compiled.definition.steps),
        }
    )


@definition_app.command("import")
def definition_import(path: Path) -> None:
    compiled = compile_definition(path.resolve(), _available_roles())
    engine = build_engine()
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        record, created = import_workflow_definition(session, compiled)
        data = _definition_dict(record)
        data["created"] = created
    engine.dispose()
    _emit(data)


@definition_app.command("list")
def definition_list() -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        definitions = list(
            session.scalars(
                select(WorkflowDefinitionRecord).order_by(
                    WorkflowDefinitionRecord.definition_key,
                    WorkflowDefinitionRecord.definition_version,
                )
            )
        )
        data = [_definition_dict(definition) for definition in definitions]
    engine.dispose()
    _emit(data)


@workflow_app.command("start")
def workflow_start(
    definition: str = typer.Option(..., "--definition"),
    version: str = typer.Option(..., "--version"),
    request_name: str = typer.Option(..., "--request-name"),
    image_mode: str = typer.Option(..., "--image-mode"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    pack_key: str | None = typer.Option(None, "--pack-key"),
    environment: str = typer.Option("development", "--environment"),
    authoring_profile: str = typer.Option("authoring-default", "--authoring-profile"),
    review_profile: str = typer.Option("review-default", "--review-profile"),
    image_profile: str = typer.Option("image-placeholder", "--image-profile"),
    registration_profile: str = typer.Option("registration-default", "--registration-profile"),
    source_intake_batch: Annotated[list[str] | None, typer.Option("--source-intake-batch")] = None,
    registry_mode: str = typer.Option("CREATE_ITEM", "--registry-mode"),
    item_id: str | None = typer.Option(None, "--item-id"),
    base_revision_id: str | None = typer.Option(None, "--base-revision-id"),
) -> None:
    request_data: dict[str, Any] = {
        "request_name": request_name,
        "image_mode": image_mode,
    }
    if pack_key is not None:
        request_data.update(
            {
                "content_pack": {"pack_key": pack_key, "environment": environment},
                "profiles": {
                    "authoring": authoring_profile,
                    "review": review_profile,
                    "image": image_profile,
                    "registration": registration_profile,
                },
                "source_intake": {"batch_ids": source_intake_batch or []},
                "registry_intent": {
                    "mode": registry_mode,
                    "item_id": item_id,
                    "base_revision_id": base_revision_id,
                },
            }
        )
    request = WorkflowRequest.model_validate(request_data)
    if version == "1.1.0" and request.content_pack is None:
        raise typer.BadParameter("workflow 1.1.0 requires --pack-key and Intake input")
    engine = build_engine()
    catalog = WorkflowCatalogService(engine)
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        stored_definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == definition,
                WorkflowDefinitionRecord.definition_version == version,
                WorkflowDefinitionRecord.active.is_(True),
            )
        )
        if stored_definition is None:
            raise typer.BadParameter("workflow definition is not imported")
        runtime_context = (
            catalog.bind_request(
                request,
                definition_key=stored_definition.definition_key,
                definition_version=stored_definition.definition_version,
            )
            if request.content_pack is not None
            else None
        )
        workflow, created = create_workflow_instance(
            session,
            definition=stored_definition,
            request=request,
            idempotency_key=idempotency_key,
            actor_type="human",
            actor_id="requester_01",
            runtime_context=runtime_context,
        )
        if created:
            enqueue_command(
                session,
                workflow_id=workflow.workflow_id,
                command_type=CommandType.START_WORKFLOW,
                payload={},
                actor_type="human",
                actor_id="requester_01",
                source="eomctl",
                idempotency_key=f"start:{workflow.workflow_id}",
            )
        workflow_id = workflow.workflow_id
    runner = WorkflowRunner(engine, catalog=catalog)
    runner.run_until_idle(workflow_id)
    _emit(_inspect(engine, workflow_id))
    engine.dispose()


@workflow_app.command("list")
def workflow_list(limit: int = typer.Option(50, min=1, max=500)) -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        workflows = list(
            session.scalars(
                select(WorkflowInstanceRecord)
                .order_by(WorkflowInstanceRecord.created_at.desc())
                .limit(limit)
            )
        )
        data = [_workflow_dict(workflow) for workflow in workflows]
    engine.dispose()
    _emit(data)


@workflow_app.command("inspect")
def workflow_inspect(workflow_id: str) -> None:
    engine = build_engine()
    _emit(_inspect(engine, workflow_id))
    engine.dispose()


@workflow_app.command("events")
def workflow_events(workflow_id: str) -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        _require_workflow(session, workflow_id)
        events = list(
            session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence)
            )
        )
        data = [_event_dict(event) for event in events]
    engine.dispose()
    _emit(data)


@workflow_app.command("steps")
def workflow_steps(workflow_id: str) -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        _require_workflow(session, workflow_id)
        steps = list(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow_id)
                .order_by(WorkflowStepRunRecord.attempt, WorkflowStepRunRecord.step_run_id)
            )
        )
        data = [_step_dict(step) for step in steps]
    engine.dispose()
    _emit(data)


@workflow_app.command("approve")
def workflow_approve(workflow_id: str, actor_id: str = typer.Option(..., "--actor-id")) -> None:
    command = _enqueue_approval_command(
        workflow_id,
        actor_id,
        CommandType.APPROVE_WORKFLOW,
        {},
    )
    _run_and_emit_command(workflow_id, command.command_id)


@workflow_app.command("request-rework")
def workflow_request_rework(
    workflow_id: str,
    actor_id: str = typer.Option(..., "--actor-id"),
    target: str = typer.Option(..., "--target"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    command = _enqueue_approval_command(
        workflow_id,
        actor_id,
        CommandType.REQUEST_REWORK,
        {"target": target, "reason": reason},
    )
    _run_and_emit_command(workflow_id, command.command_id)


@workflow_app.command("cancel")
def workflow_cancel(
    workflow_id: str,
    actor_id: str = typer.Option(..., "--actor-id"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        workflow = _require_workflow(session, workflow_id)
        payload = {"reason": reason}
        command, _ = enqueue_command(
            session,
            workflow_id=workflow_id,
            command_type=CommandType.CANCEL_WORKFLOW,
            payload=payload,
            actor_type="human",
            actor_id=actor_id,
            source="eomctl",
            idempotency_key=_command_key(
                workflow_id, "cancel", workflow.lock_version, actor_id, payload
            ),
        )
        command_id = command.command_id
    engine.dispose()
    _run_and_emit_command(workflow_id, command_id)


@workflow_app.command("reconcile")
def workflow_reconcile(workflow_id: str) -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        workflow = _require_workflow(session, workflow_id)
        command, _ = enqueue_command(
            session,
            workflow_id=workflow_id,
            command_type=CommandType.RECONCILE_WORKFLOW,
            payload={},
            actor_type="system",
            actor_id="eomctl",
            source="eomctl",
            idempotency_key=_command_key(
                workflow_id, "reconcile", workflow.lock_version, "eomctl", {}
            ),
        )
        command_id = command.command_id
    engine.dispose()
    _run_and_emit_command(workflow_id, command_id)


def _enqueue_approval_command(
    workflow_id: str,
    actor_id: str,
    command_type: CommandType,
    extra_payload: dict[str, Any],
) -> WorkflowCommandRecord:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        approval = active_approval(session, workflow_id)
        if approval is None:
            raise typer.BadParameter("workflow has no pending approval")
        payload = {
            "approval_request_id": approval.approval_request_id,
            "approval_lock_version": approval.lock_version,
            **extra_payload,
        }
        command, _ = enqueue_command(
            session,
            workflow_id=workflow_id,
            command_type=command_type,
            payload=payload,
            actor_type="human",
            actor_id=actor_id,
            source="eomctl",
            idempotency_key=_command_key(
                workflow_id,
                command_type.value,
                approval.lock_version,
                actor_id,
                payload,
            ),
        )
        session.expunge(command)
    engine.dispose()
    return command


def _run_and_emit_command(workflow_id: str, command_id: str) -> None:
    engine = build_engine()
    runner = WorkflowRunner(engine, catalog=WorkflowCatalogService(engine))
    runner.run_until_idle(workflow_id)
    sessions = build_session_factory(engine)
    with sessions() as session:
        command = session.get(WorkflowCommandRecord, command_id)
        if command is None:
            raise RuntimeError("workflow command disappeared")
        data = {"command": _command_dict(command), **_inspect(engine, workflow_id)}
        failed = command.state == "FAILED"
    engine.dispose()
    _emit(data)
    if failed:
        raise typer.Exit(1)


def _inspect(engine: Engine, workflow_id: str) -> dict[str, Any]:
    sessions = build_session_factory(engine)
    with sessions() as session:
        workflow = _require_workflow(session, workflow_id)
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        steps = list(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow_id)
                .order_by(WorkflowStepRunRecord.attempt, WorkflowStepRunRecord.step_run_id)
            )
        )
        events = list(
            session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence)
            )
        )
        approvals = list(
            session.scalars(
                select(ApprovalRequestRecord)
                .where(ApprovalRequestRecord.workflow_id == workflow_id)
                .order_by(ApprovalRequestRecord.requested_at)
            )
        )
        return {
            "workflow": _workflow_dict(workflow),
            "definition": _definition_dict(definition) if definition else None,
            "steps": [_step_dict(step) for step in steps],
            "approvals": [_approval_dict(approval) for approval in approvals],
            "events": [_event_dict(event) for event in events],
        }


def _require_workflow(session: Session, workflow_id: str) -> WorkflowInstanceRecord:
    workflow = session.get(WorkflowInstanceRecord, workflow_id)
    if workflow is None:
        raise typer.BadParameter(f"unknown workflow: {workflow_id}")
    return workflow


def _command_key(
    workflow_id: str,
    action: str,
    lock_version: int,
    actor_id: str,
    payload: dict[str, Any],
) -> str:
    digest = content_sha256(
        {
            "workflow_id": workflow_id,
            "action": action,
            "lock_version": lock_version,
            "actor_id": actor_id,
            "payload": payload,
        }
    ).removeprefix("sha256:")
    return f"wfctl-{digest}"


def _definition_dict(definition: WorkflowDefinitionRecord) -> dict[str, Any]:
    return {
        "definition_id": definition.definition_id,
        "definition_key": definition.definition_key,
        "definition_version": definition.definition_version,
        "schema_version": definition.schema_version,
        "definition_hash": definition.definition_hash,
        "active": definition.active,
        "source_path": definition.source_path,
        "imported_at": definition.imported_at,
    }


def _workflow_dict(workflow: WorkflowInstanceRecord) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "definition_key": workflow.definition_key,
        "definition_version": workflow.definition_version,
        "definition_hash": workflow.definition_hash,
        "protocol_version": workflow.protocol_version,
        "role_schema_version": workflow.role_schema_version,
        "state": workflow.state,
        "stage": workflow.stage,
        "current_step_key": workflow.current_step_key,
        "request": workflow.initial_request,
        "runtime_context": workflow.runtime_context,
        "idempotency_key": workflow.idempotency_key,
        "lock_version": workflow.lock_version,
        "rework_cycle_count": workflow.rework_cycle_count,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "completed_at": workflow.completed_at,
        "failure_code": workflow.failure_code,
        "failure_summary": workflow.failure_summary,
    }


def _step_dict(step: WorkflowStepRunRecord) -> dict[str, Any]:
    return {
        "step_run_id": step.step_run_id,
        "step_key": step.step_key,
        "attempt": step.attempt,
        "step_type": step.step_type,
        "worker_role": step.worker_role,
        "result_schema": step.result_schema,
        "state": step.state,
        "platform_job_id": step.platform_job_id,
        "input_pointer_manifest": step.input_pointer_manifest,
        "output_pointer_manifest": step.output_pointer_manifest,
        "superseded_by_step_run_id": step.superseded_by_step_run_id,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "error_code": step.error_code,
    }


def _approval_dict(approval: ApprovalRequestRecord) -> dict[str, Any]:
    return {
        "approval_request_id": approval.approval_request_id,
        "step_run_id": approval.step_run_id,
        "status": approval.status,
        "lock_version": approval.lock_version,
        "allowed_roles": approval.allowed_roles,
        "allowed_rework_targets": approval.allowed_rework_targets,
        "requested_at": approval.requested_at,
        "resolved_at": approval.resolved_at,
        "resolved_actor_type": approval.resolved_actor_type,
        "resolved_actor_id": approval.resolved_actor_id,
        "decision": approval.decision,
        "reason": approval.reason,
        "rework_target_step": approval.rework_target_step,
    }


def _event_dict(event: WorkflowEventRecord) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "event_type": event.event_type,
        "prior_state": event.prior_state,
        "new_state": event.new_state,
        "step_key": event.step_key,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "command_id": event.command_id,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def _command_dict(command: WorkflowCommandRecord) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "command_type": command.command_type,
        "state": command.state,
        "attempts": command.attempts,
        "processed_at": command.processed_at,
        "error_code": command.error_code,
    }
