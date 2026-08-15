from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_observe.settings import (
    AuthSettings,
    ObserveSettings,
    PrivacySettings,
    ServerSettings,
    SnapshotSettings,
    UiSettings,
)
from eom_observe_contracts import (
    ArtifactDetail,
    ArtifactRevisionSummary,
    DataFreshness,
    DeploymentInfo,
    JobDetail,
    NodeStatus,
    ObserveEdge,
    ObserveEvent,
    ObserveNode,
    ObserveSnapshot,
    SnapshotSummary,
    WorkflowDetail,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def settings() -> ObserveSettings:
    return ObserveSettings(
        schema_version=1,
        server=ServerSettings(),
        snapshot=SnapshotSettings(),
        privacy=PrivacySettings(),
        auth=AuthSettings(session_ttl_seconds=3600),
        ui=UiSettings(),
    )


def event(**updates: Any) -> ObserveEvent:
    values: dict[str, Any] = {
        "event_id": "jobevent_1",
        "source": "job_event",
        "event_type": "WORKER_STARTED",
        "timestamp": NOW,
        "source_node_id": "orchestrator",
        "target_node_id": "authoring",
        "workflow_id": "workflow_12345678",
        "step_run_id": "steprun_12345678",
        "job_id": "job_12345678",
        "artifact_id": "artifact_12345678",
        "revision_id": "rev_12345678",
        "status": "RUNNING",
        "summary": "Job running",
        "error_code": None,
    }
    values.update(updates)
    return ObserveEvent.model_validate(values)


def node(node_id: str, node_type: str = "SERVICE", **updates: Any) -> ObserveNode:
    values: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "display_name": node_id.replace("-", " ").title(),
        "status": NodeStatus.IDLE,
        "input_summary": {},
        "output_summary": {},
        "data_freshness": "fresh",
    }
    values.update(updates)
    return ObserveNode.model_validate(values)


def snapshot() -> ObserveSnapshot:
    node_specs = [
        ("workflow-runner", "SERVICE"),
        ("orchestrator", "SERVICE"),
        ("authoring", "WORKER"),
        ("review", "WORKER"),
        ("image", "WORKER"),
        ("item-management", "WORKER"),
        ("support", "WORKER"),
        ("human-approval", "HUMAN_GATE"),
        ("postgresql", "DATABASE"),
        ("nas", "STORAGE"),
    ]
    nodes = [node(node_id, node_type) for node_id, node_type in node_specs]
    edge = ObserveEdge(
        edge_id="edge_workflow_runner_orchestrator_platform_job_submission",
        source_node_id="workflow-runner",
        target_node_id="orchestrator",
        interaction_type="platform_job_submission",
        status="ACTIVE",
        workflow_id="workflow_12345678",
        job_id="job_12345678",
        summary="Platform job submitted",
        last_event_at=NOW,
    )
    return ObserveSnapshot(
        snapshot_id="snapshot_" + "a" * 32,
        content_hash="sha256:" + "a" * 64,
        generated_at=NOW,
        deployment_revision="3c4ab3130286",
        deployment=DeploymentInfo(
            source_commit="3c4ab3130286608f01a5a76e33e0163a330b0086",
            package_version="0.1.1",
            build_timestamp_utc=NOW,
        ),
        data_freshness=DataFreshness(database="fresh", system_probe="fresh"),
        summary=SnapshotSummary(
            active_workflows=1,
            waiting_approvals=0,
            queued_jobs=0,
            running_jobs=1,
            failed_jobs_recent=0,
            idle_workers=4,
        ),
        nodes=nodes,
        edges=[edge],
        recent_events=[event()],
    )


def workflow_detail() -> WorkflowDetail:
    return WorkflowDetail(
        workflow_id="workflow_12345678",
        definition_key="generic-item-development",
        definition_version="1.0.0",
        definition_hash="sha256:" + "b" * 64,
        state="RUNNING",
        stage="AUTHORING",
        current_step_key="authoring",
        rework_cycle_count=0,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
        failure_code=None,
        failure_summary=None,
        request_summary={"request_name": "PLACEHOLDER_REQUEST"},
        step_runs=[],
        approvals=[],
        events=[event(source="workflow_event", event_id="workflowevent_1")],
    )


def job_detail() -> JobDetail:
    return JobDetail(
        job_id="job_12345678",
        status="RUNNING",
        task_type="workflow-role",
        protocol_version="workflow-role/1.0.1",
        worker_slot_id="01",
        worker_role="authoring",
        worker_linux_user="eom-cdx-01",
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
        input_summary={},
        output_summary={},
        error_code=None,
        error_summary=None,
        artifact_id="artifact_12345678",
        revision_id="rev_12345678",
        events=[event()],
    )


def artifact_detail() -> ArtifactDetail:
    return ArtifactDetail(
        artifact_id="artifact_12345678",
        artifact_type="workflow-role",
        approved=True,
        job_id="job_12345678",
        created_at=NOW,
        revisions=[
            ArtifactRevisionSummary(
                revision_id="rev_12345678",
                content_hash="sha256:" + "c" * 64,
                manifest_hash="sha256:" + "d" * 64,
                content_bytes=100,
                logical_uri="nas://artifacts/artifact_12345678/rev_12345678",
                approved=True,
                result_status="ok",
                schema_version="workflow-role/1.0.1",
                created_at=NOW,
            )
        ],
    )
