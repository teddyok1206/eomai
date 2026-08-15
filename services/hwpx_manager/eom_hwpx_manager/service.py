"""Core-owned HWPX template import, isolated build, and immutable artifact finalization."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import (
    BuildResultStatus,
    HwpxBuildResult,
    HwpxItemDocument,
    validate_contract,
)
from eom_identifiers import (
    content_sha256,
    new_hwpx_build_id,
    new_hwpx_template_id,
    new_hwpx_template_revision_id,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_file,
)
from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
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
from eom_hwpx_manager.models import (
    HwpxBuildRecord,
    HwpxTemplateRecord,
    HwpxTemplateRevisionRecord,
    HwpxValidationRunRecord,
)
from eom_hwpx_manager.protocol import HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash
from eom_hwpx_manager.repository import (
    add_template_revision,
    add_validation,
    create_build,
    get_or_create_template,
    transition_build,
)
from eom_hwpx_manager.settings import HwpxSettings
from eom_hwpx_manager.state_machine import HwpxBuildState

RENDERER_VERSION = "0.1.0"
LOGGER = logging.getLogger("eom.hwpx_manager")


class HwpxService:
    def __init__(
        self,
        engine: Engine,
        settings: HwpxSettings | None = None,
        adapter: HwpxBuilderAdapter | None = None,
    ) -> None:
        self.settings = settings or HwpxSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.adapter = adapter or HwpxBuilderAdapter(self.settings)

    def inspect_template(self, source: Path) -> dict[str, Any]:
        workspace_id = f"inspect_{new_hwpx_template_revision_id().split('_', 1)[1]}"
        workspace = self.adapter.create_workspace(workspace_id)
        self.adapter.stage_file(workspace, "template.hwpx", source)
        log_root = self.settings.staging_root / workspace_id
        run = self.adapter.run(
            workspace,
            "inspect-package",
            ["--input", "template.hwpx", "--output", "template-analysis.json"],
            log_root,
        )
        if run.exit_code != 0:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "template inspection failed"
            )
        return self.adapter.load_json(workspace / "template-analysis.json", workspace)

    def validate_file(self, source: Path) -> dict[str, Any]:
        workspace_id = f"validate_{new_hwpx_template_revision_id().split('_', 1)[1]}"
        workspace = self.adapter.create_workspace(workspace_id)
        self.adapter.stage_file(workspace, "candidate.hwpx", source)
        run = self.adapter.run(
            workspace,
            "validate-package",
            ["--input", "candidate.hwpx", "--output", "validation.json"],
            self.settings.staging_root / workspace_id,
        )
        report = self.adapter.load_json(workspace / "validation.json", workspace)
        if run.exit_code != 0 or report.get("status") != "PASS":
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "HWPX structural validation failed",
            )
        return report

    def extract_file(self, source: Path) -> dict[str, Any]:
        bindings = source.parent / "template-bindings.json"
        if not bindings.is_file():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "template-bindings.json is required beside the HWPX",
            )
        workspace_id = f"extract_{new_hwpx_template_revision_id().split('_', 1)[1]}"
        workspace = self.adapter.create_workspace(workspace_id)
        self.adapter.stage_file(workspace, "candidate.hwpx", source)
        self.adapter.stage_file(workspace, "template-bindings.json", bindings)
        run = self.adapter.run(
            workspace,
            "extract-semantic",
            [
                "--input",
                "candidate.hwpx",
                "--bindings",
                "template-bindings.json",
                "--output",
                "semantic.json",
            ],
            self.settings.staging_root / workspace_id,
        )
        if run.exit_code != 0:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_SEMANTIC_MISMATCH,
                "HWPX semantic extraction failed",
            )
        return self.adapter.load_json(workspace / "semantic.json", workspace)

    def import_template(
        self, source: Path, *, logical_name: str, hancom_version: str
    ) -> HwpxTemplateRevisionRecord:
        expected = self.settings.reference_inbox / "eom_hwpx_reference_v1.hwpx"
        if source.resolve(strict=False) != expected.resolve(strict=False) or not source.is_file():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "reference must be the fixed read-only inbox candidate",
            )
        source_hash = sha256_file(source)
        with self.sessions() as session:
            existing = session.scalar(
                select(HwpxTemplateRevisionRecord)
                .join(HwpxTemplateRecord)
                .where(
                    HwpxTemplateRecord.logical_name == logical_name,
                    HwpxTemplateRevisionRecord.source_sha256 == source_hash,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing

        template_id = new_hwpx_template_id()
        template_revision_id = new_hwpx_template_revision_id()
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        request = {
            "logical_name": logical_name,
            "source_sha256": source_hash,
            "hancom_version_declared": hancom_version,
        }
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash())
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-template:{logical_name}:{source_hash}",
                task_type="hwpx-template-import",
                request=request,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
        if not created:
            with self.sessions() as session:
                record = session.scalar(
                    select(HwpxTemplateRevisionRecord).where(
                        HwpxTemplateRevisionRecord.source_artifact_id == job.logical_artifact_id
                    )
                )
                if record is None:
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                        "template import job has no immutable revision",
                    )
                session.expunge(record)
                return record

        try:
            workspace = self.adapter.create_workspace(template_revision_id)
            template = self.adapter.stage_file(workspace, "template.hwpx", source)
            reference_png = self.adapter.stage_file(
                workspace,
                "eom-placeholder-image-reference.png",
                self.settings.reference_kit / "eom-placeholder-image-reference.png",
            )
            log_root = self.settings.staging_root / job_id
            self._platform_transition(job_id, JobState.VALIDATED, "HWPX_REFERENCE_VALIDATED")
            self._platform_transition(job_id, JobState.QUEUED, "HWPX_REFERENCE_QUEUED")
            self._platform_transition(
                job_id,
                JobState.CLAIMED,
                "HWPX_BUILDER_CLAIMED",
                {"linux_user": self.settings.builder_user},
            )
            self._platform_transition(job_id, JobState.RUNNING, "HWPX_ANALYSIS_STARTED")
            inspect = self.adapter.run(
                workspace,
                "inspect-package",
                ["--input", "template.hwpx", "--output", "template-analysis.json"],
                log_root,
            )
            self._record_builder_run(job_id, inspect)
            if inspect.exit_code != 0:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "reference analysis failed"
                )
            compile_run = self.adapter.run(
                workspace,
                "compile-bindings",
                [
                    "--input",
                    "template.hwpx",
                    "--output",
                    "template-bindings.json",
                    "--template-id",
                    template_id,
                    "--template-revision-id",
                    template_revision_id,
                    "--reference-image-sha256",
                    sha256_file(reference_png),
                ],
                log_root,
            )
            self._record_builder_run(job_id, compile_run)
            if compile_run.exit_code != 0:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "binding compilation failed"
                )
            self._platform_transition(job_id, JobState.VALIDATING_RESULT, "HWPX_BINDINGS_RECEIVED")
            analysis = self.adapter.load_json(workspace / "template-analysis.json", workspace)
            bindings = self.adapter.load_json(workspace / "template-bindings.json", workspace)
            if bindings.get("template_sha256") != source_hash:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                    "binding manifest does not match reference bytes",
                )
            staged = stage_file_set_artifact(
                files={
                    "template.hwpx": template,
                    "template-analysis.json": workspace / "template-analysis.json",
                    "template-bindings.json": workspace / "template-bindings.json",
                },
                primary_file="template.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
                artifact_type="hwpx-template-revision",
                staging=log_root / "artifact",
            )
            self._platform_transition(job_id, JobState.COMMITTING, "HWPX_TEMPLATE_COMMIT_STARTED")
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
                    result={"analysis": analysis, "bindings": bindings},
                )
                template_record = get_or_create_template(
                    session,
                    template_id=template_id,
                    logical_name=logical_name,
                    description="PLACEHOLDER combined item HWPX reference",
                )
                revision = add_template_revision(
                    session,
                    template_revision_id=template_revision_id,
                    template=template_record,
                    source_artifact_id=artifact_id,
                    source_artifact_revision_id=artifact_revision_id,
                    source_sha256=source_hash,
                    binding_manifest_sha256=str(bindings["binding_manifest_sha256"]),
                    owpml_version=json.dumps(
                        analysis.get("version_info", {}), ensure_ascii=False, sort_keys=True
                    )[:128],
                    hancom_version=hancom_version,
                    package_profile={
                        "mimetype": analysis.get("mimetype"),
                        "namespaces": analysis.get("namespaces", []),
                    },
                    analysis_summary={
                        "entries": len(analysis.get("entries", [])),
                        "sections": analysis.get("sections", []),
                        "warnings": analysis.get("warnings", []),
                    },
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "HWPX_TEMPLATE_COMMITTED",
                    data={"template_revision_id": revision.template_revision_id},
                )
                session.flush()
                session.expunge(revision)
                log_hwpx_event(
                    LOGGER,
                    logging.INFO,
                    "HWPX_TEMPLATE_IMPORTED",
                    template_id=revision.template_id,
                    template_revision_id=revision.template_revision_id,
                    artifact_id=artifact_id,
                    artifact_revision_id=artifact_revision_id,
                )
                return revision
        except Exception as exc:
            self._fail_platform_job(job_id, exc)
            raise

    def build(
        self,
        template_revision_id: str,
        input_path: Path,
        idempotency_key: str,
    ) -> HwpxBuildRecord:
        document_raw = json.loads(input_path.read_text(encoding="utf-8"))
        validate_contract("item-document", document_raw)
        document = HwpxItemDocument.model_validate(document_raw)
        build_id = new_hwpx_build_id()
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        with transaction(self.sessions) as session:
            template_revision = session.get(HwpxTemplateRevisionRecord, template_revision_id)
            if template_revision is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING, "template revision does not exist"
                )
            ensure_protocol_version(session, HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash())
            job, _ = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-build-job:{idempotency_key}",
                task_type="hwpx-build",
                request={
                    "template_revision_id": template_revision_id,
                    "input_sha256": content_sha256(document_raw),
                },
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
            build, created = create_build(
                session,
                build_id=build_id,
                template_revision_id=template_revision_id,
                platform_job_id=job.job_id,
                input_payload=document_raw,
                renderer_version=RENDERER_VERSION,
                idempotency_key=idempotency_key,
            )
            if not created:
                session.expunge(build)
                return build
            source_revision_id = template_revision.source_artifact_revision_id

        try:
            with self.sessions() as session:
                source_revision = session.get(ArtifactRevisionRecord, source_revision_id)
                if source_revision is None:
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                        "template artifact revision does not exist",
                    )
                template_root = Path(source_revision.nas_path)
                template_hash = source_revision.content_hash

            workspace = self.adapter.create_workspace(build_id)
            self.adapter.stage_file(workspace, "template.hwpx", template_root / "template.hwpx")
            self.adapter.stage_file(
                workspace, "template-bindings.json", template_root / "template-bindings.json"
            )
            self.adapter.stage_file(workspace, "input/document.json", input_path)
            image_source = input_path.parent / document.item.image.source_path
            self.adapter.stage_file(
                workspace, "input/eom-placeholder-image-output.png", image_source
            )
            request = {
                "request_version": "1.0",
                "build_id": build_id,
                "template_id": self._template_id(template_revision_id),
                "template_revision_id": template_revision_id,
                "template_sha256": template_hash,
                "template_file": "template.hwpx",
                "bindings_file": "template-bindings.json",
                "document_file": "input/document.json",
                "image_file": "input/eom-placeholder-image-output.png",
                "output_directory": "output",
            }
            self.adapter.write_json(workspace, "request.json", request)
            log_root = self.settings.staging_root / job_id
            self._transition_both(
                build_id, job_id, HwpxBuildState.VALIDATING_INPUT, JobState.VALIDATED
            )
            self._transition_both(build_id, job_id, HwpxBuildState.STAGING, JobState.QUEUED)
            self._platform_transition(
                job_id,
                JobState.CLAIMED,
                "HWPX_BUILDER_CLAIMED",
                {"linux_user": self.settings.builder_user},
            )
            self._transition_both(build_id, job_id, HwpxBuildState.RENDERING, JobState.RUNNING)
            run = self.adapter.run(
                workspace,
                "render",
                ["--request", "request.json", "--result", "result.json"],
                log_root,
            )
            self._record_builder_run(job_id, run)
            if run.exit_code != 0:
                result_candidate = workspace / "result.json"
                if result_candidate.is_file():
                    result_raw = self.adapter.load_json(result_candidate, workspace)
                    code = next(iter(result_raw.get("errors", [])), "HWPX_BUILDER_FAILED")
                else:
                    code = "HWPX_BUILDER_FAILED"
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED, f"builder failed: {code}"
                )
            with transaction(self.sessions) as session:
                current = session.get(HwpxBuildRecord, build_id)
                if current is None:
                    raise RuntimeError("HWPX build disappeared")
                transition_build(session, current, HwpxBuildState.PACKAGING)
                transition_build(session, current, HwpxBuildState.VALIDATING_OUTPUT)
                transition_job(session, job_id, JobState.VALIDATING_RESULT, "HWPX_RESULT_RECEIVED")
            result_raw = self.adapter.load_json(workspace / "result.json", workspace)
            validate_contract("build-result", result_raw)
            result = HwpxBuildResult.model_validate(result_raw)
            output = workspace / "output/placeholder_item_combined.hwpx"
            structural = self.adapter.load_json(
                workspace / "output/structural-validation.json", workspace
            )
            semantic = self.adapter.load_json(
                workspace / "output/semantic-validation.json", workspace
            )
            if (
                result.status != BuildResultStatus.PENDING_MANUAL_HANCOM_VALIDATION
                or result.input_sha256 != content_sha256(document_raw)
                or result.renderer_version != RENDERER_VERSION
                or result.output_sha256 != sha256_file(output)
                or structural.get("status") != "PASS"
                or semantic.get("status") != "PASS"
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "builder output did not pass core validation",
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
                artifact_type="hwpx-build",
                staging=log_root / "artifact",
            )
            with transaction(self.sessions) as session:
                current = session.get(HwpxBuildRecord, build_id)
                if current is None:
                    raise RuntimeError("HWPX build disappeared")
                transition_build(session, current, HwpxBuildState.COMMITTING)
                transition_job(session, job_id, JobState.COMMITTING, "HWPX_COMMIT_STARTED")
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
                current = session.get(HwpxBuildRecord, build_id)
                if current is None:
                    raise RuntimeError("HWPX build disappeared")
                current.output_artifact_id = artifact_id
                current.output_artifact_revision_id = artifact_revision_id
                current.output_sha256 = staged.primary_hash
                current.structural_report_artifact_id = artifact_id
                current.semantic_report_artifact_id = artifact_id
                transition_build(session, current, HwpxBuildState.PENDING_MANUAL_VALIDATION)
                add_validation(
                    session,
                    build_id=build_id,
                    validation_type="STRUCTURAL",
                    status="PASS",
                    validator_version=RENDERER_VERSION,
                    artifact_id=artifact_id,
                    revision_id=artifact_revision_id,
                )
                add_validation(
                    session,
                    build_id=build_id,
                    validation_type="SEMANTIC",
                    status="PASS",
                    validator_version=RENDERER_VERSION,
                    artifact_id=artifact_id,
                    revision_id=artifact_revision_id,
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "HWPX_ARTIFACT_COMMITTED",
                    data={
                        "build_id": build_id,
                        "logical_artifact_id": artifact_id,
                        "revision_id": artifact_revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
                session.flush()
                session.expunge(current)
                log_hwpx_event(
                    LOGGER,
                    logging.INFO,
                    "HWPX_BUILD_COMMITTED",
                    build_id=current.build_id,
                    template_revision_id=current.template_revision_id,
                    input_sha256=current.input_sha256,
                    output_sha256=current.output_sha256,
                    artifact_id=current.output_artifact_id,
                    artifact_revision_id=current.output_artifact_revision_id,
                    validation_status="PASS",
                )
                return current
        except Exception as exc:
            self._fail_build(build_id, job_id, exc)
            raise

    def list_templates(self) -> list[HwpxTemplateRecord]:
        with self.sessions() as session:
            values = list(
                session.scalars(select(HwpxTemplateRecord).order_by(HwpxTemplateRecord.created_at))
            )
            for value in values:
                session.expunge(value)
            return values

    def list_builds(self, limit: int = 50) -> list[HwpxBuildRecord]:
        with self.sessions() as session:
            values = list(
                session.scalars(
                    select(HwpxBuildRecord).order_by(HwpxBuildRecord.created_at.desc()).limit(limit)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def get_build(self, build_id: str) -> HwpxBuildRecord:
        with self.sessions() as session:
            build = session.get(HwpxBuildRecord, build_id)
            if build is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_NOT_FOUND, "HWPX build does not exist"
                )
            session.expunge(build)
            return build

    def build_validations(self, build_id: str) -> list[HwpxValidationRunRecord]:
        with self.sessions() as session:
            values = list(
                session.scalars(
                    select(HwpxValidationRunRecord)
                    .where(HwpxValidationRunRecord.build_id == build_id)
                    .order_by(HwpxValidationRunRecord.performed_at)
                )
            )
            for value in values:
                session.expunge(value)
            return values

    def start_manual_validation(self, build_id: str) -> HwpxBuildRecord:
        with transaction(self.sessions) as session:
            build = session.execute(
                select(HwpxBuildRecord)
                .where(HwpxBuildRecord.build_id == build_id)
                .with_for_update()
            ).scalar_one_or_none()
            if build is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_NOT_FOUND, "HWPX build does not exist"
                )
            if build.status != HwpxBuildState.PENDING_MANUAL_VALIDATION.value:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "build is not awaiting manual validation",
                )
            build.manual_validation_status = "IN_PROGRESS"
            session.flush()
            session.expunge(build)
            return build

    def complete_manual_validation(
        self,
        build_id: str,
        *,
        hancom_version: str,
        windows_version: str,
        open_result: str,
        save_result: str,
        resaved_file: Path,
        performed_by: str,
        notes: str,
    ) -> HwpxBuildRecord:
        if open_result not in {"pass", "fail"} or save_result not in {"pass", "fail"}:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "manual results must be pass or fail",
            )
        if not resaved_file.is_file() or not resaved_file.resolve().is_relative_to(
            self.settings.manual_inbox.resolve()
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "re-saved HWPX must be in the fixed manual inbox",
            )
        with self.sessions() as session:
            build = session.get(HwpxBuildRecord, build_id)
            if build is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_NOT_FOUND, "HWPX build does not exist"
                )
            if build.status != HwpxBuildState.PENDING_MANUAL_VALIDATION.value:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "build is not awaiting manual validation",
                )
            template = session.get(HwpxTemplateRevisionRecord, build.template_revision_id)
            if template is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "template revision does not exist",
                )
            template_artifact = session.get(
                ArtifactRevisionRecord, template.source_artifact_revision_id
            )
            if template_artifact is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "template artifact revision does not exist",
                )
            input_payload = build.input_payload
            template_root = Path(template_artifact.nas_path)

        validation_id = new_hwpx_build_id()
        workspace = self.adapter.create_workspace(validation_id)
        self.adapter.stage_file(workspace, "resaved.hwpx", resaved_file)
        self.adapter.stage_file(
            workspace, "template-bindings.json", template_root / "template-bindings.json"
        )
        self.adapter.write_json(workspace, "expected.json", input_payload)
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        revision_id = new_revision_id()
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, HWPX_PROTOCOL_VERSION, hwpx_schema_bundle_hash())
            submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-manual:{build_id}:{sha256_file(resaved_file)}",
                task_type="hwpx-manual-validation",
                request={"build_id": build_id, "resaved_sha256": sha256_file(resaved_file)},
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
            )
        log_root = self.settings.staging_root / job_id
        try:
            for target, event in (
                (JobState.VALIDATED, "HWPX_MANUAL_INPUT_VALIDATED"),
                (JobState.QUEUED, "HWPX_MANUAL_VALIDATION_QUEUED"),
                (JobState.CLAIMED, "HWPX_BUILDER_CLAIMED"),
                (JobState.RUNNING, "HWPX_RESAVED_VALIDATION_STARTED"),
            ):
                self._platform_transition(job_id, target, event)
            structural_run = self.adapter.run(
                workspace,
                "validate-package",
                ["--input", "resaved.hwpx", "--output", "resaved-structural.json"],
                log_root,
            )
            semantic_run = self.adapter.run(
                workspace,
                "compare-semantic",
                [
                    "--expected",
                    "expected.json",
                    "--actual-hwpx",
                    "resaved.hwpx",
                    "--bindings",
                    "template-bindings.json",
                    "--output",
                    "resaved-semantic.json",
                ],
                log_root,
            )
            self._record_builder_run(job_id, semantic_run)
            self._platform_transition(
                job_id, JobState.VALIDATING_RESULT, "HWPX_RESAVED_REPORTS_RECEIVED"
            )
            structural = self.adapter.load_json(workspace / "resaved-structural.json", workspace)
            semantic = self.adapter.load_json(workspace / "resaved-semantic.json", workspace)
            comparison_pass = (
                structural_run.exit_code == 0
                and semantic_run.exit_code == 0
                and structural.get("status") == "PASS"
                and semantic.get("status") == "PASS"
            )
            staged = stage_file_set_artifact(
                files={
                    "resaved.hwpx": workspace / "resaved.hwpx",
                    "resaved-structural.json": workspace / "resaved-structural.json",
                    "resaved-semantic.json": workspace / "resaved-semantic.json",
                },
                primary_file="resaved.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
                artifact_type="hwpx-manual-validation",
                staging=log_root / "artifact",
            )
            self._platform_transition(job_id, JobState.COMMITTING, "HWPX_RESAVED_COMMIT_STARTED")
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            overall_pass = open_result == "pass" and save_result == "pass" and comparison_pass
            with transaction(self.sessions) as session:
                job = session.get(JobRecord, job_id)
                build = session.get(HwpxBuildRecord, build_id)
                if job is None or build is None:
                    raise RuntimeError("manual validation records disappeared")
                create_artifact_records(
                    session,
                    job=job,
                    content_hash=staged.primary_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.primary_bytes,
                    nas_path=str(final),
                    manifest=staged.manifest,
                    result={"structural": structural, "semantic": semantic},
                )
                for validation_type, status in (
                    ("MANUAL_HANCOM_OPEN", open_result.upper()),
                    ("MANUAL_HANCOM_SAVE", save_result.upper()),
                    ("RESAVED_SEMANTIC_COMPARE", "PASS" if comparison_pass else "FAIL"),
                ):
                    add_validation(
                        session,
                        build_id=build_id,
                        validation_type=validation_type,
                        status=status,
                        validator_version=RENDERER_VERSION,
                        artifact_id=artifact_id,
                        revision_id=revision_id,
                        hancom_version=hancom_version,
                        windows_version=windows_version,
                        performed_by=performed_by,
                        notes=notes,
                    )
                build.manual_validation_status = "PASS" if overall_pass else "FAIL"
                transition_build(
                    session,
                    build,
                    HwpxBuildState.SUCCEEDED if overall_pass else HwpxBuildState.FAILED,
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "HWPX_RESAVED_ARTIFACT_COMMITTED",
                    data={"build_id": build_id, "manual_status": build.manual_validation_status},
                )
                session.flush()
                session.expunge(build)
                return build
        except Exception as exc:
            self._fail_platform_job(job_id, exc)
            raise

    def _template_id(self, template_revision_id: str) -> str:
        with self.sessions() as session:
            revision = session.get(HwpxTemplateRevisionRecord, template_revision_id)
            if revision is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING, "template revision does not exist"
                )
            return revision.template_id

    def _transition_both(
        self,
        build_id: str,
        job_id: str,
        build_target: HwpxBuildState,
        job_target: JobState,
    ) -> None:
        with transaction(self.sessions) as session:
            build = session.get(HwpxBuildRecord, build_id)
            if build is None:
                raise RuntimeError("HWPX build disappeared")
            transition_build(session, build, build_target)
            transition_job(session, job_id, job_target, f"HWPX_{job_target.value}")

    def _platform_transition(
        self, job_id: str, target: JobState, event: str, data: dict[str, Any] | None = None
    ) -> None:
        with transaction(self.sessions) as session:
            transition_job(session, job_id, target, event, data=data)

    def _record_builder_run(self, job_id: str, run: BuilderRun) -> None:
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise RuntimeError("HWPX platform job disappeared")
            job.worker_exit_code = run.exit_code
            job.worker_stdout_path = str(run.stdout_path)
            job.worker_stderr_path = str(run.stderr_path)

    def _fail_platform_job(self, job_id: str, error: Exception) -> None:
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
            job.error_message = "HWPX operation failed"
            transition_job(
                session, job_id, JobState.FAILED, "HWPX_OPERATION_FAILED", data={"error_code": code}
            )

    def _fail_build(self, build_id: str, job_id: str, error: Exception) -> None:
        error_code = (
            error.code.value
            if isinstance(error, HwpxManagerError)
            else HwpxManagerErrorCode.HWPX_BUILDER_FAILED.value
        )
        with transaction(self.sessions) as session:
            build = session.get(HwpxBuildRecord, build_id)
            if build is not None and HwpxBuildState(build.status) not in {
                HwpxBuildState.SUCCEEDED,
                HwpxBuildState.FAILED,
            }:
                build.failure_code = error_code
                build.sanitized_failure_summary = "HWPX build failed"
                transition_build(session, build, HwpxBuildState.FAILED)
        self._fail_platform_job(job_id, error)
        log_hwpx_event(
            LOGGER,
            logging.ERROR,
            "HWPX_BUILD_FAILED",
            build_id=build_id,
            error_code=error_code,
        )
