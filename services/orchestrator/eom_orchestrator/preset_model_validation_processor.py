"""Orchestrator-only processor for non-generating preset adapter acceptance."""

from __future__ import annotations

import hashlib
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_identifiers import canonical_json_bytes, new_logical_artifact_id, new_revision_id
from eom_workflow import ControlArtifactPointer
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES
from eom_workflow.preset_model_validation import PresetModelAcceptanceCases
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.control_models import ExecutionPresetValidationRecord
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, JobRecord
from eom_orchestrator.preset_lifecycle import (
    EVALUATION_SCHEMA_REF,
    record_execution_preset_evaluation,
)
from eom_orchestrator.preset_model_evidence import (
    CASES_SCHEMA_REF,
    validated_acceptance_checkpoint,
    validated_job_request,
)
from eom_orchestrator.preset_model_selection import validate_model_selection, validated_preset
from eom_orchestrator.preset_model_validation import (
    PROTOCOL,
    REQUEST_SCHEMA,
    TASK_TYPE,
    pinned_validation_revisions,
    validated_request,
)
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job

_LOCK_KEY = int.from_bytes(hashlib.sha256(b"eom:preset-model-validation").digest()[:8], signed=True)
_CHECKPOINT_EVENT = "PRESET_MODEL_ACCEPTANCE_STAGED"
_ADVANCING = (
    JobState.CREATED,
    JobState.VALIDATED,
    JobState.QUEUED,
    JobState.CLAIMED,
    JobState.RUNNING,
)


def _transient_commit_failure(error: BaseException) -> bool:
    """Only uncertain I/O/transaction failures recover; permanent contract errors terminalize."""

    if isinstance(error, OSError):
        return True
    if isinstance(error, PlatformError):
        return str(error.code) == "NAS_UNAVAILABLE" or isinstance(error.__cause__, OSError)
    if isinstance(error, DBAPIError):
        state = getattr(error.orig, "sqlstate", None)
        return error.connection_invalidated or (
            isinstance(state, str)
            and (state.startswith("08") or state in {"40001", "40P01", "53300", "57P01"})
        )
    return False


class PresetModelValidationProcessor:
    """One existing-style metadata command at a time, with recoverable Artifact commit."""

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self._retry_after = 0.0

    def process_once(self) -> str | None:
        if self.engine.dialect.name != "postgresql":
            raise ControlPlaneError(
                "CONTROL_VALIDATION_BACKEND_UNSUPPORTED", "validation requires PostgreSQL"
            )
        if time.monotonic() < self._retry_after:
            return None
        with self.engine.connect() as lock:
            acquired = lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY})
            lock.commit()
            if not acquired:
                return None
            try:
                with transaction(self.sessions) as session:
                    command = session.scalar(
                        select(ExecutionPresetValidationRecord)
                        .where(ExecutionPresetValidationRecord.state.in_(("PENDING", "PROCESSING")))
                        .order_by(
                            ExecutionPresetValidationRecord.requested_at,
                            ExecutionPresetValidationRecord.validation_id,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if command is None:
                        return None
                    validation_id = command.validation_id
                    command.state = "PROCESSING"
                try:
                    self._process(validation_id)
                except (
                    ControlPlaneError,
                    JsonSchemaValidationError,
                    ValueError,
                    OSError,
                    SQLAlchemyError,
                    PlatformError,
                ) as exc:
                    code = (
                        str(exc.code)
                        if isinstance(exc, (ControlPlaneError, PlatformError))
                        else "CONTROL_VALIDATION_EXECUTION_FAILED"
                    )
                    with transaction(self.sessions) as session:
                        command = session.get(
                            ExecutionPresetValidationRecord, validation_id, with_for_update=True
                        )
                        job = session.get(JobRecord, validation_id, with_for_update=True)
                        if command is not None and command.state == "PROCESSING":
                            if (
                                job is not None
                                and job.status == "COMMITTING"
                                and _transient_commit_failure(exc)
                            ):
                                # Bytes may be committed. Retain the same identity/checkpoint;
                                # never fail or replace a delivery after uncertain commit.
                                job.error_code = code
                                job.error_message = "preset acceptance commit requires recovery"
                                self._retry_after = time.monotonic() + 30.0
                                return None
                            command.state = "FAILED"
                            command.error_code = code
                            command.completed_at = datetime.now(UTC)
                            if job is not None and job.status not in {
                                "SUCCEEDED",
                                "FAILED",
                                "CANCELLED",
                            }:
                                job.error_code = code
                                job.error_message = "non-live preset acceptance failed"
                                transition_job(
                                    session,
                                    validation_id,
                                    JobState.FAILED,
                                    "PRESET_MODEL_VALIDATION_FAILED",
                                    data={"error_code": code},
                                )
                    return validation_id
                return validation_id
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
                lock.commit()

    def _process(self, validation_id: str) -> None:
        source_commit = self.settings.runtime_source_commit
        if source_commit is None or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ControlPlaneError(
                "CONTROL_VALIDATION_EVALUATOR_UNAVAILABLE",
                "installed evaluator identity is required",
            )
        with transaction(self.sessions) as session:
            command = session.get(
                ExecutionPresetValidationRecord, validation_id, with_for_update=True
            )
            if command is None or command.state != "PROCESSING":
                raise ControlPlaneError(
                    "CONTROL_VALIDATION_STATE_MISMATCH", "validation claim differs"
                )
            request = validated_request(command)
            try:
                ensure_protocol_version(
                    session, PROTOCOL, CONTROL_SCHEMA_RESOURCES[REQUEST_SCHEMA].sha256
                )
            except RuntimeError as exc:
                raise ControlPlaneError(
                    "CONTROL_VALIDATION_PROTOCOL_MISMATCH", "registered protocol hash differs"
                ) from exc
            job = session.get(JobRecord, validation_id)
            if job is None:
                job, _created = submit_structured_job(
                    session,
                    job_id=validation_id,
                    protocol_version=PROTOCOL,
                    idempotency_key=command.idempotency_key,
                    task_type=TASK_TYPE,
                    request=command.canonical_request,
                    logical_artifact_id=new_logical_artifact_id(),
                    revision_id=new_revision_id(),
                )
            request = validated_job_request(job, command)
            draft, base = pinned_validation_revisions(
                session,
                draft_revision_id=request.preset_revision_id,
                base_revision_id=request.base_revision_id,
            )
            if job.status in {state.value for state in _ADVANCING}:
                while job.status != "RUNNING":
                    target = _ADVANCING[_ADVANCING.index(JobState(job.status)) + 1]
                    transition_job(
                        session, validation_id, target, "PRESET_MODEL_VALIDATION_ADVANCED"
                    )
                case_keys = validate_model_selection(
                    session,
                    validated_preset(base),
                    validated_preset(draft),
                    observed_at=datetime.now(UTC),
                )
                completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                report: dict[str, Any] = {
                    "schema_version": "execution-preset-evaluation-report/1.0",
                    "evaluated_preset_revision_id": request.preset_revision_id,
                    "evaluated_policy_sha256": request.preset_policy_sha256,
                    "scope": "NON_LIVE",
                    "outcome": "PASS",
                    "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
                    "cases_total": len(case_keys),
                    "cases_passed": len(case_keys),
                    "quality_score_permille": None,
                    "completed_at": completed_at,
                    "report_sha256": "sha256:" + "0" * 64,
                }
                report["report_sha256"] = compute_control_document_hash(report, "report_sha256")
                cases = PresetModelAcceptanceCases(
                    validation_id=validation_id,
                    request_sha256=job.request_hash,
                    preset_revision_id=request.preset_revision_id,
                    preset_content_sha256=request.preset_content_sha256,
                    preset_policy_sha256=request.preset_policy_sha256,
                    base_revision_id=request.base_revision_id,
                    base_content_sha256=request.base_content_sha256,
                    evaluator_source_commit=source_commit,
                    case_keys=case_keys,
                    completed_at=datetime.fromisoformat(completed_at),
                    cases_sha256="sha256:" + "0" * 64,
                ).model_dump(mode="json")
                cases["cases_sha256"] = compute_control_document_hash(cases, "cases_sha256")
                validated_acceptance_checkpoint(
                    job=job,
                    request=request,
                    draft=draft,
                    base=base,
                    report_document=report,
                    cases_document=cases,
                    evaluator_source_commit=source_commit,
                )
                transition_job(
                    session,
                    validation_id,
                    JobState.VALIDATING_RESULT,
                    _CHECKPOINT_EVENT,
                    data={"report": report, "cases": cases},
                )
            elif job.status in {"VALIDATING_RESULT", "COMMITTING"}:
                event = session.scalar(
                    select(JobEventRecord).where(
                        JobEventRecord.job_id == validation_id,
                        JobEventRecord.event == _CHECKPOINT_EVENT,
                    )
                )
                if event is None:
                    raise ControlPlaneError(
                        "CONTROL_VALIDATION_CHECKPOINT_MISSING", "validation checkpoint is missing"
                    )
                checkpoint_report, checkpoint_cases = (
                    event.data.get("report"),
                    event.data.get("cases"),
                )
                if not isinstance(checkpoint_report, dict) or not isinstance(
                    checkpoint_cases, dict
                ):
                    raise ControlPlaneError(
                        "CONTROL_VALIDATION_CHECKPOINT_INVALID", "checkpoint is incomplete"
                    )
                report, cases = checkpoint_report, checkpoint_cases
                validated_acceptance_checkpoint(
                    job=job,
                    request=request,
                    draft=draft,
                    base=base,
                    report_document=report,
                    cases_document=cases,
                    evaluator_source_commit=source_commit,
                )
            else:
                raise ControlPlaneError("CONTROL_VALIDATION_STATE_MISMATCH", "job state differs")
            artifact_id, revision_id = job.logical_artifact_id, job.revision_id
            if job.status == "VALIDATING_RESULT":
                transition_job(
                    session,
                    validation_id,
                    JobState.COMMITTING,
                    "PRESET_MODEL_ACCEPTANCE_COMMITTING",
                )
        # This is the only materialization/commit owner; the API inserts metadata only.
        with tempfile.TemporaryDirectory(
            prefix="preset-acceptance-", dir=self.settings.staging_root
        ) as temporary:
            root = Path(temporary)
            report_file, cases_file = (
                root / "preset-evaluation.json",
                root / "acceptance-cases.json",
            )
            report_file.write_bytes(canonical_json_bytes(report) + b"\n")
            cases_file.write_bytes(canonical_json_bytes(cases) + b"\n")
            staged = stage_file_set_artifact(
                files={report_file.name: report_file, cases_file.name: cases_file},
                primary_file=report_file.name,
                job_id=validation_id,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
                artifact_type=TASK_TYPE,
                staging=root / "artifact",
                created_at=request.requested_at,
                manifest_version="control-file-set/1.0",
                file_metadata={
                    report_file.name: {
                        "schema_ref": EVALUATION_SCHEMA_REF,
                        "media_type": "application/json",
                    },
                    cases_file.name: {
                        "schema_ref": CASES_SCHEMA_REF,
                        "media_type": "application/json",
                    },
                },
            )
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            with transaction(self.sessions) as session:
                command = session.get(
                    ExecutionPresetValidationRecord, validation_id, with_for_update=True
                )
                job = session.get(JobRecord, validation_id, with_for_update=True)
                if (
                    command is None
                    or command.state != "PROCESSING"
                    or job is None
                    or job.status != "COMMITTING"
                ):
                    raise ControlPlaneError(
                        "CONTROL_VALIDATION_STATE_MISMATCH", "commit state differs"
                    )
                request = validated_job_request(job, command)
                draft, base = pinned_validation_revisions(
                    session,
                    draft_revision_id=request.preset_revision_id,
                    base_revision_id=request.base_revision_id,
                )
                validated_acceptance_checkpoint(
                    job=job,
                    request=request,
                    draft=draft,
                    base=base,
                    report_document=report,
                    cases_document=cases,
                    evaluator_source_commit=source_commit,
                )
                existing = session.get(ArtifactRevisionRecord, revision_id)
                if existing is None:
                    create_artifact_records(
                        session,
                        job=job,
                        content_hash=staged.primary_hash,
                        manifest_hash=staged.manifest_hash,
                        content_bytes=staged.primary_bytes,
                        nas_path=str(final),
                        manifest=staged.manifest,
                        result=report,
                    )
                elif (
                    existing.job_id != validation_id
                    or existing.logical_artifact_id != artifact_id
                    or existing.content_hash != staged.primary_hash
                    or existing.manifest_hash != staged.manifest_hash
                    or not existing.approved
                ):
                    raise ControlPlaneError(
                        "CONTROL_VALIDATION_EVIDENCE_MISMATCH",
                        "committed evidence identity differs",
                    )
                job.error_code, job.error_message = None, None
                transition_job(
                    session, validation_id, JobState.SUCCEEDED, "PRESET_MODEL_VALIDATION_SUCCEEDED"
                )
                record_execution_preset_evaluation(
                    session,
                    document=report,
                    report_artifact=ControlArtifactPointer(
                        artifact_id=artifact_id,
                        artifact_revision_id=revision_id,
                        sha256=staged.primary_hash,
                        schema_ref=EVALUATION_SCHEMA_REF,
                        media_type="application/json",
                        logical_name=report_file.name,
                    ),
                    created_by=request.requested_by,
                )
                command.state = "SUCCEEDED"
                command.completed_at = job.completed_at
