"""Bounded, read-only PostgreSQL projections for observability snapshots and details."""

# Fixed SQL projections stay contiguous so their selected columns remain auditable.
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from eom_observe.errors import ObserveError, ObserveErrorCode
from eom_observe.operational_overview import OperationalOverviewRows
from eom_observe.read_model import REQUIRED_READ_MODEL_TABLES


@dataclass(frozen=True)
class SnapshotRows:
    workers: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    job_events: list[dict[str, Any]]
    workflow_events: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    revisions: list[dict[str, Any]]
    counts: dict[str, Any]


class ObserveRepository:
    """Uses fixed SQL only; every public method is read-only."""

    def __init__(self, engine: Engine, *, event_limit: int = 200) -> None:
        self.engine = engine
        self.event_limit = event_limit

    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in result.mappings().all()]

    def snapshot_rows(self) -> SnapshotRows:
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                workers = self._rows(
                    connection.execute(
                        text(
                            "SELECT slot_id, linux_user, role, enabled, gpu, created_at, updated_at "
                            "FROM worker_slots ORDER BY slot_id"
                        )
                    )
                )
                workflows = self._rows(
                    connection.execute(
                        text(
                            "SELECT workflow_id, definition_key, definition_version, definition_hash, "
                            "state, stage, current_step_key, initial_request, rework_cycle_count, "
                            "created_at, updated_at, completed_at, failure_code, failure_summary "
                            "FROM workflow_instances ORDER BY updated_at DESC, workflow_id LIMIT 200"
                        )
                    )
                )
                steps = self._rows(
                    connection.execute(
                        text(
                            "SELECT sr.step_run_id, sr.workflow_id, sr.step_key, sr.attempt, "
                            "sr.step_type, sr.worker_role, sr.result_schema, sr.state, "
                            "sr.platform_job_id, sr.input_pointer_manifest, "
                            "sr.output_pointer_manifest, sr.started_at, sr.finished_at, "
                            "sr.error_code, sr.error_summary, sr.superseded_by_step_run_id, "
                            "j.status AS job_status, j.worker_exit_code, j.updated_at AS job_updated_at, "
                            "j.logical_artifact_id, j.revision_id, j.idempotency_key, "
                            "ar.content_hash, ar.manifest_hash, ar.content_bytes, ar.created_at AS artifact_created_at "
                            "FROM workflow_step_runs sr "
                            "LEFT JOIN jobs j ON j.job_id = sr.platform_job_id "
                            "LEFT JOIN artifact_revisions ar ON ar.job_id = j.job_id "
                            "ORDER BY COALESCE(sr.finished_at, sr.started_at) DESC NULLS LAST, "
                            "sr.workflow_id, sr.attempt, sr.step_key LIMIT 500"
                        )
                    )
                )
                jobs = self._rows(
                    connection.execute(
                        text(
                            "SELECT j.job_id, j.protocol_version, j.idempotency_key, j.task_type, "
                            "j.request, j.status, j.logical_artifact_id, j.revision_id, "
                            "j.worker_slot_id, j.worker_exit_code, j.error_code, j.error_message, "
                            "j.created_at, j.updated_at, j.completed_at, ws.role AS worker_role, "
                            "ws.linux_user AS worker_linux_user, ar.content_hash, ar.manifest_hash, "
                            "ar.content_bytes, ar.result, ar.created_at AS artifact_created_at "
                            "FROM jobs j LEFT JOIN worker_slots ws ON ws.slot_id = j.worker_slot_id "
                            "LEFT JOIN artifact_revisions ar ON ar.job_id = j.job_id "
                            "ORDER BY j.updated_at DESC, j.job_id LIMIT 500"
                        )
                    )
                )
                job_events = self._rows(
                    connection.execute(
                        text(
                            "SELECT je.event_id, je.job_id, je.sequence, je.from_state, je.to_state, "
                            "je.event, je.created_at, j.worker_slot_id, ws.role AS worker_role, "
                            "sr.workflow_id, sr.step_run_id, sr.step_key, sr.attempt, "
                            "j.logical_artifact_id, j.revision_id, j.error_code "
                            "FROM job_events je JOIN jobs j ON j.job_id = je.job_id "
                            "LEFT JOIN worker_slots ws ON ws.slot_id = j.worker_slot_id "
                            "LEFT JOIN workflow_step_runs sr ON sr.platform_job_id = j.job_id "
                            "ORDER BY je.created_at DESC, je.event_id DESC LIMIT :event_limit"
                        ),
                        {"event_limit": self.event_limit},
                    )
                )
                workflow_events = self._rows(
                    connection.execute(
                        text(
                            "SELECT event_id, workflow_id, sequence, event_type, prior_state, "
                            "new_state, step_key, command_id, created_at "
                            "FROM workflow_events ORDER BY created_at DESC, event_id DESC "
                            "LIMIT :event_limit"
                        ),
                        {"event_limit": self.event_limit},
                    )
                )
                approvals = self._rows(
                    connection.execute(
                        text(
                            "SELECT approval_request_id, workflow_id, step_run_id, status, "
                            "allowed_roles, allowed_rework_targets, requested_at, resolved_at, "
                            "decision, rework_target_step "
                            "FROM approval_requests ORDER BY requested_at DESC, approval_request_id "
                            "LIMIT 200"
                        )
                    )
                )
                revisions = self._rows(
                    connection.execute(
                        text(
                            "SELECT ar.revision_id, ar.logical_artifact_id, ar.job_id, "
                            "ar.content_hash, ar.manifest_hash, ar.content_bytes, ar.approved, "
                            "ar.created_at, a.artifact_type, a.created_at AS artifact_created_at, "
                            "ar.result "
                            "FROM artifact_revisions ar JOIN artifacts a "
                            "ON a.logical_artifact_id = ar.logical_artifact_id "
                            "ORDER BY ar.created_at DESC, ar.revision_id LIMIT 500"
                        )
                    )
                )
                counts_row = (
                    connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM workflow_instances WHERE state NOT IN "
                            "('COMPLETED','FAILED','CANCELLED')) AS active_workflows, "
                            "(SELECT count(*) FROM approval_requests WHERE status='PENDING') "
                            "AS waiting_approvals, "
                            "(SELECT count(*) FROM jobs WHERE status IN ('CREATED','VALIDATED','QUEUED')) "
                            "AS queued_jobs, "
                            "(SELECT count(*) FROM jobs WHERE status IN "
                            "('CLAIMED','RUNNING','VALIDATING_RESULT','COMMITTING')) AS running_jobs, "
                            "(SELECT count(*) FROM jobs WHERE status='FAILED' "
                            "AND updated_at >= now() - interval '1 hour') AS failed_jobs_recent, "
                            "(SELECT count(*) FROM workflow_instances) AS workflow_count, "
                            "(SELECT count(*) FROM jobs) AS job_count"
                        )
                    )
                    .mappings()
                    .one()
                )
                return SnapshotRows(
                    workers=workers,
                    workflows=workflows,
                    steps=steps,
                    jobs=jobs,
                    job_events=job_events,
                    workflow_events=workflow_events,
                    approvals=approvals,
                    revisions=revisions,
                    counts=dict(counts_row),
                )
        except DBAPIError as exc:
            code = (
                ObserveErrorCode.OBSERVE_DATABASE_TIMEOUT
                if "statement timeout" in str(exc).lower()
                else ObserveErrorCode.OBSERVE_DATABASE_UNAVAILABLE
            )
            raise ObserveError(code, "observability database query failed") from exc
        except SQLAlchemyError as exc:
            raise ObserveError(
                ObserveErrorCode.OBSERVE_QUERY_FAILED, "observability query failed"
            ) from exc

    def operational_overview_rows(
        self, *, recent_failure_window_seconds: int, attention_limit: int
    ) -> OperationalOverviewRows:
        """Return one exact read-only operational classification snapshot."""

        if not 60 <= recent_failure_window_seconds <= 86_400:
            raise ValueError("recent failure window is outside the contract")
        if not 1 <= attention_limit <= 100:
            raise ValueError("attention limit is outside the contract")
        active_command_states = "('PENDING','LEASED','PROCESSING')"
        active_job_states = (
            "('CREATED','VALIDATED','QUEUED','CLAIMED','RUNNING','VALIDATING_RESULT','COMMITTING')"
        )
        held_lease_states = "('ACTIVE','RECONCILING')"
        nonterminal_workflow_states = (
            "('REQUESTED','RUNNING','AWAITING_HUMAN_APPROVAL','REWORK_REQUESTED',"
            "'APPROVED','REGISTERING')"
        )
        active_workflow_ids = (
            "SELECT workflow_id FROM workflow_commands WHERE state IN "
            f"{active_command_states} UNION "
            "SELECT sr.workflow_id FROM workflow_step_runs sr JOIN jobs j "
            "ON j.job_id=sr.platform_job_id WHERE j.status IN "
            f"{active_job_states} UNION "
            "SELECT workflow_id FROM worker_leases WHERE state IN "
            f"{held_lease_states}"
        )
        parameters = {
            "recent_failure_window_seconds": recent_failure_window_seconds,
            "attention_limit": attention_limit,
        }
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                counts = dict(
                    connection.execute(
                        text(
                            "WITH active_workflow_ids AS ("
                            + active_workflow_ids
                            + ") SELECT transaction_timestamp() AS observed_at, "
                            "(SELECT count(command_id) FROM workflow_commands WHERE state IN "
                            + active_command_states
                            + ") AS active_workflow_commands, "
                            "(SELECT count(*) FROM jobs WHERE status IN "
                            + active_job_states
                            + ") AS active_jobs, "
                            "(SELECT count(lease_id) FROM worker_leases WHERE state IN "
                            + held_lease_states
                            + ") AS held_worker_leases, "
                            "(SELECT count(api_idempotency_record_id) FROM api_idempotency_records "
                            "WHERE state='PROCESSING') AS processing_api_requests, "
                            "(SELECT count(*) FROM approval_requests "
                            "WHERE status='PENDING') AS pending_human_approvals, "
                            "(SELECT count(*) FROM active_workflow_ids) AS executable_workflows, "
                            "(SELECT count(*) FROM workflow_instances w WHERE w.state IN "
                            + nonterminal_workflow_states
                            + " AND NOT EXISTS (SELECT 1 FROM active_workflow_ids a "
                            "WHERE a.workflow_id=w.workflow_id) AND NOT EXISTS "
                            "(SELECT 1 FROM approval_requests p WHERE p.workflow_id=w.workflow_id "
                            "AND p.status='PENDING')) AS quiescent_nonterminal_workflows, "
                            "(SELECT count(*) FROM workflow_instances WHERE state='FAILED' "
                            "AND updated_at >= transaction_timestamp() - "
                            "(:recent_failure_window_seconds * interval '1 second')) "
                            "AS recent_failed_workflows, "
                            "(SELECT count(*) FROM jobs WHERE status='FAILED' AND updated_at >= "
                            "transaction_timestamp() - (:recent_failure_window_seconds * "
                            "interval '1 second')) AS recent_failed_jobs, "
                            "(SELECT count(*) FROM workflow_instances WHERE state='FAILED' "
                            "AND updated_at < transaction_timestamp() - "
                            "(:recent_failure_window_seconds * interval '1 second')) "
                            "AS historical_failed_workflows, "
                            "(SELECT count(*) FROM jobs WHERE status='FAILED' AND updated_at < "
                            "transaction_timestamp() - (:recent_failure_window_seconds * "
                            "interval '1 second')) AS historical_failed_jobs"
                        ),
                        parameters,
                    )
                    .mappings()
                    .one()
                )
                observed_at = counts.pop("observed_at")
                attention = self._rows(
                    connection.execute(
                        text(
                            "WITH active_workflow_ids AS ("
                            + active_workflow_ids
                            + "), attention AS ("
                            "SELECT 'QUIESCENT_NONTERMINAL_WORKFLOW' AS classification, "
                            "w.workflow_id, NULL::text AS job_id, NULL::text AS command_id, "
                            "NULL::text AS lease_id, NULL::text AS api_idempotency_record_id, "
                            "w.state, w.failure_code AS error_code, w.updated_at AS observed_at "
                            "FROM workflow_instances w WHERE w.state IN "
                            + nonterminal_workflow_states
                            + " AND NOT EXISTS (SELECT 1 FROM active_workflow_ids a "
                            "WHERE a.workflow_id=w.workflow_id) AND NOT EXISTS "
                            "(SELECT 1 FROM approval_requests p WHERE p.workflow_id=w.workflow_id "
                            "AND p.status='PENDING') UNION ALL "
                            "SELECT 'EXPIRED_WORKFLOW_COMMAND_CLAIM', c.workflow_id, NULL::text, "
                            "c.command_id, NULL::text, NULL::text, c.state, c.error_code, "
                            "c.lease_expires_at FROM workflow_commands c WHERE c.state IN "
                            "('LEASED','PROCESSING') AND c.lease_expires_at <= "
                            "transaction_timestamp() UNION ALL "
                            "SELECT 'EXPIRED_WORKER_LEASE', l.workflow_id, l.job_id, NULL::text, "
                            "l.lease_id, NULL::text, l.state, NULL::text, l.expires_at "
                            "FROM worker_leases l WHERE l.state IN "
                            + held_lease_states
                            + " AND l.expires_at <= transaction_timestamp() UNION ALL "
                            "SELECT 'EXPIRED_API_IDEMPOTENCY_CLAIM', NULL::text, NULL::text, "
                            "NULL::text, NULL::text, i.api_idempotency_record_id, i.state, "
                            "i.error_code, i.lease_expires_at FROM api_idempotency_records i "
                            "WHERE i.state='PROCESSING' AND i.lease_expires_at <= "
                            "transaction_timestamp() UNION ALL "
                            "SELECT 'RECENT_FAILED_WORKFLOW', w.workflow_id, NULL::text, NULL::text, "
                            "NULL::text, NULL::text, w.state, w.failure_code, w.updated_at "
                            "FROM workflow_instances w WHERE w.state='FAILED' AND w.updated_at >= "
                            "transaction_timestamp() - (:recent_failure_window_seconds * "
                            "interval '1 second') UNION ALL "
                            "SELECT 'RECENT_FAILED_JOB', sr.workflow_id, j.job_id, NULL::text, "
                            "NULL::text, NULL::text, j.status, j.error_code, j.updated_at "
                            "FROM jobs j LEFT JOIN LATERAL (SELECT workflow_id FROM "
                            "workflow_step_runs WHERE platform_job_id=j.job_id ORDER BY "
                            "workflow_id LIMIT 1) sr ON true WHERE j.status='FAILED' AND "
                            "j.updated_at >= transaction_timestamp() - "
                            "(:recent_failure_window_seconds * interval '1 second')) "
                            "SELECT classification, workflow_id, job_id, command_id, lease_id, "
                            "api_idempotency_record_id, state, error_code, observed_at FROM attention "
                            "ORDER BY observed_at DESC, classification DESC, "
                            "COALESCE(workflow_id,job_id,command_id,lease_id,"
                            "api_idempotency_record_id) DESC LIMIT :attention_limit"
                        ),
                        parameters,
                    )
                )
                return OperationalOverviewRows(
                    observed_at=observed_at,
                    counts=counts,
                    attention=attention,
                )
        except DBAPIError as exc:
            code = (
                ObserveErrorCode.OBSERVE_DATABASE_TIMEOUT
                if "statement timeout" in str(exc).lower()
                else ObserveErrorCode.OBSERVE_DATABASE_UNAVAILABLE
            )
            raise ObserveError(code, "operational overview query failed") from exc
        except SQLAlchemyError as exc:
            raise ObserveError(
                ObserveErrorCode.OBSERVE_QUERY_FAILED, "operational overview query failed"
            ) from exc

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return bool(connection.scalar(text("SELECT 1")) == 1)
        except SQLAlchemyError:
            return False

    def database_is_readonly(self) -> bool:
        try:
            with self.engine.connect() as connection:
                value = connection.scalar(text("SHOW default_transaction_read_only"))
                return str(value).lower() == "on"
        except SQLAlchemyError:
            return False

    def insert_is_denied(self) -> bool:
        statement = text(
            "INSERT INTO worker_slots (slot_id,linux_user,role,enabled,gpu) "
            "VALUES ('zz','observe-denied','support',false,false)"
        )
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.execute(statement)
                connection.rollback()
        except DBAPIError:
            return True
        return False

    def required_tables(self) -> list[str]:
        names = REQUIRED_READ_MODEL_TABLES
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=current_schema() AND table_name = ANY(:names) "
                    "ORDER BY table_name"
                ),
                {"names": list(names)},
            ).scalars()
            return list(rows)

    def workflow_rows(
        self, workflow_id: str
    ) -> tuple[
        dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
    ]:
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            workflow_row = (
                connection.execute(
                    text(
                        "SELECT workflow_id, definition_key, definition_version, definition_hash, "
                        "state, stage, current_step_key, initial_request, rework_cycle_count, "
                        "created_at, updated_at, completed_at, failure_code, failure_summary "
                        "FROM workflow_instances WHERE workflow_id=:workflow_id"
                    ),
                    {"workflow_id": workflow_id},
                )
                .mappings()
                .one_or_none()
            )
            if workflow_row is None:
                return None, [], [], []
            steps = self._rows(
                connection.execute(
                    text(
                        "SELECT sr.*, j.idempotency_key, j.logical_artifact_id, j.revision_id, "
                        "j.worker_exit_code, ar.content_hash, ar.manifest_hash, ar.content_bytes, "
                        "ar.result FROM workflow_step_runs sr "
                        "LEFT JOIN jobs j ON j.job_id=sr.platform_job_id "
                        "LEFT JOIN artifact_revisions ar ON ar.job_id=j.job_id "
                        "WHERE sr.workflow_id=:workflow_id ORDER BY sr.attempt, sr.step_key"
                    ),
                    {"workflow_id": workflow_id},
                )
            )
            approvals = self._rows(
                connection.execute(
                    text(
                        "SELECT approval_request_id, workflow_id, step_run_id, status, "
                        "allowed_roles, allowed_rework_targets, requested_at, resolved_at, "
                        "decision, rework_target_step FROM approval_requests "
                        "WHERE workflow_id=:workflow_id ORDER BY requested_at"
                    ),
                    {"workflow_id": workflow_id},
                )
            )
            events = self._rows(
                connection.execute(
                    text(
                        "SELECT event_id, workflow_id, sequence, event_type, prior_state, "
                        "new_state, step_key, command_id, created_at FROM workflow_events "
                        "WHERE workflow_id=:workflow_id ORDER BY sequence"
                    ),
                    {"workflow_id": workflow_id},
                )
            )
            return dict(workflow_row), steps, approvals, events

    def job_rows(self, job_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            row = (
                connection.execute(
                    text(
                        "SELECT j.*, ws.role AS worker_role, ws.linux_user AS worker_linux_user, "
                        "ar.content_hash, ar.manifest_hash, ar.content_bytes, ar.result "
                        "FROM jobs j LEFT JOIN worker_slots ws ON ws.slot_id=j.worker_slot_id "
                        "LEFT JOIN artifact_revisions ar ON ar.job_id=j.job_id WHERE j.job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None, []
            events = self._rows(
                connection.execute(
                    text(
                        "SELECT je.event_id, je.job_id, je.sequence, je.from_state, je.to_state, "
                        "je.event, je.created_at, j.worker_slot_id, ws.role AS worker_role, "
                        "sr.workflow_id, sr.step_run_id, sr.step_key, sr.attempt, "
                        "j.logical_artifact_id, j.revision_id, j.error_code "
                        "FROM job_events je JOIN jobs j ON j.job_id=je.job_id "
                        "LEFT JOIN worker_slots ws ON ws.slot_id=j.worker_slot_id "
                        "LEFT JOIN workflow_step_runs sr ON sr.platform_job_id=j.job_id "
                        "WHERE je.job_id=:job_id ORDER BY je.sequence"
                    ),
                    {"job_id": job_id},
                )
            )
            return dict(row), events

    def artifact_rows(self, artifact_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            artifact = (
                connection.execute(
                    text(
                        "SELECT logical_artifact_id, job_id, artifact_type, approved, created_at "
                        "FROM artifacts WHERE logical_artifact_id=:artifact_id"
                    ),
                    {"artifact_id": artifact_id},
                )
                .mappings()
                .one_or_none()
            )
            if artifact is None:
                return None, []
            revisions = self._rows(
                connection.execute(
                    text(
                        "SELECT revision_id, logical_artifact_id, job_id, content_hash, "
                        "manifest_hash, content_bytes, result, approved, created_at "
                        "FROM artifact_revisions WHERE logical_artifact_id=:artifact_id "
                        "ORDER BY created_at, revision_id"
                    ),
                    {"artifact_id": artifact_id},
                )
            )
            return dict(artifact), revisions
