"""Explicit state and interaction derivation rules for the read-only projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from eom_observe_contracts import NodeStatus, ObserveEdge, ObserveEvent, ObserveNode

from eom_observe.event_mapper import role_node
from eom_observe.redaction import metadata_summary, sanitize_error, shortened_hash
from eom_observe.settings import PrivacySettings

ACTIVE_JOB_STATES = {"CLAIMED", "RUNNING", "VALIDATING_RESULT", "COMMITTING"}
QUEUED_JOB_STATES = {"CREATED", "VALIDATED", "QUEUED"}
ACTIVE_WORKFLOW_STATES = {"REQUESTED", "RUNNING", "REWORK_REQUESTED", "APPROVED", "REGISTERING"}
RECENT_SECONDS = 30

NodeType = Literal["SERVICE", "WORKER", "HUMAN_GATE", "DATABASE", "STORAGE"]
EdgeStatus = Literal["ACTIVE", "RECENT", "INACTIVE", "FAILED"]

STATIC_NODES: tuple[tuple[str, NodeType, str, str | None], ...] = (
    ("workflow-runner", "SERVICE", "Workflow Runner", None),
    ("orchestrator", "SERVICE", "Orchestrator", None),
    ("human-approval", "HUMAN_GATE", "Human Approval", None),
    ("postgresql", "DATABASE", "PostgreSQL", None),
    ("nas", "STORAGE", "NAS Artifacts", None),
)
STATIC_EDGES = (
    ("workflow-runner", "orchestrator", "platform_job_submission"),
    ("orchestrator", "authoring", "worker_execution"),
    ("orchestrator", "image", "worker_execution"),
    ("orchestrator", "review", "worker_execution"),
    ("orchestrator", "item-management", "worker_execution"),
    ("orchestrator", "support", "worker_execution"),
    ("authoring", "orchestrator", "worker_result"),
    ("image", "orchestrator", "worker_result"),
    ("review", "orchestrator", "worker_result"),
    ("item-management", "orchestrator", "worker_result"),
    ("support", "orchestrator", "worker_result"),
    ("orchestrator", "postgresql", "job_event_transaction"),
    ("orchestrator", "nas", "artifact_commit"),
    ("workflow-runner", "human-approval", "approval_requested"),
    ("human-approval", "workflow-runner", "approval_decision"),
    ("workflow-runner", "item-management", "registration_scheduled"),
    ("workflow-runner", "postgresql", "workflow_transaction"),
)


def _elapsed(started_at: datetime | None, now: datetime) -> int | None:
    if started_at is None:
        return None
    return max(0, int((now - started_at).total_seconds()))


def _step_summaries(
    row: dict[str, Any], privacy: PrivacySettings
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_summary = metadata_summary(row.get("input_pointer_manifest") or {}, privacy)
    key_hash = shortened_hash(row["idempotency_key"]) if row.get("idempotency_key") else None
    if key_hash:
        input_summary["idempotency_key_hash"] = key_hash
    output_summary: dict[str, Any] = {}
    for key in ("logical_artifact_id", "revision_id", "content_bytes", "worker_exit_code"):
        if row.get(key) is not None:
            output_summary[key] = row[key]
    for source, target in (("content_hash", "sha256"), ("manifest_hash", "manifest_hash")):
        value = row.get(source)
        if isinstance(value, str):
            output_summary[target] = value[:19]
    return input_summary, output_summary


def _last_event_by_node(events: list[ObserveEvent]) -> dict[str, ObserveEvent]:
    latest: dict[str, ObserveEvent] = {}
    for event in events:
        latest[event.source_node_id] = event
        latest[event.target_node_id] = event
    return latest


def derive_nodes(
    *,
    workers: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    events: list[ObserveEvent],
    privacy: PrivacySettings,
    database_fresh: bool,
    system_probe_fresh: bool,
    available_workers: dict[str, bool] | None = None,
    now: datetime | None = None,
) -> list[ObserveNode]:
    current = now or datetime.now(UTC)
    latest = _last_event_by_node(events)
    active_steps = [
        row
        for row in steps
        if row["state"] in {"READY", "RUNNING"} or row.get("job_status") in ACTIVE_JOB_STATES
    ]
    active_steps.sort(
        key=lambda row: (
            row.get("started_at") or datetime.min.replace(tzinfo=UTC),
            row["step_run_id"],
        ),
        reverse=True,
    )
    worker_nodes: list[ObserveNode] = []
    for worker in sorted(workers, key=lambda item: item["slot_id"]):
        node_id = role_node(worker["role"])
        active = next(
            (row for row in active_steps if row.get("worker_role") == worker["role"]), None
        )
        recent = next((row for row in steps if row.get("worker_role") == worker["role"]), None)
        status = NodeStatus.IDLE
        selected = active or recent
        if not worker["enabled"]:
            status = NodeStatus.DISABLED
        elif available_workers is not None and not available_workers.get(
            worker["linux_user"], False
        ):
            status = NodeStatus.UNAVAILABLE
        elif active is not None:
            status = (
                NodeStatus.QUEUED
                if active.get("job_status") in QUEUED_JOB_STATES
                else NodeStatus.RUNNING
            )
        elif recent is not None and recent.get("finished_at") is not None:
            age = (current - recent["finished_at"]).total_seconds()
            if age <= RECENT_SECONDS:
                status = (
                    NodeStatus.FAILED_RECENTLY
                    if recent["state"] == "FAILED"
                    else NodeStatus.SUCCEEDED_RECENTLY
                )
        input_summary, output_summary = _step_summaries(selected or {}, privacy)
        last = latest.get(node_id)
        worker_nodes.append(
            ObserveNode(
                node_id=node_id,
                node_type="WORKER",
                display_name=worker["role"].replace("_", " ").title(),
                role=worker["role"],
                linux_user=worker["linux_user"],
                slot_id=worker["slot_id"],
                status=status,
                current_workflow_id=active.get("workflow_id") if active else None,
                current_step_key=active.get("step_key") if active else None,
                current_step_run_id=active.get("step_run_id") if active else None,
                current_job_id=active.get("platform_job_id") if active else None,
                attempt=active.get("attempt") if active else None,
                started_at=active.get("started_at") if active else None,
                elapsed_seconds=_elapsed(active.get("started_at"), current) if active else None,
                last_event=last.event_type if last else None,
                last_event_at=last.timestamp if last else None,
                input_summary=input_summary,
                output_summary=output_summary,
                last_error_code=(selected or {}).get("error_code"),
                last_error_summary=sanitize_error((selected or {}).get("error_summary")),
                data_freshness=(
                    "stale" if not database_fresh else "fresh" if system_probe_fresh else "unknown"
                ),
            )
        )

    active_workflow = next(
        (row for row in workflows if row["state"] in ACTIVE_WORKFLOW_STATES), None
    )
    active_job = next((row for row in jobs if row["status"] in ACTIVE_JOB_STATES), None)
    waiting = next((row for row in approvals if row["status"] == "PENDING"), None)
    static_nodes: list[ObserveNode] = []
    for node_id, node_type, display_name, role in STATIC_NODES:
        status = NodeStatus.IDLE
        workflow_id = None
        step_key = None
        job_id = None
        if node_id == "workflow-runner" and active_workflow:
            status = NodeStatus.RUNNING
            workflow_id = active_workflow["workflow_id"]
            step_key = active_workflow["current_step_key"]
        elif node_id == "orchestrator" and active_job:
            status = NodeStatus.RUNNING
            job_id = active_job["job_id"]
        elif node_id == "human-approval" and waiting:
            status = NodeStatus.WAITING
            workflow_id = waiting["workflow_id"]
        elif node_id == "postgresql" and not database_fresh:
            status = NodeStatus.UNAVAILABLE
        elif node_id == "nas":
            failure = next(
                (row for row in jobs if row.get("error_code") == "NAS_UNAVAILABLE"), None
            )
            status = NodeStatus.UNAVAILABLE if failure else NodeStatus.IDLE
        last = latest.get(node_id)
        static_nodes.append(
            ObserveNode(
                node_id=node_id,
                node_type=node_type,
                display_name=display_name,
                role=role,
                status=status,
                current_workflow_id=workflow_id,
                current_step_key=step_key,
                current_job_id=job_id,
                last_event=last.event_type if last else None,
                last_event_at=last.timestamp if last else None,
                input_summary={},
                output_summary={},
                data_freshness=(
                    ("fresh" if database_fresh else "stale")
                    if node_id == "postgresql"
                    else ("fresh" if system_probe_fresh else "unknown")
                ),
            )
        )
    return sorted(static_nodes + worker_nodes, key=lambda node: node.node_id)


def _interaction_type(event: ObserveEvent) -> str:
    if event.target_node_id == "nas":
        return "artifact_commit"
    if event.target_node_id == "human-approval":
        return "approval_requested"
    if event.source_node_id == "human-approval":
        return "approval_decision"
    if event.source_node_id == "workflow-runner" and event.target_node_id == "orchestrator":
        return "platform_job_submission"
    if event.source_node_id == "orchestrator" and event.target_node_id in {
        "authoring",
        "image",
        "review",
        "item-management",
        "support",
    }:
        return "worker_execution"
    if event.target_node_id == "orchestrator" and event.source_node_id in {
        "authoring",
        "image",
        "review",
        "item-management",
        "support",
    }:
        return "worker_result"
    if event.target_node_id == "postgresql":
        return (
            "workflow_transaction"
            if event.source_node_id == "workflow-runner"
            else "job_event_transaction"
        )
    return "worker_result"


def derive_edges(
    events: list[ObserveEvent], *, active_seconds: int, now: datetime | None = None
) -> list[ObserveEdge]:
    current = now or datetime.now(UTC)
    latest: dict[tuple[str, str, str], ObserveEvent] = {}
    for event in events:
        key = (event.source_node_id, event.target_node_id, _interaction_type(event))
        latest[key] = event
    edges: list[ObserveEdge] = []
    for source, target, interaction in STATIC_EDGES:
        recent_event = latest.get((source, target, interaction))
        status: EdgeStatus = "INACTIVE"
        if recent_event is not None:
            age = (current - recent_event.timestamp).total_seconds()
            status = "ACTIVE" if age <= active_seconds else "RECENT"
            if recent_event.error_code:
                status = "FAILED"
        edge_id = f"edge_{source.replace('-', '_')}_{target.replace('-', '_')}_{interaction}"
        edges.append(
            ObserveEdge(
                edge_id=edge_id,
                source_node_id=source,
                target_node_id=target,
                interaction_type=interaction,
                status=status,
                workflow_id=recent_event.workflow_id if recent_event else None,
                job_id=recent_event.job_id if recent_event else None,
                step_key=None,
                attempt=None,
                started_at=recent_event.timestamp if recent_event else None,
                completed_at=recent_event.timestamp if recent_event else None,
                last_event_at=recent_event.timestamp if recent_event else None,
                summary=(recent_event.summary if recent_event else interaction.replace("_", " ")),
            )
        )
    return sorted(edges, key=lambda edge: edge.edge_id)
