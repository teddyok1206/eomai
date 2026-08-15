"""Build validated, metadata-only snapshots and detail projections."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from eom_observe_contracts import (
    ApprovalSummary,
    ArtifactDetail,
    ArtifactRevisionSummary,
    DataFreshness,
    JobDetail,
    ObserveSnapshot,
    SnapshotSummary,
    StepRunSummary,
    WorkflowDetail,
    validate_contract,
)

from eom_observe.event_mapper import map_job_event, map_workflow_event, merge_events
from eom_observe.redaction import (
    logical_artifact_uri,
    metadata_summary,
    sanitize_error,
    shortened_hash,
)
from eom_observe.repository import ObserveRepository
from eom_observe.settings import REPOSITORY_ROOT, ObserveSettings
from eom_observe.state_derivation import derive_edges, derive_nodes
from eom_observe.system_probe import probe_system


def deployment_revision(repository_root: Path = REPOSITORY_ROOT) -> str:
    try:
        git_dir = repository_root / ".git"
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            return (git_dir / ref).read_text(encoding="ascii").strip()[:12]
        return head[:12]
    except OSError:
        return "unknown"


def canonical_snapshot_hash(value: dict[str, Any]) -> str:
    content = dict(value)
    content.pop("snapshot_id", None)
    content.pop("content_hash", None)
    content.pop("generated_at", None)
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class SnapshotBuilder:
    def __init__(self, repository: ObserveRepository, settings: ObserveSettings) -> None:
        self.repository = repository
        self.settings = settings

    def build(self, *, now: datetime | None = None) -> ObserveSnapshot:
        build_started = perf_counter()
        generated_at = now or datetime.now(UTC)
        query_started = perf_counter()
        rows = self.repository.snapshot_rows()
        query_duration_ms = (perf_counter() - query_started) * 1000
        probe = probe_system()
        events = merge_events(
            job_events=rows.job_events,
            workflow_events=rows.workflow_events,
            steps=rows.steps,
            approvals=rows.approvals,
            revisions=rows.revisions,
            limit=self.settings.snapshot.recent_event_limit,
        )
        nodes = derive_nodes(
            workers=rows.workers,
            workflows=rows.workflows,
            steps=rows.steps,
            jobs=rows.jobs,
            approvals=rows.approvals,
            events=events,
            privacy=self.settings.privacy,
            database_fresh=True,
            system_probe_fresh=probe.fresh,
            available_workers=probe.users_present if probe.fresh else None,
            now=generated_at,
        )
        edges = derive_edges(
            events,
            active_seconds=self.settings.ui.edge_activity_seconds,
            now=generated_at,
        )
        summary = SnapshotSummary(
            active_workflows=int(rows.counts["active_workflows"]),
            waiting_approvals=int(rows.counts["waiting_approvals"]),
            queued_jobs=int(rows.counts["queued_jobs"]),
            running_jobs=int(rows.counts["running_jobs"]),
            failed_jobs_recent=int(rows.counts["failed_jobs_recent"]),
            idle_workers=sum(node.status == "IDLE" for node in nodes if node.node_type == "WORKER"),
        )
        partial = {
            "schema_version": "1.0",
            "deployment_revision": deployment_revision(),
            "data_freshness": DataFreshness(
                database="fresh", system_probe="fresh" if probe.fresh else "unknown"
            ).model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
            "recent_events": [event.model_dump(mode="json") for event in events],
        }
        content_hash = canonical_snapshot_hash(partial)
        snapshot = ObserveSnapshot(
            snapshot_id=f"snapshot_{content_hash.removeprefix('sha256:')[:32]}",
            content_hash=content_hash,
            generated_at=generated_at,
            deployment_revision=deployment_revision(),
            data_freshness=DataFreshness(
                database="fresh", system_probe="fresh" if probe.fresh else "unknown"
            ),
            summary=summary,
            nodes=nodes,
            edges=edges,
            recent_events=events,
        )
        validate_contract("snapshot", snapshot.model_dump(mode="json"))
        logging.getLogger("eom_observe.snapshot").info(
            "observability snapshot built",
            extra={
                "event": "SNAPSHOT_BUILT",
                "snapshot_id": snapshot.snapshot_id,
                "query_duration_ms": round(query_duration_ms, 3),
                "snapshot_duration_ms": round((perf_counter() - build_started) * 1000, 3),
            },
        )
        return snapshot

    def stale_copy(
        self, snapshot: ObserveSnapshot, *, now: datetime | None = None
    ) -> ObserveSnapshot:
        value = snapshot.model_dump(mode="json")
        value["generated_at"] = now or datetime.now(UTC)
        value["data_freshness"] = {"database": "stale", "system_probe": "unknown"}
        content_hash = canonical_snapshot_hash(value)
        value["content_hash"] = content_hash
        value["snapshot_id"] = f"snapshot_{content_hash.removeprefix('sha256:')[:32]}"
        stale = ObserveSnapshot.model_validate(value)
        validate_contract("snapshot", stale.model_dump(mode="json"))
        return stale

    def workflow_detail(self, workflow_id: str) -> WorkflowDetail | None:
        workflow, steps, approvals, events = self.repository.workflow_rows(workflow_id)
        if workflow is None:
            return None
        mapped_events = [map_workflow_event(row) for row in events]
        step_models = []
        for row in steps:
            output = metadata_summary(row.get("result") or {}, self.settings.privacy)
            for key in ("logical_artifact_id", "revision_id", "content_bytes"):
                if row.get(key) is not None:
                    output[key] = row[key]
            step_models.append(
                StepRunSummary(
                    step_run_id=row["step_run_id"],
                    step_key=row["step_key"],
                    attempt=row["attempt"],
                    step_type=row["step_type"],
                    worker_role=row.get("worker_role"),
                    result_schema=row.get("result_schema"),
                    state=row["state"],
                    platform_job_id=row.get("platform_job_id"),
                    input_summary=metadata_summary(
                        row.get("input_pointer_manifest") or {}, self.settings.privacy
                    ),
                    output_summary=output,
                    started_at=row.get("started_at"),
                    finished_at=row.get("finished_at"),
                    error_code=row.get("error_code"),
                    error_summary=sanitize_error(row.get("error_summary")),
                    superseded_by_step_run_id=row.get("superseded_by_step_run_id"),
                )
            )
        detail = WorkflowDetail(
            workflow_id=workflow_id,
            definition_key=workflow["definition_key"],
            definition_version=workflow["definition_version"],
            definition_hash=workflow["definition_hash"],
            state=workflow["state"],
            stage=workflow["stage"],
            current_step_key=workflow["current_step_key"],
            rework_cycle_count=workflow["rework_cycle_count"],
            created_at=workflow["created_at"],
            updated_at=workflow["updated_at"],
            completed_at=workflow.get("completed_at"),
            failure_code=workflow.get("failure_code"),
            failure_summary=sanitize_error(workflow.get("failure_summary")),
            request_summary=metadata_summary(workflow["initial_request"], self.settings.privacy),
            step_runs=step_models,
            approvals=[
                ApprovalSummary(
                    approval_request_id=row["approval_request_id"],
                    step_run_id=row["step_run_id"],
                    status=row["status"],
                    allowed_roles=row["allowed_roles"],
                    allowed_rework_targets=row["allowed_rework_targets"],
                    requested_at=row["requested_at"],
                    resolved_at=row.get("resolved_at"),
                    decision=row.get("decision"),
                    rework_target_step=row.get("rework_target_step"),
                )
                for row in approvals
            ],
            events=mapped_events,
        )
        validate_contract("workflow-detail", detail.model_dump(mode="json"))
        return detail

    def job_detail(self, job_id: str) -> JobDetail | None:
        job, events = self.repository.job_rows(job_id)
        if job is None:
            return None
        input_summary = metadata_summary(job["request"], self.settings.privacy)
        if job.get("idempotency_key"):
            input_summary["idempotency_key_hash"] = shortened_hash(job["idempotency_key"])
        output = metadata_summary(job.get("result") or {}, self.settings.privacy)
        for key in ("logical_artifact_id", "revision_id", "content_bytes"):
            if job.get(key) is not None:
                output[key] = job[key]
        detail = JobDetail(
            job_id=job_id,
            status=job["status"],
            task_type=job["task_type"],
            protocol_version=job["protocol_version"],
            worker_slot_id=job.get("worker_slot_id"),
            worker_role=job.get("worker_role"),
            worker_linux_user=job.get("worker_linux_user"),
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            completed_at=job.get("completed_at"),
            input_summary=input_summary,
            output_summary=output,
            error_code=job.get("error_code"),
            error_summary=sanitize_error(job.get("error_message")),
            artifact_id=job.get("logical_artifact_id"),
            revision_id=job.get("revision_id"),
            events=[map_job_event(row) for row in events],
        )
        validate_contract("job-detail", detail.model_dump(mode="json"))
        return detail

    def artifact_detail(self, artifact_id: str) -> ArtifactDetail | None:
        artifact, revisions = self.repository.artifact_rows(artifact_id)
        if artifact is None:
            return None
        detail = ArtifactDetail(
            artifact_id=artifact_id,
            artifact_type=artifact["artifact_type"],
            approved=artifact["approved"],
            job_id=artifact["job_id"],
            created_at=artifact["created_at"],
            revisions=[
                ArtifactRevisionSummary(
                    revision_id=row["revision_id"],
                    content_hash=row["content_hash"],
                    manifest_hash=row["manifest_hash"],
                    content_bytes=row["content_bytes"],
                    logical_uri=logical_artifact_uri(artifact_id, row["revision_id"]),
                    approved=row["approved"],
                    result_status=(row.get("result") or {}).get("status"),
                    schema_version=(row.get("result") or {}).get("protocol_version"),
                    created_at=row["created_at"],
                )
                for row in revisions
            ],
        )
        validate_contract("artifact-detail", detail.model_dump(mode="json"))
        return detail
