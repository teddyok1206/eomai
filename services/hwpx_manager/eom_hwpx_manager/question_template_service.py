"""Approved question-template delivery adapter for canonical Item content."""

from __future__ import annotations

import json
import logging
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    AssessmentItemContent,
)
from eom_catalog_contracts import (
    validate_contract as validate_catalog_contract,
)
from eom_hwpx_contracts import (
    BuildResultStatus,
    HwpxBuildResult,
)
from eom_hwpx_contracts import (
    validate_contract as validate_hwpx_contract,
)
from eom_identifiers import (
    content_sha256,
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
from sqlalchemy import Engine, select

from eom_hwpx_manager.adapter import BuilderRun
from eom_hwpx_manager.application_adapter import FixedQuestionTemplateBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.protocol import HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash
from eom_hwpx_manager.question_template import QUESTION_TEMPLATE_PROFILE, project_question_template
from eom_hwpx_manager.settings import HwpxSettings

QUESTION_TEMPLATE_RENDERER = "eom-template"
QUESTION_TEMPLATE_RENDERER_VERSION = "1.0.0"
BUILDER_RENDERER_VERSION = "0.1.0"
EXPECTED_NATIVE_EQUATIONS = 1
EXPECTED_CONTENT_TABLES = 1
EXPECTED_TOTAL_NATIVE_TABLES = 4
MAX_ITEM_CONTENT_BYTES = 2 * 1024 * 1024
LOGGER = logging.getLogger("eom.hwpx_manager.question_template")
TEMPLATE_ID = re.compile(r"\Ahwpxtpl_[0-9a-f]{32}\Z", re.ASCII)
TEMPLATE_REVISION_ID = re.compile(r"\Ahwpxrev_[0-9a-f]{32}\Z", re.ASCII)
ARTIFACT_ID = re.compile(r"\Aartifact_[0-9a-f]{32}\Z", re.ASCII)
ARTIFACT_REVISION_ID = re.compile(r"\Arev_[0-9a-f]{32}\Z", re.ASCII)
SHA256 = re.compile(r"\Asha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True)
class ItemContentSourcePointer:
    artifact_id: str
    artifact_revision_id: str
    sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_revision_id": self.artifact_revision_id,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class QuestionTemplateSnapshot:
    profile: str
    template_id: str
    template_revision_id: str
    template_artifact_id: str
    template_artifact_revision_id: str
    template_source_sha256: str
    binding_manifest_sha256: str

    def request_identity(self) -> dict[str, str]:
        return {
            "document_profile": self.profile,
            "template_id": self.template_id,
            "template_revision_id": self.template_revision_id,
            "template_artifact_id": self.template_artifact_id,
            "template_artifact_revision_id": self.template_artifact_revision_id,
            "template_source_sha256": self.template_source_sha256,
            "binding_manifest_sha256": self.binding_manifest_sha256,
        }

    @classmethod
    def from_request_options(cls, options: dict[str, Any]) -> QuestionTemplateSnapshot:
        """Restore the exact release snapshot persisted with an application request."""

        try:
            return cls(
                profile=str(options["document_profile"]),
                template_id=str(options["template_id"]),
                template_revision_id=str(options["template_revision_id"]),
                template_artifact_id=str(options["template_artifact_id"]),
                template_artifact_revision_id=str(options["template_artifact_revision_id"]),
                template_source_sha256=str(options["template_source_sha256"]),
                binding_manifest_sha256=str(options["binding_manifest_sha256"]),
            )
        except KeyError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "stored question-template release snapshot is incomplete",
            ) from exc


@dataclass(frozen=True)
class QuestionTemplateBuildReceipt:
    build_id: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    output_sha256: str
    native_equation_count: int
    native_table_count: int
    total_native_table_count: int


class QuestionTemplateHwpxService:
    """Project one pinned canonical item into one pinned approved question template."""

    def __init__(self, engine: Engine, settings: HwpxSettings | None = None) -> None:
        self.settings = settings or HwpxSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.adapter = FixedQuestionTemplateBuilderAdapter(self.settings)

    def snapshot(self) -> QuestionTemplateSnapshot:
        """Return the deployed release pin without resolving an implicit latest revision."""

        snapshot = QuestionTemplateSnapshot(
            profile=QUESTION_TEMPLATE_PROFILE,
            template_id=self.settings.question_template_id,
            template_revision_id=self.settings.question_template_revision_id,
            template_artifact_id=self.settings.question_template_artifact_id,
            template_artifact_revision_id=self.settings.question_template_artifact_revision_id,
            template_source_sha256=self.settings.question_template_source_sha256,
            binding_manifest_sha256=self.settings.question_template_binding_manifest_sha256,
        )
        if (
            TEMPLATE_ID.fullmatch(snapshot.template_id) is None
            or TEMPLATE_REVISION_ID.fullmatch(snapshot.template_revision_id) is None
            or ARTIFACT_ID.fullmatch(snapshot.template_artifact_id) is None
            or ARTIFACT_REVISION_ID.fullmatch(snapshot.template_artifact_revision_id) is None
            or SHA256.fullmatch(snapshot.template_source_sha256) is None
            or SHA256.fullmatch(snapshot.binding_manifest_sha256) is None
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "question-template release pin is incomplete",
            )
        return snapshot

    def build(
        self,
        source_path: Path,
        source: ItemContentSourcePointer,
        *,
        item_revision_id: str,
        item_number: int,
        idempotency_key: str,
        build_id: str,
        template_snapshot: QuestionTemplateSnapshot,
    ) -> QuestionTemplateBuildReceipt:
        if template_snapshot != self.snapshot():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "question-template release pin changed after request creation",
            )
        content = self._load_content(source_path, source)
        projection = project_question_template(
            content,
            item_revision_id=item_revision_id,
            item_number=item_number,
        )
        image_pointer = projection.image.artifact
        image_path = self._resolve_artifact_primary(
            image_pointer.artifact_id,
            image_pointer.artifact_revision_id,
            image_pointer.sha256,
        )
        template_root = self._resolve_template(template_snapshot)
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        request_identity = {
            "renderer_profile": QUESTION_TEMPLATE_PROFILE,
            "item_revision_id": item_revision_id,
            "item_content": source.as_dict(),
            "image": image_pointer.model_dump(mode="json"),
            "template": template_snapshot.request_identity(),
            "item_number": item_number,
        }
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash())
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-question-template:{idempotency_key}",
                task_type="hwpx-question-template-build",
                request=request_identity,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
            existing_job_id = job.job_id if not created else None
        if existing_job_id is not None:
            return self._completed_receipt(existing_job_id, expected_build_id=build_id)

        document_raw = projection.document.model_dump(mode="json")
        validate_hwpx_contract("item-document", document_raw)
        request = {
            "request_version": "1.0",
            "build_id": build_id,
            "template_id": template_snapshot.template_id,
            "template_revision_id": template_snapshot.template_revision_id,
            "template_sha256": template_snapshot.template_source_sha256,
            "template_file": "template.hwpx",
            "bindings_file": "template-bindings.json",
            "document_file": "input/document.json",
            "image_file": "input/eom-placeholder-image-output.png",
            "output_directory": "output",
        }
        try:
            workspace = self.adapter.create_workspace(build_id)
            self.adapter.stage_file(workspace, "template.hwpx", template_root / "template.hwpx")
            self.adapter.stage_file(
                workspace,
                "template-bindings.json",
                template_root / "template-bindings.json",
            )
            self.adapter.write_json(workspace, "input/document.json", document_raw)
            self.adapter.stage_file(
                workspace,
                "input/eom-placeholder-image-output.png",
                image_path,
            )
            self.adapter.write_json(workspace, "request.json", request)
            log_root = self.settings.staging_root / job_id
            for state, event in (
                (JobState.VALIDATED, "HWPX_TEMPLATE_INPUT_VALIDATED"),
                (JobState.QUEUED, "HWPX_TEMPLATE_BUILD_QUEUED"),
                (JobState.CLAIMED, "HWPX_TEMPLATE_BUILDER_CLAIMED"),
                (JobState.RUNNING, "HWPX_TEMPLATE_RENDER_STARTED"),
            ):
                self._transition(job_id, state, event)
            run = self.adapter.run(
                workspace,
                "render",
                ["--request", "request.json", "--result", "result.json"],
                log_root,
            )
            self._record_run(job_id, run)
            if run.exit_code != 0:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                    "question-template HWPX builder failed",
                )
            self._transition(job_id, JobState.VALIDATING_RESULT, "HWPX_TEMPLATE_RESULT_RECEIVED")
            result_raw = self.adapter.load_json(workspace / "result.json", workspace)
            validate_hwpx_contract("build-result", result_raw)
            result = HwpxBuildResult.model_validate(result_raw)
            output = workspace / "output/placeholder_item_combined.hwpx"
            self._verify_output(output, workspace)
            structural = self.adapter.load_json(
                workspace / "output/structural-validation.json",
                workspace,
            )
            semantic = self.adapter.load_json(
                workspace / "output/semantic-validation.json",
                workspace,
            )
            equation_count, total_table_count = self._metrics(structural)
            if (
                result.status != BuildResultStatus.PENDING_MANUAL_HANCOM_VALIDATION
                or result.build_id != build_id
                or result.template_id != template_snapshot.template_id
                or result.template_revision_id != template_snapshot.template_revision_id
                or result.input_sha256 != content_sha256(document_raw)
                or result.renderer_version != BUILDER_RENDERER_VERSION
                or result.output_sha256 != sha256_file(output)
                or structural.get("status") != "PASS"
                or semantic.get("status") != "PASS"
                or equation_count != EXPECTED_NATIVE_EQUATIONS
                or total_table_count != EXPECTED_TOTAL_NATIVE_TABLES
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "question-template output did not match its pinned validation contract",
                )
            staged = stage_file_set_artifact(
                files={
                    "placeholder_item_combined.hwpx": output,
                    "package-manifest.json": workspace / "output/package-manifest.json",
                    "structural-validation.json": workspace / "output/structural-validation.json",
                    "semantic-validation.json": workspace / "output/semantic-validation.json",
                    "template-bindings.json": workspace / "template-bindings.json",
                    "result.json": workspace / "result.json",
                },
                primary_file="placeholder_item_combined.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
                artifact_type="hwpx-question-template-build",
                staging=log_root / "artifact",
            )
            self._transition(job_id, JobState.COMMITTING, "HWPX_TEMPLATE_COMMIT_STARTED")
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            stored_result = {
                "schema_version": "1.0",
                "builder_result": result.model_dump(mode="json"),
                "native_equation_count": equation_count,
                "native_table_count": EXPECTED_CONTENT_TABLES,
                "total_native_table_count": total_table_count,
                "template": template_snapshot.request_identity(),
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
                    "HWPX_TEMPLATE_ARTIFACT_COMMITTED",
                    data={
                        "build_id": build_id,
                        "logical_artifact_id": artifact_id,
                        "revision_id": artifact_revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            LOGGER.info(
                "HWPX_QUESTION_TEMPLATE_BUILD_COMMITTED build_id=%s artifact_id=%s",
                build_id,
                artifact_id,
            )
            return QuestionTemplateBuildReceipt(
                build_id=build_id,
                job_id=job_id,
                artifact_id=artifact_id,
                artifact_revision_id=artifact_revision_id,
                output_sha256=staged.primary_hash,
                native_equation_count=equation_count,
                native_table_count=EXPECTED_CONTENT_TABLES,
                total_native_table_count=total_table_count,
            )
        except Exception as exc:
            self._fail_job(job_id, exc)
            raise

    def _load_content(
        self, source_path: Path, source: ItemContentSourcePointer
    ) -> AssessmentItemContent:
        canonical = self._resolve_artifact_primary(
            source.artifact_id,
            source.artifact_revision_id,
            source.sha256,
        )
        try:
            metadata = source_path.lstat()
            if (
                source_path != canonical
                or not stat.S_ISREG(metadata.st_mode)
                or source_path.is_symlink()
                or metadata.st_size > MAX_ITEM_CONTENT_BYTES
                or sha256_file(source_path) != source.sha256
            ):
                raise ValueError("unsafe content artifact")
            raw: object = json.loads(source_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("content artifact is not an object")
            validate_catalog_contract("assessment-item-content", raw)
            return AssessmentItemContent.model_validate(raw)
        except Exception as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "canonical item content artifact is invalid",
            ) from exc

    def _resolve_template(self, snapshot: QuestionTemplateSnapshot) -> Path:
        primary = self._resolve_artifact_primary(
            snapshot.template_artifact_id,
            snapshot.template_artifact_revision_id,
            snapshot.template_source_sha256,
        )
        if primary.name != "template.hwpx":
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "question-template artifact primary file is invalid",
            )
        self._verify_manifest_member(snapshot, "template.hwpx", primary)
        binding = self._artifact_file(primary.parent, "template-bindings.json")
        self._verify_manifest_member(snapshot, "template-bindings.json", binding)
        try:
            value: object = json.loads(binding.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "question-template binding manifest is invalid",
            ) from exc
        if not isinstance(value, dict) or any(
            value.get(key) != expected
            for key, expected in (
                ("template_id", snapshot.template_id),
                ("template_revision_id", snapshot.template_revision_id),
                ("template_sha256", snapshot.template_source_sha256),
                ("binding_manifest_sha256", snapshot.binding_manifest_sha256),
            )
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "question-template binding manifest does not match its release pin",
            )
        return primary.parent

    def _verify_manifest_member(
        self, snapshot: QuestionTemplateSnapshot, name: str, path: Path
    ) -> None:
        with self.sessions() as session:
            revision = session.get(
                ArtifactRevisionRecord,
                snapshot.template_artifact_revision_id,
            )
            files = revision.manifest.get("files") if revision is not None else None
            manifest = revision.manifest if revision is not None else {}
        entries = (
            [entry for entry in files if isinstance(entry, dict) and entry.get("file_name") == name]
            if isinstance(files, list)
            else []
        )
        try:
            invalid = (
                manifest.get("artifact_type") != "hwpx-template-revision"
                or manifest.get("logical_artifact_id") != snapshot.template_artifact_id
                or manifest.get("revision_id") != snapshot.template_artifact_revision_id
                or manifest.get("primary_file") != "template.hwpx"
                or manifest.get("content_hash") != snapshot.template_source_sha256
                or len(entries) != 1
                or entries[0].get("sha256") != sha256_file(path)
                or entries[0].get("bytes") != path.stat().st_size
            )
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "question-template artifact member is unreadable",
            ) from exc
        if invalid:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "question-template binding manifest is not pinned by its Artifact Revision",
            )

    def _resolve_artifact_primary(
        self, artifact_id: str, revision_id: str, expected_sha256: str
    ) -> Path:
        with self.sessions() as session:
            artifact = session.get(ArtifactRecord, artifact_id)
            revision = session.get(ArtifactRevisionRecord, revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != artifact_id
                or revision.content_hash != expected_sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "artifact pointer is stale or invalid",
                )
            primary_name = revision.manifest.get("primary_file")
            root = Path(revision.nas_path)
        if not isinstance(primary_name, str):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact has no typed primary file",
            )
        primary = self._artifact_file(root, primary_name)
        if sha256_file(primary) != expected_sha256:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact bytes do not match the pinned revision",
            )
        return primary

    @staticmethod
    def _artifact_file(root: Path, name: str) -> Path:
        relative = Path(name)
        candidate = root / relative
        current = root
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact file pointer is unsafe",
            )
        try:
            root_metadata = root.lstat()
            if not stat.S_ISDIR(root_metadata.st_mode) or root.is_symlink():
                raise ValueError("artifact root is unsafe")
            resolved_root = root.resolve(strict=True)
            for component in relative.parts:
                current = current / component
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("artifact path contains a symlink")
            metadata = candidate.lstat()
            if not stat.S_ISREG(metadata.st_mode) or not candidate.resolve(
                strict=True
            ).is_relative_to(resolved_root):
                raise ValueError("artifact path is not a contained regular file")
        except (OSError, ValueError) as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact file pointer is unsafe",
            ) from exc
        return candidate

    @staticmethod
    def _verify_output(output: Path, workspace: Path) -> None:
        try:
            metadata = output.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "question-template output is missing",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or output.is_symlink()
            or not output.resolve().is_relative_to(workspace.resolve())
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "question-template output materialization is unsafe",
            )

    @staticmethod
    def _metrics(structural: dict[str, Any]) -> tuple[int, int]:
        metrics = structural.get("metrics")
        if not isinstance(metrics, dict):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "question-template structural metrics are missing",
            )
        equations = metrics.get("native_equation_count")
        tables = metrics.get("total_native_table_count")
        if not isinstance(equations, int) or not isinstance(tables, int):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "question-template structural metrics are invalid",
            )
        return equations, tables

    def _completed_receipt(
        self, job_id: str, *, expected_build_id: str
    ) -> QuestionTemplateBuildReceipt:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            revision = (
                session.get(ArtifactRevisionRecord, job.revision_id) if job is not None else None
            )
            if job is None or job.status != JobState.SUCCEEDED.value or revision is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "existing question-template build is not a completed immutable result",
                )
            result = revision.result
            builder_result = result.get("builder_result")
            if not isinstance(builder_result, dict):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "completed question-template build has no typed result",
                )
            parsed = HwpxBuildResult.model_validate(builder_result)
            if parsed.build_id != expected_build_id:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "existing question-template build belongs to another application request",
                )
            return QuestionTemplateBuildReceipt(
                build_id=parsed.build_id,
                job_id=job.job_id,
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                output_sha256=revision.content_hash,
                native_equation_count=int(result["native_equation_count"]),
                native_table_count=int(result["native_table_count"]),
                total_native_table_count=int(result["total_native_table_count"]),
            )

    def _transition(self, job_id: str, target: JobState, event: str) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event)

    def _record_run(self, job_id: str, run: BuilderRun) -> None:
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise RuntimeError("question-template platform job disappeared")
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
            job.error_message = "question-template HWPX build failed"
            transition_job(
                session,
                job_id,
                JobState.FAILED,
                "HWPX_TEMPLATE_BUILD_FAILED",
                data={"error_code": code},
            )
