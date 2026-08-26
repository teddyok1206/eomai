"""Synchronous vertical-slice orchestrator."""

from __future__ import annotations

import grp
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_protocol import (
    ArtifactSpec,
    ErrorCode,
    JobRequest,
    SchemaValidationError,
    SmokePayload,
    WorkerInput,
    WorkerResult,
    validate_message,
)
from eom_workflow.models import (
    ArtifactPointer,
    KnowledgeAnalysisProposalRoleResult,
    KnowledgeAnalysisProposalRoleResultV2,
    KnowledgeAnalysisProposalRoleResultV3,
    KnowledgeAnalysisWorkerRequest,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.models import ArtifactSpec as WorkflowArtifactSpec
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    result_schema_protocol,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_orchestrator.artifacts import (
    commit_artifact,
    commit_file_set_artifact,
    stage_artifact,
    stage_structured_artifact,
)
from eom_orchestrator.capacity_controller import CodexCapacityController, LeaseClaim
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.execution_materializer import (
    MaterializedExecution,
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_orchestrator.logging import log_event
from eom_orchestrator.models import JobRecord
from eom_orchestrator.protocol import protocol_schema_hash
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_job,
    submit_structured_job,
    upsert_worker_slot,
)
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job
from eom_orchestrator.worker import CodexWorkerAdapter, load_worker_result
from eom_orchestrator.worker_registry import WorkerSlot

LOGGER = logging.getLogger("eom.orchestrator")
TERMINAL_STATES = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}


class Orchestrator:
    def __init__(
        self,
        engine: Engine,
        settings: Settings | None = None,
        worker_adapter: CodexWorkerAdapter | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.sessions = build_session_factory(engine)
        self.registry = resolve_worker_configuration(self.settings).registry
        self.worker_adapter = worker_adapter or CodexWorkerAdapter(self.settings)
        self.capacity = CodexCapacityController(self.sessions)

    def submit(self, message: str, idempotency_key: str | None = None) -> JobRecord:
        request = JobRequest(
            job_id=new_job_id(),
            idempotency_key=idempotency_key or f"request-{uuid4().hex}",
            payload=SmokePayload(message=message),
            artifact=ArtifactSpec(
                logical_artifact_id=new_logical_artifact_id(), revision_id=new_revision_id()
            ),
            submitted_at=datetime.now(UTC),
        )
        with transaction(self.sessions) as session:
            self._sync_registry(session)
            ensure_protocol_version(session, request.protocol_version, protocol_schema_hash())
            job, created = submit_job(session, request)
        if not created:
            return self.get_job(job.job_id)

        slot: WorkerSlot | None = None
        try:
            validate_message("job-request", request.model_dump(mode="json"))
            self._transition(request.job_id, JobState.VALIDATED, "REQUEST_VALIDATED")
            self._transition(request.job_id, JobState.QUEUED, "JOB_QUEUED")
            slot = self.registry.select("authoring")
            with transaction(self.sessions) as session:
                claimed = session.get(JobRecord, request.job_id)
                if claimed is None:
                    raise RuntimeError("created job disappeared")
                claimed.worker_slot_id = slot.slot_id
                transition_job(
                    session,
                    request.job_id,
                    JobState.CLAIMED,
                    "WORKER_CLAIMED",
                    data={"worker_slot": slot.slot_id, "linux_user": slot.linux_user},
                )
            self._transition(request.job_id, JobState.RUNNING, "WORKER_STARTED")
            staging = self.settings.staging_root / request.job_id
            try:
                staging.mkdir(mode=0o750, parents=False, exist_ok=False)
            except OSError as exc:
                raise PlatformError(
                    ErrorCode.WORKER_EXEC_FAILED, "failed to create job staging directory"
                ) from exc
            worker_input = WorkerInput(
                job_id=request.job_id,
                payload=request.payload,
                artifact=request.artifact,
                submitted_at=request.submitted_at,
            )
            validate_message("worker-input", worker_input.model_dump(mode="json"))
            run = self.worker_adapter.run(worker_input, slot, staging)
            with transaction(self.sessions) as session:
                running = session.get(JobRecord, request.job_id)
                if running is None:
                    raise RuntimeError("running job disappeared")
                running.worker_exit_code = run.exit_code
                running.worker_stdout_path = str(run.stdout_path)
                running.worker_stderr_path = str(run.stderr_path)
            if run.exit_code != 0:
                raise PlatformError(
                    ErrorCode.WORKER_EXEC_FAILED, f"worker exited with code {run.exit_code}"
                )

            self._transition(request.job_id, JobState.VALIDATING_RESULT, "WORKER_RESULT_RECEIVED")
            raw_result = load_worker_result(run.result_path, run.result_path.parent)
            result = self._parse_worker_result(raw_result)
            self._validate_result_identity(request, result)
            staged = stage_artifact(result=result, staging=staging, worker_slot=slot.slot_id)
            self._transition(request.job_id, JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED")
            final_path = commit_artifact(staged, self.settings.nas_artifact_root)
            with transaction(self.sessions) as session:
                committing = session.execute(
                    select(JobRecord).where(JobRecord.job_id == request.job_id).with_for_update()
                ).scalar_one()
                create_artifact_records(
                    session,
                    job=committing,
                    content_hash=staged.content_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.manifest.content_bytes,
                    nas_path=str(final_path),
                    manifest=staged.manifest.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                )
                transition_job(
                    session,
                    request.job_id,
                    JobState.SUCCEEDED,
                    "ARTIFACT_COMMITTED",
                    data={
                        "logical_artifact_id": request.artifact.logical_artifact_id,
                        "revision_id": request.artifact.revision_id,
                        "content_hash": staged.content_hash,
                    },
                )
            log_event(
                LOGGER,
                logging.INFO,
                "job succeeded",
                job_id=request.job_id,
                worker_slot=slot.slot_id,
                component="orchestrator",
                event="JOB_SUCCEEDED",
            )
        except (SchemaValidationError, ValidationError) as exc:
            self._fail(request.job_id, ErrorCode.PROTOCOL_VALIDATION_FAILED, str(exc), slot)
        except PlatformError as exc:
            self._fail(request.job_id, exc.code, str(exc), slot)
        except SQLAlchemyError as exc:
            self._fail(request.job_id, ErrorCode.DATABASE_ERROR, "database operation failed", slot)
            raise PlatformError(ErrorCode.DATABASE_ERROR, "database operation failed") from exc
        return self.get_job(request.job_id)

    def get_job(self, job_id: str) -> JobRecord:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise KeyError(job_id)
            session.expunge(job)
            return job

    def submit_workflow_role(
        self,
        *,
        workflow_id: str,
        step_run_id: str,
        step_key: str,
        attempt: int,
        role: str,
        request: WorkerRequest | KnowledgeAnalysisWorkerRequest,
        upstream_artifacts: tuple[ArtifactPointer, ...],
        result_schema: str,
        idempotency_key: str,
        prompt_path: Path | None = None,
        prompt_text: str | None = None,
        before_execute: Callable[[str], None] | None = None,
    ) -> JobRecord:
        if (prompt_path is None) == (prompt_text is None):
            raise ValueError("exactly one workflow prompt source is required")
        existing = self._job_by_idempotency_key(idempotency_key)
        if existing is not None:
            stored = existing.request
            if (
                stored.get("workflow_id") != workflow_id
                or stored.get("step_run_id") != step_run_id
                or stored.get("role") != role
                or stored.get("attempt") != attempt
            ):
                raise ValueError("workflow role idempotency key conflicts with stored job")
            if existing.status != JobState.QUEUED.value:
                return existing
            job_id = existing.job_id
            worker_input = RoleWorkerInput.model_validate(existing.request)
            input_document = worker_input.model_dump(mode="json")
            artifact = worker_input.artifact
            protocol_version = worker_input.protocol_version
        else:
            job_id = new_job_id()
            artifact = WorkflowArtifactSpec(
                logical_artifact_id=new_logical_artifact_id(), revision_id=new_revision_id()
            )
            protocol_version = result_schema_protocol(result_schema)
            worker_input = RoleWorkerInput(
                protocol_version=protocol_version,
                job_id=job_id,
                workflow_id=workflow_id,
                step_run_id=step_run_id,
                attempt=attempt,
                role=cast(
                    Literal["authoring", "image", "review", "item_management", "support"],
                    role,
                ),
                request=request,
                upstream_artifacts=upstream_artifacts,
                artifact=artifact,
            )
            input_document = worker_input.model_dump(mode="json")
            validate_role_input(input_document, role, protocol_version)
        if prompt_text is None:
            assert prompt_path is not None
            prompt_text = prompt_path.read_text(encoding="utf-8")
        if existing is None:
            with transaction(self.sessions) as session:
                self._sync_registry(session)
                ensure_protocol_version(
                    session, protocol_version, role_schema_bundle_hash(protocol_version)
                )
                job, created = submit_structured_job(
                    session,
                    job_id=job_id,
                    protocol_version=protocol_version,
                    idempotency_key=idempotency_key,
                    task_type=f"workflow_{role}",
                    request=input_document,
                    logical_artifact_id=artifact.logical_artifact_id,
                    revision_id=artifact.revision_id,
                )
            if not created:
                return self.get_job(job.job_id)
            self._transition(job_id, JobState.VALIDATED, "REQUEST_VALIDATED")
            self._transition(job_id, JobState.QUEUED, "JOB_QUEUED")

        if before_execute is not None:
            before_execute(job_id)

        slot: WorkerSlot | None = None
        lease_id: str | None = None
        worker_start_attempted = False
        worker_terminal_confirmed = False
        try:
            with self.sessions() as session:
                plan_record = session.scalar(
                    select(ResolvedExecutionPlanRecord).where(
                        ResolvedExecutionPlanRecord.workflow_id == workflow_id
                    )
                )
                if plan_record is not None:
                    plan_document = plan_record.canonical_document
                    plan_id = plan_record.plan_id
                else:
                    plan_document = None
                    plan_id = None
            if plan_document is not None:
                matching_steps = [
                    item
                    for item in plan_document.get("steps", [])
                    if isinstance(item, dict)
                    and item.get("role") == role
                    and item.get("step_key") == step_key
                ]
                if len(matching_steps) != 1 or plan_id is None:
                    raise ControlPlaneError(
                        "CONTROL_PLAN_STEP_MISSING", "workflow execution plan step is missing"
                    )
                plan_step = matching_steps[0]
                lease = self.capacity.claim(
                    LeaseClaim(
                        plan_id=plan_id,
                        step_key=str(plan_step["step_key"]),
                        job_id=job_id,
                        attempt=attempt,
                        workload_class=(
                            "KNOWLEDGE_ANALYSIS"
                            if request.request_name == "KNOWLEDGE_ANALYSIS_REQUEST"
                            else "CODEX"
                        ),
                        acquired_at=datetime.now(UTC),
                        ttl=timedelta(seconds=int(plan_step["timeout_seconds"])),
                    )
                )
                lease_id = lease.lease_id
                slot = self._slot_by_key(lease.slot_key)
            else:
                plan_step = None
                plan_id = None
                slot = self.registry.select(role)
            with transaction(self.sessions) as session:
                claimed = session.get(JobRecord, job_id)
                if claimed is None:
                    raise RuntimeError("created workflow job disappeared")
                claimed.worker_slot_id = slot.slot_id
                transition_job(
                    session,
                    job_id,
                    JobState.CLAIMED,
                    "WORKER_CLAIMED",
                    data={"worker_slot": slot.slot_id, "linux_user": slot.linux_user},
                )
            staging = self.settings.staging_root / job_id
            staging.mkdir(mode=0o750, parents=False, exist_ok=False)
            if plan_step is None or plan_id is None:
                self._transition(job_id, JobState.RUNNING, "WORKER_STARTED")
                run = self.worker_adapter.run_structured(
                    job_id=job_id,
                    input_document=input_document,
                    output_schema=constrained_result_schema(result_schema, worker_input),
                    prompt_text=prompt_text,
                    slot=slot,
                    staging=staging,
                )
            else:
                private_group = grp.getgrnam(slot.linux_user)

                def materialize(workspace: Path) -> MaterializedExecution:
                    with self.sessions() as materialization_session:
                        authorized = authorized_execution_artifact_revisions(
                            materialization_session,
                            plan_id=plan_id,
                            step_key=str(plan_step["step_key"]),
                        )
                        evidence = materialize_execution_step(
                            materialization_session,
                            plan_id=plan_id,
                            step_key=str(plan_step["step_key"]),
                            workspace=workspace,
                            canonical_artifact_root=self.settings.nas_artifact_root,
                            worker_group_id=private_group.gr_gid,
                            authorized_artifact_revision_ids=authorized,
                        )
                    event_data: dict[str, object] = dict(evidence.event_data())
                    self._transition(
                        job_id,
                        JobState.RUNNING,
                        "RESOLVED_WORKER_STARTED",
                        data=event_data,
                    )
                    return evidence

                worker_start_attempted = True
                resolved_run = self.worker_adapter.run_resolved_structured(
                    job_id=job_id,
                    input_document=input_document,
                    output_schema=constrained_result_schema(result_schema, worker_input),
                    prompt_text=prompt_text,
                    slot=slot,
                    staging=staging,
                    materialize=materialize,
                )
                worker_terminal_confirmed = True
                run = resolved_run.run
            with transaction(self.sessions) as session:
                running = session.get(JobRecord, job_id)
                if running is None:
                    raise RuntimeError("running workflow job disappeared")
                running.worker_exit_code = run.exit_code
                running.worker_stdout_path = str(run.stdout_path)
                running.worker_stderr_path = str(run.stderr_path)
            if run.exit_code != 0:
                raise PlatformError(
                    ErrorCode.WORKER_EXEC_FAILED, f"worker exited with code {run.exit_code}"
                )

            self._transition(job_id, JobState.VALIDATING_RESULT, "WORKER_RESULT_RECEIVED")
            raw_result = load_worker_result(run.result_path, run.result_path.parent)
            result = validate_role_result(raw_result, role, result_schema)
            if (
                result.job_id != worker_input.job_id
                or result.workflow_id != worker_input.workflow_id
                or result.step_run_id != worker_input.step_run_id
                or result.artifact != worker_input.artifact
            ):
                raise PlatformError(
                    ErrorCode.WORKER_RESULT_INVALID,
                    "workflow worker result identifiers do not match input",
                )
            result_document = result.model_dump(mode="json")
            if result_schema in {
                "knowledge-analysis-proposal-result@1.0",
                "knowledge-analysis-proposal-result@2.0",
                "knowledge-analysis-proposal-result@3.0",
            }:
                expected_result_type = {
                    "knowledge-analysis-proposal-result@1.0": (KnowledgeAnalysisProposalRoleResult),
                    "knowledge-analysis-proposal-result@2.0": (
                        KnowledgeAnalysisProposalRoleResultV2
                    ),
                    "knowledge-analysis-proposal-result@3.0": (
                        KnowledgeAnalysisProposalRoleResultV3
                    ),
                }[result_schema]
                if not isinstance(result, expected_result_type) or not isinstance(
                    worker_input.request, KnowledgeAnalysisWorkerRequest
                ):
                    raise PlatformError(
                        ErrorCode.WORKER_RESULT_INVALID,
                        "knowledge proposal typed boundary is inconsistent",
                    )
                staged_file_set, receipt = stage_knowledge_analysis_proposal(
                    proposal=result.output.proposal,
                    request=worker_input.request.analysis_request,
                    job_id=job_id,
                    logical_artifact_id=artifact.logical_artifact_id,
                    revision_id=artifact.revision_id,
                    staging=staging,
                )
                self._transition(job_id, JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED")
                final_path = commit_file_set_artifact(
                    staged_file_set, self.settings.nas_artifact_root
                )
                content_hash = staged_file_set.primary_hash
                manifest_hash = staged_file_set.manifest_hash
                content_bytes = staged_file_set.primary_bytes
                manifest_document = staged_file_set.manifest
                database_result = receipt.model_dump(mode="json")
            else:
                staged = stage_structured_artifact(
                    result=result_document,
                    job_id=job_id,
                    logical_artifact_id=artifact.logical_artifact_id,
                    revision_id=artifact.revision_id,
                    staging=staging,
                    worker_slot=slot.slot_id,
                )
                self._transition(job_id, JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED")
                final_path = commit_artifact(staged, self.settings.nas_artifact_root)
                content_hash = staged.content_hash
                manifest_hash = staged.manifest_hash
                content_bytes = staged.manifest.content_bytes
                manifest_document = staged.manifest.model_dump(mode="json")
                database_result = result_document
            with transaction(self.sessions) as session:
                committing = session.execute(
                    select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
                ).scalar_one()
                create_artifact_records(
                    session,
                    job=committing,
                    content_hash=content_hash,
                    manifest_hash=manifest_hash,
                    content_bytes=content_bytes,
                    nas_path=str(final_path),
                    manifest=manifest_document,
                    result=database_result,
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "ARTIFACT_COMMITTED",
                    data={
                        "logical_artifact_id": artifact.logical_artifact_id,
                        "revision_id": artifact.revision_id,
                        "content_hash": content_hash,
                    },
                )
        except WorkflowSchemaError as exc:
            self._fail(job_id, ErrorCode.WORKER_RESULT_INVALID, str(exc), slot)
        except ControlPlaneError as exc:
            if exc.code not in {
                "CONTROL_CAPACITY_EXHAUSTED",
                "CONTROL_KNOWLEDGE_CAPACITY_EXHAUSTED",
            }:
                self._fail(job_id, ErrorCode.WORKER_UNAVAILABLE, exc.code, slot)
        except PlatformError as exc:
            self._fail(job_id, exc.code, str(exc), slot)
        except OSError:
            self._fail(job_id, ErrorCode.WORKER_EXEC_FAILED, "workflow worker I/O failed", slot)
        except SQLAlchemyError as exc:
            self._fail(job_id, ErrorCode.DATABASE_ERROR, "database operation failed", slot)
            raise PlatformError(ErrorCode.DATABASE_ERROR, "database operation failed") from exc
        finally:
            if lease_id is not None:
                try:
                    observed_at = datetime.now(UTC)
                    if not worker_start_attempted or worker_terminal_confirmed:
                        final_job = self.get_job(job_id)
                        self.capacity.release(
                            lease_id=lease_id,
                            reason_code=(
                                "WORKER_ATTEMPT_SUCCEEDED"
                                if final_job.status == JobState.SUCCEEDED.value
                                else "WORKER_ATTEMPT_TERMINATED"
                            ),
                            released_at=observed_at,
                        )
                    else:
                        self.capacity.defer_uncertain_process(
                            lease_id=lease_id,
                            observed_at=observed_at,
                        )
                except (ControlPlaneError, SQLAlchemyError, KeyError):
                    LOGGER.exception("failed to release worker capacity lease")
        return self.get_job(job_id)

    def _job_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        with self.sessions() as session:
            job = session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == idempotency_key)
            )
            if job is not None:
                session.expunge(job)
            return job

    def _sync_registry(self, session: Session) -> None:
        for slot in self.registry.config.slots:
            upsert_worker_slot(
                session,
                slot_id=slot.slot_id,
                linux_user=slot.linux_user,
                role=slot.role,
                enabled=slot.enabled,
                gpu=slot.gpu,
            )

    def _transition(
        self,
        job_id: str,
        target: JobState,
        event: str,
        data: dict[str, object] | None = None,
    ) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event, data=data)

    def _slot_by_key(self, slot_key: str) -> WorkerSlot:
        slot_id = slot_key.removeprefix("slot")
        matches = [slot for slot in self.registry.config.slots if slot.slot_id == slot_id]
        if len(matches) != 1 or not matches[0].enabled:
            raise ControlPlaneError("CONTROL_LEASE_SLOT_MISSING", "leased worker slot is missing")
        return matches[0]

    def _fail(self, job_id: str, code: ErrorCode, message: str, slot: WorkerSlot | None) -> None:
        try:
            with transaction(self.sessions) as session:
                job = session.execute(
                    select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
                ).scalar_one()
                if JobState(job.status) not in TERMINAL_STATES:
                    job.error_code = code.value
                    job.error_message = message[:2048]
                    staging = self.settings.staging_root / job_id
                    stdout_path = staging / "worker.stdout.log"
                    stderr_path = staging / "worker.stderr.log"
                    if job.worker_stdout_path is None and stdout_path.is_file():
                        job.worker_stdout_path = str(stdout_path)
                    if job.worker_stderr_path is None and stderr_path.is_file():
                        job.worker_stderr_path = str(stderr_path)
                    transition_job(
                        session,
                        job_id,
                        JobState.FAILED,
                        "JOB_FAILED",
                        data={"error_code": code.value},
                    )
        except SQLAlchemyError:
            LOGGER.exception("failed to persist job failure")
        log_event(
            LOGGER,
            logging.ERROR,
            message,
            job_id=job_id,
            worker_slot=slot.slot_id if slot else None,
            component="orchestrator",
            event="JOB_FAILED",
            error_code=code.value,
        )

    @staticmethod
    def _parse_worker_result(raw_result: object) -> WorkerResult:
        try:
            validate_message("worker-result", raw_result)
            return WorkerResult.model_validate(raw_result)
        except (SchemaValidationError, ValidationError) as exc:
            raise PlatformError(
                ErrorCode.WORKER_RESULT_INVALID, "worker result failed protocol validation"
            ) from exc

    @staticmethod
    def _validate_result_identity(request: JobRequest, result: WorkerResult) -> None:
        if result.job_id != request.job_id or result.artifact != request.artifact:
            raise PlatformError(
                ErrorCode.WORKER_RESULT_INVALID,
                "worker result identifiers do not match worker input",
            )
