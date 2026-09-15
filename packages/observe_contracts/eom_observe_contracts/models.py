"""Strict Pydantic models returned by the versioned observability API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class OperationalAttentionClass(StrEnum):
    QUIESCENT_NONTERMINAL_WORKFLOW = "QUIESCENT_NONTERMINAL_WORKFLOW"
    EXPIRED_WORKFLOW_COMMAND_CLAIM = "EXPIRED_WORKFLOW_COMMAND_CLAIM"
    EXPIRED_WORKER_LEASE = "EXPIRED_WORKER_LEASE"
    EXPIRED_API_IDEMPOTENCY_CLAIM = "EXPIRED_API_IDEMPOTENCY_CLAIM"
    RECENT_FAILED_WORKFLOW = "RECENT_FAILED_WORKFLOW"
    RECENT_FAILED_JOB = "RECENT_FAILED_JOB"


class OperationalCounts(StrictModel):
    active_workflow_commands: int = Field(ge=0)
    active_jobs: int = Field(ge=0)
    held_worker_leases: int = Field(ge=0)
    processing_api_requests: int = Field(ge=0)
    pending_human_approvals: int = Field(ge=0)
    executable_workflows: int = Field(ge=0)
    quiescent_nonterminal_workflows: int = Field(ge=0)
    recent_failed_workflows: int = Field(ge=0)
    recent_failed_jobs: int = Field(ge=0)
    historical_failed_workflows: int = Field(ge=0)
    historical_failed_jobs: int = Field(ge=0)


class OperationalAttentionItem(StrictModel):
    classification: OperationalAttentionClass
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[a-z0-9_]{8,55}$")
    job_id: str | None = Field(default=None, pattern=r"^job_[a-z0-9_]{8,55}$")
    command_id: str | None = Field(default=None, pattern=r"^wfcmd_[a-z0-9_]{8,55}$")
    lease_id: str | None = Field(default=None, pattern=r"^workerlease_[a-z0-9_]{8,55}$")
    api_idempotency_record_id: str | None = Field(
        default=None, pattern=r"^apiidem_[a-z0-9_]{8,55}$"
    )
    state: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    observed_at: datetime

    @model_validator(mode="after")
    def require_classification_identity(self) -> OperationalAttentionItem:
        identities = {
            "workflow_id": self.workflow_id,
            "job_id": self.job_id,
            "command_id": self.command_id,
            "lease_id": self.lease_id,
            "api_idempotency_record_id": self.api_idempotency_record_id,
        }
        required, permitted = {
            OperationalAttentionClass.QUIESCENT_NONTERMINAL_WORKFLOW: (
                frozenset({"workflow_id"}),
                frozenset({"workflow_id"}),
            ),
            OperationalAttentionClass.EXPIRED_WORKFLOW_COMMAND_CLAIM: (
                frozenset({"workflow_id", "command_id"}),
                frozenset({"workflow_id", "command_id"}),
            ),
            OperationalAttentionClass.EXPIRED_WORKER_LEASE: (
                frozenset({"workflow_id", "job_id", "lease_id"}),
                frozenset({"workflow_id", "job_id", "lease_id"}),
            ),
            OperationalAttentionClass.EXPIRED_API_IDEMPOTENCY_CLAIM: (
                frozenset({"api_idempotency_record_id"}),
                frozenset({"api_idempotency_record_id"}),
            ),
            OperationalAttentionClass.RECENT_FAILED_WORKFLOW: (
                frozenset({"workflow_id"}),
                frozenset({"workflow_id"}),
            ),
            OperationalAttentionClass.RECENT_FAILED_JOB: (
                frozenset({"job_id"}),
                frozenset({"workflow_id", "job_id"}),
            ),
        }[self.classification]
        if any(identities[name] is None for name in required):
            raise ValueError("operational attention identity is incomplete")
        if any(value is not None and name not in permitted for name, value in identities.items()):
            raise ValueError(
                "operational attention identity is inconsistent with its classification"
            )
        permitted_states = {
            OperationalAttentionClass.QUIESCENT_NONTERMINAL_WORKFLOW: frozenset(
                {
                    "REQUESTED",
                    "RUNNING",
                    "AWAITING_HUMAN_APPROVAL",
                    "REWORK_REQUESTED",
                    "APPROVED",
                    "REGISTERING",
                }
            ),
            OperationalAttentionClass.EXPIRED_WORKFLOW_COMMAND_CLAIM: frozenset(
                {"LEASED", "PROCESSING"}
            ),
            OperationalAttentionClass.EXPIRED_WORKER_LEASE: frozenset({"ACTIVE", "RECONCILING"}),
            OperationalAttentionClass.EXPIRED_API_IDEMPOTENCY_CLAIM: frozenset({"PROCESSING"}),
            OperationalAttentionClass.RECENT_FAILED_WORKFLOW: frozenset({"FAILED"}),
            OperationalAttentionClass.RECENT_FAILED_JOB: frozenset({"FAILED"}),
        }[self.classification]
        if self.state not in permitted_states:
            raise ValueError("operational attention state is inconsistent with its classification")
        return self


class OperationalOverview(StrictModel):
    schema_version: Literal["observe-operational-overview/1.0"] = "observe-operational-overview/1.0"
    generated_at: datetime
    recent_failure_window_seconds: int = Field(ge=60, le=86_400)
    counts: OperationalCounts
    attention: list[OperationalAttentionItem] = Field(max_length=100)

    @model_validator(mode="after")
    def require_stable_attention_order(self) -> OperationalOverview:
        def key(item: OperationalAttentionItem) -> tuple[datetime, str, str]:
            identity = next(
                value
                for value in (
                    item.workflow_id,
                    item.job_id,
                    item.command_id,
                    item.lease_id,
                    item.api_idempotency_record_id,
                )
                if value is not None
            )
            return (item.observed_at, item.classification.value, identity)

        expected = sorted(self.attention, key=key, reverse=True)
        if self.attention != expected:
            raise ValueError("operational attention values must use canonical newest-first order")
        identities = {
            (
                item.classification,
                item.workflow_id,
                item.job_id,
                item.command_id,
                item.lease_id,
                item.api_idempotency_record_id,
            )
            for item in self.attention
        }
        if len(identities) != len(self.attention):
            raise ValueError("operational attention values must be unique")
        return self


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
