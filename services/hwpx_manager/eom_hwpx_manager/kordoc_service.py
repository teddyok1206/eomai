"""Orchestrated Kordoc HWPX generation from a pinned Markdown artifact revision."""

from __future__ import annotations

import logging
import stat
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_contracts import (
    KordocBuildResult,
    KordocExpectedStructure,
    KordocRenderOptions,
    KordocRenderRequest,
    KordocSourcePointer,
    validate_contract,
)
from eom_identifiers import (
    new_hwpx_build_id,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_file,
)
from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_protocol import ErrorCode
from sqlalchemy import Engine, select

from eom_hwpx_manager.adapter import BuilderRun, HwpxBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.logging import log_hwpx_event
from eom_hwpx_manager.protocol import HWPX_KORDOC_PROTOCOL_VERSION, kordoc_schema_bundle_hash
from eom_hwpx_manager.settings import HwpxSettings

KORDOC_RENDERER_VERSION = "0.1.0"
LOGGER = logging.getLogger("eom.hwpx_manager.kordoc")


@dataclass(frozen=True)
class KordocBuildReceipt:
    build_id: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    output_sha256: str
    status: str


class KordocHwpxService:
    def __init__(
        self,
        engine: Engine,
        settings: HwpxSettings | None = None,
        adapter: HwpxBuilderAdapter | None = None,
    ) -> None:
        self.settings = settings or HwpxSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.adapter = adapter or HwpxBuilderAdapter(self.settings)

    def build(
        self,
        source_path: Path,
        source: KordocSourcePointer,
        expected_structure: KordocExpectedStructure,
        *,
        idempotency_key: str,
        options: KordocRenderOptions | None = None,
    ) -> KordocBuildReceipt:
        actual_options = options or KordocRenderOptions()
        self._resolve_source(source_path, source)
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        build_id = new_hwpx_build_id()
        request_identity = {
            "renderer_profile": "kordoc-markdown-v1",
            "source": source.model_dump(mode="json"),
            "options": actual_options.model_dump(mode="json"),
            "expected_structure": expected_structure.model_dump(mode="json"),
        }
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session, HWPX_KORDOC_PROTOCOL_VERSION, kordoc_schema_bundle_hash()
            )
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_KORDOC_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-kordoc-build:{idempotency_key}",
                task_type="hwpx-kordoc-build",
                request=request_identity,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
            existing_job_id = job.job_id if not created else None
        if existing_job_id is not None:
            return self._completed_receipt(existing_job_id)

        request = KordocRenderRequest(
            build_id=build_id,
            source=source,
            options=actual_options,
            expected_structure=expected_structure,
        )
        request_raw = request.model_dump(mode="json")
        validate_contract("kordoc-render-request", request_raw)
        try:
            workspace = self.adapter.create_workspace(build_id)
            self.adapter.stage_file(workspace, source.file, source_path)
            self.adapter.write_json(workspace, "request.json", request_raw)
            log_root = self.settings.staging_root / job_id
            for state, event in (
                (JobState.VALIDATED, "HWPX_KORDOC_INPUT_VALIDATED"),
                (JobState.QUEUED, "HWPX_KORDOC_BUILD_QUEUED"),
                (JobState.CLAIMED, "HWPX_KORDOC_BUILDER_CLAIMED"),
                (JobState.RUNNING, "HWPX_KORDOC_RENDER_STARTED"),
            ):
                self._transition(job_id, state, event)
            run = self.adapter.run(
                workspace,
                "render-kordoc",
                ["--request", "request.json", "--result", "result.json"],
                log_root,
            )
            self._record_run(job_id, run)
            if run.exit_code != 0:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "Kordoc HWPX builder failed"
                )
            self._transition(job_id, JobState.VALIDATING_RESULT, "HWPX_KORDOC_RESULT_RECEIVED")
            result_raw = self.adapter.load_json(workspace / "result.json", workspace)
            validate_contract("kordoc-build-result", result_raw)
            result = KordocBuildResult.model_validate(result_raw)
            output = workspace / "output/kordoc_document.hwpx"
            try:
                output_stat = output.lstat()
            except OSError as exc:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "Kordoc output is missing",
                ) from exc
            if (
                not stat.S_ISREG(output_stat.st_mode)
                or output.is_symlink()
                or not output.resolve().is_relative_to(workspace.resolve())
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "Kordoc output materialization is unsafe",
                )
            structural = self.adapter.load_json(
                workspace / "output/structural-validation.json", workspace
            )
            renderer_report = self.adapter.load_json(
                workspace / "output/kordoc-validation.json", workspace
            )
            if (
                result.status != "PENDING_MANUAL_HANCOM_VALIDATION"
                or result.build_id != build_id
                or result.source_artifact_id != source.artifact_id
                or result.source_artifact_revision_id != source.artifact_revision_id
                or result.source_sha256 != source.sha256
                or result.renderer_version != KORDOC_RENDERER_VERSION
                or result.output_sha256 != sha256_file(output)
                or result.native_equation_count != expected_structure.display_equation_count
                or result.native_table_count != expected_structure.table_count
                or structural.get("status") != "PASS"
                or renderer_report.get("validation_ok") is not True
                or renderer_report.get("parse_success") is not True
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "Kordoc result did not pass manager validation",
                )
            staged = stage_file_set_artifact(
                files={
                    "kordoc_document.hwpx": output,
                    "package-manifest.json": workspace / "output/package-manifest.json",
                    "structural-validation.json": workspace / "output/structural-validation.json",
                    "kordoc-validation.json": workspace / "output/kordoc-validation.json",
                    "result.json": workspace / "result.json",
                },
                primary_file="kordoc_document.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
                artifact_type="hwpx-kordoc-build",
                staging=log_root / "artifact",
            )
            self._transition(job_id, JobState.COMMITTING, "HWPX_KORDOC_COMMIT_STARTED")
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            with transaction(self.sessions) as session:
                job = session.execute(
                    select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
                ).scalar_one()
                create_artifact_records(
                    session,
                    job=job,
                    content_hash=staged.primary_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.primary_bytes,
                    nas_path=str(final),
                    manifest=staged.manifest,
                    result=result.model_dump(mode="json"),
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "HWPX_KORDOC_ARTIFACT_COMMITTED",
                    data={
                        "build_id": build_id,
                        "logical_artifact_id": artifact_id,
                        "revision_id": artifact_revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            log_hwpx_event(
                LOGGER,
                logging.INFO,
                "HWPX_KORDOC_BUILD_COMMITTED",
                build_id=build_id,
                source_artifact_id=source.artifact_id,
                source_artifact_revision_id=source.artifact_revision_id,
                output_sha256=staged.primary_hash,
                artifact_id=artifact_id,
                artifact_revision_id=artifact_revision_id,
            )
            return KordocBuildReceipt(
                build_id=build_id,
                job_id=job_id,
                artifact_id=artifact_id,
                artifact_revision_id=artifact_revision_id,
                output_sha256=staged.primary_hash,
                status=JobState.SUCCEEDED.value,
            )
        except Exception as exc:
            self._fail_job(job_id, exc)
            raise

    def _resolve_source(self, source_path: Path, source: KordocSourcePointer) -> None:
        with self.sessions() as session:
            artifact = session.get(ArtifactRecord, source.artifact_id)
            revision = session.get(ArtifactRevisionRecord, source.artifact_revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != source.artifact_id
                or revision.content_hash != source.sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "Markdown artifact pointer is missing, stale, or unapproved",
                )
            primary_file = revision.manifest.get("primary_file")
            if not isinstance(primary_file, str):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "Markdown artifact has no typed primary file",
                )
            relative = Path(primary_file)
            revision_root = Path(revision.nas_path).resolve(strict=False)
            if relative.is_absolute() or ".." in relative.parts or "\\" in primary_file:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "Markdown artifact primary file is unsafe",
                )
            canonical_path = (revision_root / relative).resolve(strict=False)
            if not canonical_path.is_relative_to(revision_root):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "Markdown artifact primary file escaped its revision",
                )
        try:
            source_stat = source_path.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "Markdown artifact file is missing",
            ) from exc
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or source_path.resolve() != canonical_path
            or source_path.suffix.casefold() != ".md"
            or sha256_file(source_path) != source.sha256
            or source_stat.st_size > 1024 * 1024
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "Markdown artifact materialization is unsafe or hash-mismatched",
            )

    def _completed_receipt(self, job_id: str) -> KordocBuildReceipt:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            if job is None or job.status != JobState.SUCCEEDED.value:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "existing Kordoc build is not a completed immutable result",
                )
            revision = session.get(ArtifactRevisionRecord, job.revision_id)
            if revision is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "completed Kordoc job has no artifact revision",
                )
            result = KordocBuildResult.model_validate(revision.result)
            return KordocBuildReceipt(
                build_id=result.build_id,
                job_id=job.job_id,
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                output_sha256=revision.content_hash,
                status=job.status,
            )

    def _transition(self, job_id: str, target: JobState, event: str) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event)

    def _record_run(self, job_id: str, run: BuilderRun) -> None:
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise RuntimeError("Kordoc platform job disappeared")
            job.worker_exit_code = run.exit_code
            job.worker_stdout_path = str(run.stdout_path)
            job.worker_stderr_path = str(run.stderr_path)

    def _fail_job(self, job_id: str, error: Exception) -> None:
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, job_id)
            if job is None or JobState(job.status) in {
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
            }:
                return
            code = (
                error.code.value
                if isinstance(error, HwpxManagerError)
                else ErrorCode.WORKER_EXEC_FAILED.value
            )
            job.error_code = code
            job.error_message = "Kordoc HWPX operation failed"
            transition_job(
                session,
                job_id,
                JobState.FAILED,
                "HWPX_KORDOC_OPERATION_FAILED",
                data={"error_code": code},
            )
