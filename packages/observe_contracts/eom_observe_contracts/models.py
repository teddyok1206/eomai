"""Strict Pydantic models returned by the versioned observability API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SummaryValue = str | int | bool | None | list[str]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeStatus(StrEnum):
    IDLE = "IDLE"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED_RECENTLY = "SUCCEEDED_RECENTLY"
    FAILED_RECENTLY = "FAILED_RECENTLY"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class DataFreshness(StrictModel):
    database: Literal["fresh", "stale", "unknown"]
    system_probe: Literal["fresh", "stale", "unknown"]


class SnapshotSummary(StrictModel):
    active_workflows: int = Field(ge=0)
    waiting_approvals: int = Field(ge=0)
    queued_jobs: int = Field(ge=0)
    running_jobs: int = Field(ge=0)
    failed_jobs_recent: int = Field(ge=0)
    idle_workers: int = Field(ge=0)


class DeploymentInfo(StrictModel):
    source_commit: str = Field(min_length=1, max_length=64)
    package_version: str = Field(min_length=1, max_length=64)
    build_timestamp_utc: datetime


class ObserveNode(StrictModel):
    node_id: str
    node_type: Literal["SERVICE", "WORKER", "HUMAN_GATE", "DATABASE", "STORAGE"]
    display_name: str
    role: str | None = None
    linux_user: str | None = None
    slot_id: str | None = None
    status: NodeStatus
    current_workflow_id: str | None = None
    current_step_key: str | None = None
    current_step_run_id: str | None = None
    current_job_id: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    started_at: datetime | None = None
    elapsed_seconds: int | None = Field(default=None, ge=0)
    last_event: str | None = None
    last_event_at: datetime | None = None
    input_summary: dict[str, SummaryValue] = Field(default_factory=dict)
    output_summary: dict[str, SummaryValue] = Field(default_factory=dict)
    last_error_code: str | None = None
    last_error_summary: str | None = None
    data_freshness: Literal["fresh", "stale", "unknown"] = "fresh"


class ObserveEdge(StrictModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    interaction_type: str
    status: Literal["ACTIVE", "RECENT", "INACTIVE", "FAILED"]
    workflow_id: str | None = None
    job_id: str | None = None
    step_key: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None
    summary: str


class ObserveEvent(StrictModel):
    event_id: str
    source: Literal["job_event", "workflow_event", "step_run", "approval", "artifact_revision"]
    event_type: str
    timestamp: datetime
    source_node_id: str
    target_node_id: str
    workflow_id: str | None = None
    step_run_id: str | None = None
    job_id: str | None = None
    artifact_id: str | None = None
    revision_id: str | None = None
    status: str
    summary: str
    error_code: str | None = None


class ObserveSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: str
    content_hash: str
    generated_at: datetime
    deployment_revision: str
    deployment: DeploymentInfo
    data_freshness: DataFreshness
    summary: SnapshotSummary
    nodes: list[ObserveNode]
    edges: list[ObserveEdge]
    recent_events: list[ObserveEvent]


class HealthResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["LIVE", "READY", "DEGRADED"]
    timestamp_utc: datetime


class StepRunSummary(StrictModel):
    step_run_id: str
    step_key: str
    attempt: int = Field(ge=1)
    step_type: str
    worker_role: str | None
    result_schema: str | None
    state: str
    platform_job_id: str | None
    input_summary: dict[str, SummaryValue]
    output_summary: dict[str, SummaryValue]
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_summary: str | None
    superseded_by_step_run_id: str | None


class ApprovalSummary(StrictModel):
    approval_request_id: str
    step_run_id: str
    status: str
    allowed_roles: list[str]
    allowed_rework_targets: list[str]
    requested_at: datetime
    resolved_at: datetime | None
    decision: str | None
    rework_target_step: str | None


class WorkflowDetail(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    workflow_id: str
    definition_key: str
    definition_version: str
    definition_hash: str
    state: str
    stage: str
    current_step_key: str
    rework_cycle_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    failure_summary: str | None
    request_summary: dict[str, SummaryValue]
    step_runs: list[StepRunSummary]
    approvals: list[ApprovalSummary]
    events: list[ObserveEvent]


class JobDetail(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    status: str
    task_type: str
    protocol_version: str
    worker_slot_id: str | None
    worker_role: str | None
    worker_linux_user: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    input_summary: dict[str, SummaryValue]
    output_summary: dict[str, SummaryValue]
    error_code: str | None
    error_summary: str | None
    artifact_id: str | None
    revision_id: str | None
    events: list[ObserveEvent]


class ArtifactRevisionSummary(StrictModel):
    revision_id: str
    content_hash: str
    manifest_hash: str
    content_bytes: int = Field(ge=0)
    logical_uri: str
    approved: bool
    result_status: str | None
    schema_version: str | None
    created_at: datetime


class ArtifactDetail(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    artifact_id: str
    artifact_type: str
    approved: bool
    job_id: str
    created_at: datetime
    revisions: list[ArtifactRevisionSummary]
