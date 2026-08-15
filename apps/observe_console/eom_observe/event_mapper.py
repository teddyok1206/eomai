"""Deterministic mapping from existing audit sources to a unified event contract."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from eom_observe_contracts import ObserveEvent

from eom_observe.redaction import sanitize_error

SOURCE_PRIORITY = {
    "workflow_event": 0,
    "step_run": 1,
    "job_event": 2,
    "approval": 3,
    "artifact_revision": 4,
}


def role_node(role: str | None) -> str:
    return {
        "authoring": "authoring",
        "review": "review",
        "image": "image",
        "item_management": "item-management",
        "support": "support",
    }.get(role or "", "orchestrator")


def _job_route(event: str, role: str | None, workflow_id: str | None) -> tuple[str, str]:
    worker = role_node(role)
    if event == "JOB_CREATED" and workflow_id:
        return "workflow-runner", "orchestrator"
    if event in {"WORKER_CLAIMED", "WORKER_STARTED"}:
        return "orchestrator", worker
    if event == "WORKER_RESULT_RECEIVED":
        return worker, "orchestrator"
    if event in {"ARTIFACT_COMMIT_STARTED", "ARTIFACT_COMMITTED"}:
        return "orchestrator", "nas"
    return "orchestrator", "postgresql"


def map_job_event(row: dict[str, Any]) -> ObserveEvent:
    source, target = _job_route(row["event"], row.get("worker_role"), row.get("workflow_id"))
    return ObserveEvent(
        event_id=f"jobevent_{row['event_id']}",
        source="job_event",
        event_type=row["event"],
        timestamp=row["created_at"],
        source_node_id=source,
        target_node_id=target,
        workflow_id=row.get("workflow_id"),
        step_run_id=row.get("step_run_id"),
        job_id=row["job_id"],
        artifact_id=row.get("logical_artifact_id"),
        revision_id=row.get("revision_id"),
        status=row["to_state"],
        summary=f"Job {row['to_state'].lower().replace('_', ' ')}",
        error_code=row.get("error_code"),
    )


def _workflow_route(event_type: str, step_key: str | None) -> tuple[str, str]:
    if event_type in {"HUMAN_APPROVAL_REQUESTED", "HUMAN_APPROVAL_STAGE_ENTERED"}:
        return "workflow-runner", "human-approval"
    if event_type in {"WORKFLOW_APPROVED", "WORKFLOW_REWORK_REQUESTED"}:
        return "human-approval", "workflow-runner"
    if step_key == "registration" or event_type == "REGISTRATION_STAGE_ENTERED":
        return "workflow-runner", "item-management"
    if event_type.startswith("STEP_"):
        return "workflow-runner", "orchestrator"
    return "workflow-runner", "postgresql"


def map_workflow_event(row: dict[str, Any]) -> ObserveEvent:
    source, target = _workflow_route(row["event_type"], row.get("step_key"))
    return ObserveEvent(
        event_id=f"workflowevent_{row['event_id']}",
        source="workflow_event",
        event_type=row["event_type"],
        timestamp=row["created_at"],
        source_node_id=source,
        target_node_id=target,
        workflow_id=row["workflow_id"],
        step_run_id=None,
        job_id=None,
        artifact_id=None,
        revision_id=None,
        status=row["new_state"],
        summary=f"Workflow {row['new_state'].lower().replace('_', ' ')}",
        error_code=None,
    )


def map_step_run(row: dict[str, Any]) -> ObserveEvent:
    role = role_node(row.get("worker_role"))
    state = row["state"]
    source, target = (
        (role, "orchestrator")
        if state in {"SUCCEEDED", "FAILED", "SUPERSEDED"}
        else ("orchestrator", role)
    )
    timestamp = row.get("finished_at") or row.get("started_at")
    if timestamp is None:
        raise ValueError("step event has no timestamp")
    return ObserveEvent(
        event_id=f"steprun_{row['step_run_id']}_{state.lower()}",
        source="step_run",
        event_type=f"STEP_{state}",
        timestamp=timestamp,
        source_node_id=source,
        target_node_id=target,
        workflow_id=row["workflow_id"],
        step_run_id=row["step_run_id"],
        job_id=row.get("platform_job_id"),
        artifact_id=row.get("logical_artifact_id"),
        revision_id=row.get("revision_id"),
        status=state,
        summary=f"{row['step_key']} attempt {row['attempt']} {state.lower()}",
        error_code=row.get("error_code"),
    )


def map_approval(row: dict[str, Any]) -> ObserveEvent:
    pending = row["status"] == "PENDING"
    timestamp = row["requested_at"] if pending else row.get("resolved_at") or row["requested_at"]
    return ObserveEvent(
        event_id=f"approval_{row['approval_request_id']}_{row['status'].lower()}",
        source="approval",
        event_type=f"APPROVAL_{row['status']}",
        timestamp=timestamp,
        source_node_id="workflow-runner" if pending else "human-approval",
        target_node_id="human-approval" if pending else "workflow-runner",
        workflow_id=row["workflow_id"],
        step_run_id=row["step_run_id"],
        job_id=None,
        artifact_id=None,
        revision_id=None,
        status=row["status"],
        summary=f"Approval {row['status'].lower().replace('_', ' ')}",
        error_code=None,
    )


def map_revision(row: dict[str, Any]) -> ObserveEvent:
    return ObserveEvent(
        event_id=f"revision_{row['revision_id']}",
        source="artifact_revision",
        event_type="ARTIFACT_REVISION_CREATED",
        timestamp=row["created_at"],
        source_node_id="orchestrator",
        target_node_id="nas",
        workflow_id=None,
        step_run_id=None,
        job_id=row["job_id"],
        artifact_id=row["logical_artifact_id"],
        revision_id=row["revision_id"],
        status="SUCCEEDED",
        summary="Immutable artifact revision committed",
        error_code=None,
    )


def _event_sort_key(event: ObserveEvent) -> tuple[datetime, int, int, str]:
    local_sequence = 0
    tail = event.event_id.rsplit("_", 1)[-1]
    if tail.isdigit():
        local_sequence = int(tail)
    return (event.timestamp, SOURCE_PRIORITY[event.source], local_sequence, event.event_id)


def merge_events(
    *,
    job_events: Iterable[dict[str, Any]],
    workflow_events: Iterable[dict[str, Any]],
    steps: Iterable[dict[str, Any]],
    approvals: Iterable[dict[str, Any]],
    revisions: Iterable[dict[str, Any]],
    limit: int,
) -> list[ObserveEvent]:
    events: list[ObserveEvent] = []
    events.extend(map_job_event(row) for row in job_events)
    events.extend(map_workflow_event(row) for row in workflow_events)
    for row in steps:
        if row.get("started_at") is not None or row.get("finished_at") is not None:
            events.append(map_step_run(row))
    events.extend(map_approval(row) for row in approvals)
    events.extend(map_revision(row) for row in revisions)
    events.sort(key=_event_sort_key)
    sanitized = []
    for event in events[-limit:]:
        sanitized.append(
            event.model_copy(update={"summary": sanitize_error(event.summary, 240) or ""})
        )
    return sanitized
