"""Application adapter for the immutable content-team HwpQuestionEditor profile."""

from __future__ import annotations

import json
import logging
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts import AssessmentItemContentV2
from eom_catalog_contracts import validate_contract as validate_catalog_contract
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamBuildResult,
    ContentTeamHandoffSnapshot,
    ContentTeamItemSource,
    ContentTeamRenderRequest,
    serialize_content_team_markdown,
)
from eom_hwpx_contracts import validate_contract as validate_hwpx_contract
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id, sha256_file
from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, select

from eom_hwpx_manager.adapter import BuilderRun
from eom_hwpx_manager.application_adapter import FixedContentTeamBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.protocol import (
    HWPX_CONTENT_TEAM_PROTOCOL_VERSION,
    content_team_schema_bundle_hash,
)
from eom_hwpx_manager.settings import HwpxSettings

CONTENT_TEAM_RENDERER = "content-team"
CONTENT_TEAM_RENDERER_VERSION = "1.0.0"
ITEM_SCHEMA_REF = "eom.assessment.item-content/2.0"
ITEM_JSON_MEMBER = "assessment-item-content.json"
ITEM_MARKDOWN_MEMBER = "content-team-item.md"
ITEM_MARKDOWN_SCHEMA_REF = "eom://schemas/hwpx/content-team-editorial-markdown/1.0"
ITEM_MARKDOWN_MEDIA_TYPE = "text/markdown"
HANDOFF_MEMBER = "handoff-source.zip"
HANDOFF_SCHEMA_REF = "eom://schemas/hwpx/content-team-handoff-archive/1.0"
HANDOFF_MEDIA_TYPE = "application/zip"
MAX_ITEM_JSON_BYTES = 2 * 1024 * 1024
MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_HANDOFF_BYTES = 64 * 1024 * 1024
LOGGER = logging.getLogger("eom.hwpx_manager.content_team")
ARTIFACT_ID = re.compile(r"\Aartifact_[0-9a-f]{32}\Z", re.ASCII)
REVISION_ID = re.compile(r"\Arev_[0-9a-f]{32}\Z", re.ASCII)
SHA256 = re.compile(r"\Asha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True)
class ContentTeamBuildReceipt:
    build_id: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    output_sha256: str
    native_equation_count: int
    native_table_count: int


class ContentTeamHwpxService:
    """Resolve pinned members, run the isolated renderer, then commit validated HWPX."""

    def __init__(self, engine: Engine, settings: HwpxSettings | None = None) -> None:
        self.settings = settings or HwpxSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.adapter = FixedContentTeamBuilderAdapter(self.settings)

    def snapshot(self) -> ContentTeamHandoffSnapshot:
        snapshot = ContentTeamHandoffSnapshot.model_validate(
            {
                "artifact_id": self.settings.content_team_handoff_artifact_id,
                "artifact_revision_id": self.settings.content_team_handoff_artifact_revision_id,
                "archive_sha256": self.settings.content_team_handoff_archive_sha256,
                "members": [
                    {"purpose": purpose, "sha256": sha256, "size": size}
                    for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
                ],
            }
        )
        if (
            ARTIFACT_ID.fullmatch(snapshot.artifact_id) is None
            or REVISION_ID.fullmatch(snapshot.artifact_revision_id) is None
            or SHA256.fullmatch(snapshot.archive_sha256) is None
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "content-team handoff release pin is incomplete",
            )
        return snapshot

    def build(
        self,
        source_path: Path,
        source: ContentTeamItemSource,
        *,
        item_revision_id: str,
        idempotency_key: str,
        build_id: str,
        handoff_snapshot: ContentTeamHandoffSnapshot,
    ) -> ContentTeamBuildReceipt:
        if handoff_snapshot != self.snapshot():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "content-team handoff release pin changed after request creation",
            )
        content = self._load_content(source_path, source)
        markdown_path = self._resolve_member(
            source.artifact_id,
            source.artifact_revision_id,
            ITEM_MARKDOWN_MEMBER,
            source.markdown_sha256,
            media_type=ITEM_MARKDOWN_MEDIA_TYPE,
            schema_ref=ITEM_MARKDOWN_SCHEMA_REF,
            max_bytes=MAX_MARKDOWN_BYTES,
        )
        markdown = serialize_content_team_markdown(content)
        if markdown_path.read_bytes() != markdown:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "content-team Markdown member differs from canonical item content",
            )
        handoff_path = self._resolve_member(
            handoff_snapshot.artifact_id,
            handoff_snapshot.artifact_revision_id,
            HANDOFF_MEMBER,
            handoff_snapshot.archive_sha256,
            media_type=HANDOFF_MEDIA_TYPE,
            schema_ref=HANDOFF_SCHEMA_REF,
            max_bytes=MAX_HANDOFF_BYTES,
        )
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        request = ContentTeamRenderRequest(
            build_id=build_id,
            item_revision_id=item_revision_id,
            source=source,
            handoff=handoff_snapshot,
        )
        request_raw = request.model_dump(mode="json")
        validate_hwpx_contract("content-team-render-request", request_raw)
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session,
                HWPX_CONTENT_TEAM_PROTOCOL_VERSION,
                content_team_schema_bundle_hash(),
            )
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_CONTENT_TEAM_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-content-team:{idempotency_key}",
                task_type="hwpx-content-team-build",
                request=request_raw,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
            existing_job_id = job.job_id if not created else None
        if existing_job_id is not None:
            return self._completed_receipt(existing_job_id, expected_build_id=build_id)

        try:
            workspace = self.adapter.create_workspace(build_id)
            self.adapter.stage_file(workspace, source.json_file, source_path)
            self.adapter.stage_file(workspace, source.markdown_file, markdown_path)
            self.adapter.stage_file(workspace, handoff_snapshot.archive_file, handoff_path)
            self.adapter.write_json(workspace, "request.json", request_raw)
            log_root = self.settings.staging_root / job_id
            for state, event in (
                (JobState.VALIDATED, "HWPX_CONTENT_TEAM_INPUT_VALIDATED"),
                (JobState.QUEUED, "HWPX_CONTENT_TEAM_BUILD_QUEUED"),
                (JobState.CLAIMED, "HWPX_CONTENT_TEAM_BUILDER_CLAIMED"),
                (JobState.RUNNING, "HWPX_CONTENT_TEAM_RENDER_STARTED"),
            ):
                self._transition(job_id, state, event)
            run = self.adapter.run(
                workspace,
                "render-content-team",
                ["--request", "request.json", "--result", "result.json"],
                log_root,
            )
            self._record_run(job_id, run)
            if run.exit_code != 0:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                    "content-team HWPX builder failed",
                )
            self._transition(
                job_id,
                JobState.VALIDATING_RESULT,
                "HWPX_CONTENT_TEAM_RESULT_RECEIVED",
            )
            result_raw = self.adapter.load_json(workspace / "result.json", workspace)
            validate_hwpx_contract("content-team-build-result", result_raw)
            result = ContentTeamBuildResult.model_validate(result_raw)
            output = workspace / "output/content-team-item.hwpx"
            self._verify_output(output, workspace)
            package_manifest = self.adapter.load_json(
                workspace / "output/package-manifest.json",
                workspace,
            )
            renderer_report = self.adapter.load_json(
                workspace / "output/content-team-validation.json",
                workspace,
            )
            if (
                result.status != "SUCCEEDED"
                or result.build_id != build_id
                or result.item_revision_id != item_revision_id
                or result.source_artifact_id != source.artifact_id
                or result.source_artifact_revision_id != source.artifact_revision_id
                or result.source_json_sha256 != source.json_sha256
                or result.source_markdown_sha256 != source.markdown_sha256
                or result.handoff_archive_sha256 != handoff_snapshot.archive_sha256
                or result.output_sha256 != sha256_file(output)
                or package_manifest.get("package_sha256") != result.output_sha256
                or renderer_report.get("status") != "PASS"
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "content-team renderer result differs from its pinned request",
                )
            staged = stage_file_set_artifact(
                files={
                    "content-team-item.hwpx": output,
                    "package-manifest.json": workspace / "output/package-manifest.json",
                    "content-team-validation.json": (
                        workspace / "output/content-team-validation.json"
                    ),
                    "renderer-result.json": workspace / "result.json",
                    "renderer-request.json": workspace / "request.json",
                },
                primary_file="content-team-item.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
                artifact_type="hwpx-content-team-build",
                staging=log_root / "artifact",
                manifest_version="content-team-hwpx-artifact/1.0",
            )
            self._transition(job_id, JobState.COMMITTING, "HWPX_CONTENT_TEAM_COMMIT_STARTED")
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            stored_result = {
                "schema_version": "1.0",
                "builder_result": result.model_dump(mode="json"),
                "native_equation_count": result.equation_count,
                "native_table_count": result.table_count,
                "handoff": handoff_snapshot.model_dump(mode="json"),
            }
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
                    result=stored_result,
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "HWPX_CONTENT_TEAM_ARTIFACT_COMMITTED",
                    data={
                        "build_id": build_id,
                        "logical_artifact_id": artifact_id,
                        "revision_id": artifact_revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            LOGGER.info(
                "HWPX_CONTENT_TEAM_BUILD_COMMITTED build_id=%s artifact_id=%s",
                build_id,
                artifact_id,
            )
            return ContentTeamBuildReceipt(
                build_id=build_id,
                job_id=job_id,
                artifact_id=artifact_id,
                artifact_revision_id=artifact_revision_id,
                output_sha256=staged.primary_hash,
                native_equation_count=result.equation_count,
                native_table_count=result.table_count,
            )
        except Exception as exc:
            self._fail_job(job_id, exc)
            raise

    def _load_content(
        self,
        source_path: Path,
        source: ContentTeamItemSource,
    ) -> AssessmentItemContentV2:
        canonical = self._resolve_member(
            source.artifact_id,
            source.artifact_revision_id,
            ITEM_JSON_MEMBER,
            source.json_sha256,
            media_type="application/json",
            schema_ref=ITEM_SCHEMA_REF,
            max_bytes=MAX_ITEM_JSON_BYTES,
        )
        try:
            metadata = source_path.lstat()
            if (
                source_path != canonical
                or not stat.S_ISREG(metadata.st_mode)
                or source_path.is_symlink()
                or metadata.st_size > MAX_ITEM_JSON_BYTES
                or sha256_file(source_path) != source.json_sha256
            ):
                raise ValueError("unsafe item content")
            value: object = json.loads(source_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("item content is not an object")
            validate_catalog_contract("assessment-item-content-v2", value)
            return AssessmentItemContentV2.model_validate(value)
        except Exception as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "canonical content-team item artifact is invalid",
            ) from exc

    def _resolve_member(
        self,
        artifact_id: str,
        revision_id: str,
        member_name: str,
        expected_sha256: str,
        *,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> Path:
        relative = Path(member_name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in member_name:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact member pointer is unsafe",
            )
        with self.sessions() as session:
            artifact = session.get(ArtifactRecord, artifact_id)
            revision = session.get(ArtifactRevisionRecord, revision_id)
            files = revision.manifest.get("files") if revision is not None else None
            entries = (
                [
                    entry
                    for entry in files
                    if isinstance(entry, dict) and entry.get("file_name") == member_name
                ]
                if isinstance(files, list)
                else []
            )
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != artifact_id
                or len(entries) != 1
                or entries[0].get("sha256") != expected_sha256
                or entries[0].get("media_type") != media_type
                or entries[0].get("schema_ref") != schema_ref
                or not isinstance(entries[0].get("bytes"), int)
                or not 0 < entries[0]["bytes"] <= max_bytes
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "artifact member pointer is stale or invalid",
                )
            root = Path(revision.nas_path)
            expected_size = entries[0]["bytes"]
        candidate = root / relative
        current = root
        try:
            root_metadata = root.lstat()
            resolved_root = root.resolve(strict=True)
            if not stat.S_ISDIR(root_metadata.st_mode) or root.is_symlink():
                raise ValueError("artifact root is unsafe")
            for part in relative.parts:
                current = current / part
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise ValueError("artifact member path contains a symlink")
            metadata = candidate.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or candidate.resolve(strict=True).parent != resolved_root
                or metadata.st_size != expected_size
                or sha256_file(candidate) != expected_sha256
            ):
                raise ValueError("artifact member materialization differs")
        except (OSError, ValueError) as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact member materialization is unsafe",
            ) from exc
        return candidate

    @staticmethod
    def _verify_output(output: Path, workspace: Path) -> None:
        try:
            metadata = output.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "content-team HWPX output is missing",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or output.is_symlink()
            or not output.resolve(strict=True).is_relative_to(workspace.resolve(strict=True))
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "content-team HWPX output materialization is unsafe",
            )

    def _completed_receipt(
        self,
        job_id: str,
        *,
        expected_build_id: str,
    ) -> ContentTeamBuildReceipt:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            revision = (
                session.get(ArtifactRevisionRecord, job.revision_id) if job is not None else None
            )
            if job is None or job.status != JobState.SUCCEEDED.value or revision is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "existing content-team build is not a completed immutable result",
                )
            stored = revision.result
            raw = stored.get("builder_result")
            if not isinstance(raw, dict):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "completed content-team build has no typed result",
                )
            parsed = ContentTeamBuildResult.model_validate(raw)
            if parsed.build_id != expected_build_id:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "completed content-team build belongs to another request",
                )
            return ContentTeamBuildReceipt(
                build_id=parsed.build_id,
                job_id=job.job_id,
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                output_sha256=revision.content_hash,
                native_equation_count=int(stored["native_equation_count"]),
                native_table_count=int(stored["native_table_count"]),
            )

    def _transition(self, job_id: str, target: JobState, event: str) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event)

    def _record_run(self, job_id: str, run: BuilderRun) -> None:
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise RuntimeError("content-team platform job disappeared")
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
                else HwpxManagerErrorCode.HWPX_BUILDER_FAILED.value
            )
            job.error_code = code
            job.error_message = "content-team HWPX build failed"
            transition_job(
                session,
                job_id,
                JobState.FAILED,
                "HWPX_CONTENT_TEAM_BUILD_FAILED",
                data={"error_code": code},
            )
