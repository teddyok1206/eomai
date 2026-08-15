"""Synchronous vertical-slice orchestrator."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_orchestrator.artifacts import commit_artifact, stage_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.logging import log_event
from eom_orchestrator.models import JobRecord
from eom_orchestrator.protocol import protocol_schema_hash
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_job,
    upsert_worker_slot,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job
from eom_orchestrator.worker import CodexWorkerAdapter, load_worker_result
from eom_orchestrator.worker_registry import WorkerRegistry, WorkerSlot

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
        self.registry = WorkerRegistry.load(self.settings.worker_config)
        self.worker_adapter = worker_adapter or CodexWorkerAdapter(self.settings)

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

    def _transition(self, job_id: str, target: JobState, event: str) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event)

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
