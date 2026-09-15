"""Authoritative PostgreSQL read surface for the Observability adapter."""

from __future__ import annotations

FULL_SELECT_TABLES = (
    "worker_slots",
    "jobs",
    "job_events",
    "artifacts",
    "artifact_revisions",
    "workflow_instances",
    "workflow_step_runs",
    "workflow_events",
    "approval_requests",
)

COLUMN_SELECT_GRANTS = {
    "workflow_commands": (
        "command_id",
        "workflow_id",
        "state",
        "lease_expires_at",
        "error_code",
    ),
    "worker_leases": (
        "lease_id",
        "workflow_id",
        "job_id",
        "state",
        "expires_at",
    ),
    "api_idempotency_records": (
        "api_idempotency_record_id",
        "state",
        "lease_expires_at",
        "error_code",
    ),
}

REQUIRED_READ_MODEL_TABLES = tuple(sorted((*FULL_SELECT_TABLES, *COLUMN_SELECT_GRANTS)))
