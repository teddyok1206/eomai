"""Whole-assessment HWPX rendering through the fixed content-team builder boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts import MockExamAssemblyManifestV1
from eom_hwpx_contracts import (
    ContentTeamExamAssemblyPointer,
    ContentTeamExamBuildResult,
    ContentTeamExamImageSource,
    ContentTeamExamItemSource,
    ContentTeamExamRenderRequest,
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    ContentTeamItemSource,
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
from eom_orchestrator.database import transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import select

from eom_hwpx_manager.content_team_service import (
    HANDOFF_MEDIA_TYPE,
    HANDOFF_MEMBER,
    HANDOFF_SCHEMA_REF,
    ITEM_JSON_MEMBER,
    ITEM_MARKDOWN_MEDIA_TYPE,
    ITEM_MARKDOWN_MEMBER,
    ITEM_MARKDOWN_SCHEMA_REF,
    ITEM_SCHEMA_REF,
    MAX_HANDOFF_BYTES,
    MAX_IMAGE_BYTES,
    MAX_ITEM_JSON_BYTES,
    MAX_MARKDOWN_BYTES,
    ArtifactMemberPointer,
    ContentTeamHwpxService,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.protocol import (
    HWPX_CONTENT_TEAM_EXAM_PROTOCOL_VERSION,
    content_team_exam_schema_bundle_hash,
)

EXAM_RENDERER = "content-team-exam"
EXAM_RENDERER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ContentTeamExamItemPointer:
    position: int
    placement_id: str
    item_id: str
    item_revision_id: str
    item_manifest_sha256: str
    source: ContentTeamItemSource
    images: tuple[ContentTeamImageSource, ...]


@dataclass(frozen=True)
class ContentTeamExamBuildReceipt:
    build_id: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    output_sha256: str
    item_count: int
    section_count: int
    native_equation_count: int
    native_table_count: int
    visual_count: int


class ContentTeamExamHwpxService(ContentTeamHwpxService):
    """Resolve each immutable item pointer, render, merge, validate, and commit once."""

    def build_exam(
        self,
        manifest: MockExamAssemblyManifestV1,
        items: tuple[ContentTeamExamItemPointer, ...],
        *,
        idempotency_key: str,
        build_id: str,
        handoff_snapshot: ContentTeamHandoffSnapshot,
    ) -> ContentTeamExamBuildReceipt:
        if handoff_snapshot != self.snapshot():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "content-team handoff release pin changed after exam request creation",
            )
        if tuple(
            (
                row.position,
                row.placement_id,
                row.item_id,
                row.item_revision_id,
                row.item_manifest_sha256,
            )
            for row in items
        ) != tuple(
            (
                row.position,
                row.placement_id,
                row.item_id,
                row.item_revision_id,
                row.item_manifest_sha256,
            )
            for row in manifest.placements
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "exam item pointers differ from the released Assembly",
            )
        member_requests: list[tuple[tuple[int, str, int], ArtifactMemberPointer]] = [
            (
                (0, "handoff", 0),
                ArtifactMemberPointer(
                    artifact_id=handoff_snapshot.artifact_id,
                    revision_id=handoff_snapshot.artifact_revision_id,
                    member_name=HANDOFF_MEMBER,
                    expected_sha256=handoff_snapshot.archive_sha256,
                    media_type=HANDOFF_MEDIA_TYPE,
                    schema_ref=HANDOFF_SCHEMA_REF,
                    max_bytes=MAX_HANDOFF_BYTES,
                ),
            )
        ]
        for item in items:
            member_requests.extend(
                (
                    (
                        (item.position, "json", 0),
                        ArtifactMemberPointer(
                            artifact_id=item.source.artifact_id,
                            revision_id=item.source.artifact_revision_id,
                            member_name=ITEM_JSON_MEMBER,
                            expected_sha256=item.source.json_sha256,
                            media_type="application/json",
                            schema_ref=ITEM_SCHEMA_REF,
                            max_bytes=MAX_ITEM_JSON_BYTES,
                        ),
                    ),
                    (
                        (item.position, "markdown", 0),
                        ArtifactMemberPointer(
                            artifact_id=item.source.artifact_id,
                            revision_id=item.source.artifact_revision_id,
                            member_name=ITEM_MARKDOWN_MEMBER,
                            expected_sha256=item.source.markdown_sha256,
                            media_type=ITEM_MARKDOWN_MEDIA_TYPE,
                            schema_ref=ITEM_MARKDOWN_SCHEMA_REF,
                            max_bytes=MAX_MARKDOWN_BYTES,
                        ),
                    ),
                )
            )
            member_requests.extend(
                (
                    (item.position, "image", image.visual_ordinal),
                    ArtifactMemberPointer(
                        artifact_id=image.artifact_id,
                        revision_id=image.artifact_revision_id,
                        member_name=image.artifact_member,
                        expected_sha256=image.sha256,
                        media_type=image.media_type,
                        schema_ref=image.schema_ref,
                        max_bytes=MAX_IMAGE_BYTES,
                    ),
                )
                for image in item.images
            )
        resolved_members = self._resolve_members(
            tuple(pointer for _key, pointer in member_requests)
        )
        member_paths = {
            key: path
            for (key, _pointer), path in zip(member_requests, resolved_members, strict=True)
        }
        handoff_path = member_paths[(0, "handoff", 0)]
        staged_items: list[
            tuple[
                ContentTeamExamItemSource,
                Path,
                Path,
                tuple[tuple[ContentTeamImageSource, Path], ...],
            ]
        ] = []
        for item in items:
            canonical = member_paths[(item.position, "json", 0)]
            content = self._load_resolved_content(canonical, item.source)
            markdown = member_paths[(item.position, "markdown", 0)]
            self._validate_image_sources(item.images, content)
            image_inputs = tuple(
                (
                    image,
                    member_paths[(item.position, "image", image.visual_ordinal)],
                )
                for image in item.images
            )
            prefix = f"input/items/{item.position:03d}"
            staged_items.append(
                (
                    ContentTeamExamItemSource(
                        position=item.position,
                        placement_id=item.placement_id,
                        item_id=item.item_id,
                        item_revision_id=item.item_revision_id,
                        item_manifest_sha256=item.item_manifest_sha256,
                        source_artifact_id=item.source.artifact_id,
                        source_artifact_revision_id=item.source.artifact_revision_id,
                        source_json_sha256=item.source.json_sha256,
                        source_markdown_sha256=item.source.markdown_sha256,
                        json_file=f"{prefix}/item-content.json",
                        markdown_file=f"{prefix}/content-team-item.md",
                        images=tuple(
                            ContentTeamExamImageSource(
                                **image.model_dump(mode="json", exclude={"file_name"}),
                                file_name=f"{prefix}/visual-{image.visual_ordinal}.png",
                            )
                            for image, _ in image_inputs
                        ),
                    ),
                    canonical,
                    markdown,
                    image_inputs,
                )
            )
        request = ContentTeamExamRenderRequest(
            build_id=build_id,
            assembly=ContentTeamExamAssemblyPointer(
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                manifest_sha256=manifest.manifest_sha256,
                policy_revision_id=manifest.policy_revision_id,
                policy_sha256=manifest.policy_sha256,
                graph_snapshot_revision_id=manifest.graph_snapshot_revision_id,
                graph_snapshot_sha256=manifest.graph_snapshot_sha256,
            ),
            handoff=handoff_snapshot,
            items=tuple(value[0] for value in staged_items),
        )
        request_raw = request.model_dump(mode="json")
        validate_hwpx_contract("content-team-exam-render-request", request_raw)
        item_set_sha256 = content_sha256(
            [
                {
                    "position": item.position,
                    "placement_id": item.placement_id,
                    "item_id": item.item_id,
                    "item_revision_id": item.item_revision_id,
                    "item_manifest_sha256": item.item_manifest_sha256,
                }
                for item in request.items
            ]
        )
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        artifact_revision_id = new_revision_id()
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session,
                HWPX_CONTENT_TEAM_EXAM_PROTOCOL_VERSION,
                content_team_exam_schema_bundle_hash(),
            )
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=HWPX_CONTENT_TEAM_EXAM_PROTOCOL_VERSION,
                idempotency_key=f"hwpx-content-team-exam:{idempotency_key}",
                task_type="hwpx-content-team-exam-build",
                request=request_raw,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
            )
            existing_job_id = job.job_id if not created else None
        if existing_job_id is not None:
            return self._completed_exam_receipt(existing_job_id, build_id)

        try:
            workspace = self.adapter.create_workspace(build_id)
            self.adapter.stage_file(workspace, handoff_snapshot.archive_file, handoff_path)
            for staged_item, source_path, markdown_path, images in staged_items:
                self.adapter.stage_file(workspace, staged_item.json_file, source_path)
                self.adapter.stage_file(workspace, staged_item.markdown_file, markdown_path)
                for image, image_path in images:
                    target = (
                        f"input/items/{staged_item.position:03d}/visual-{image.visual_ordinal}.png"
                    )
                    self.adapter.stage_file(workspace, target, image_path)
            self.adapter.write_json(workspace, "request.json", request_raw)
            log_root = self.settings.staging_root / job_id
            for state, event in (
                (JobState.VALIDATED, "HWPX_EXAM_INPUT_VALIDATED"),
                (JobState.QUEUED, "HWPX_EXAM_BUILD_QUEUED"),
                (JobState.CLAIMED, "HWPX_EXAM_BUILDER_CLAIMED"),
                (JobState.RUNNING, "HWPX_EXAM_RENDER_STARTED"),
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
                    "content-team exam HWPX builder failed",
                )
            self._transition(job_id, JobState.VALIDATING_RESULT, "HWPX_EXAM_RESULT_RECEIVED")
            result_raw = self.adapter.load_json(workspace / "result.json", workspace)
            validate_hwpx_contract("content-team-exam-build-result", result_raw)
            result = ContentTeamExamBuildResult.model_validate(result_raw)
            output = workspace / "output/content-team-exam.hwpx"
            self._verify_output(output, workspace)
            package_manifest = self.adapter.load_json(
                workspace / "output/package-manifest.json", workspace
            )
            report = self.adapter.load_json(
                workspace / "output/content-team-exam-validation.json", workspace
            )
            if (
                result.status != "SUCCEEDED"
                or result.build_id != build_id
                or result.assessment_assembly_revision_id
                != manifest.assessment_assembly_revision_id
                or result.assembly_manifest_sha256 != manifest.manifest_sha256
                or result.item_set_sha256 != item_set_sha256
                or result.item_count != len(items)
                or result.section_count != len(items)
                or result.output_sha256 != sha256_file(output)
                or package_manifest.get("package_sha256") != result.output_sha256
                or package_manifest.get("item_set_sha256") != item_set_sha256
                or package_manifest.get("assembly") != request.assembly.model_dump(mode="json")
                or report.get("status") != "PASS"
                or report.get("assessment_assembly_revision_id")
                != manifest.assessment_assembly_revision_id
                or report.get("assembly_manifest_sha256") != manifest.manifest_sha256
                or report.get("item_set_sha256") != item_set_sha256
                or report.get("item_count") != len(items)
                or report.get("equation_count") != result.equation_count
                or report.get("table_count") != result.table_count
                or report.get("visual_count") != result.visual_count
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "content-team exam result differs from its pinned Assembly request",
                )
            staged = stage_file_set_artifact(
                files={
                    "content-team-exam.hwpx": output,
                    "package-manifest.json": workspace / "output/package-manifest.json",
                    "content-team-exam-validation.json": (
                        workspace / "output/content-team-exam-validation.json"
                    ),
                    "renderer-result.json": workspace / "result.json",
                    "renderer-request.json": workspace / "request.json",
                },
                primary_file="content-team-exam.hwpx",
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=artifact_revision_id,
                artifact_type="hwpx-content-team-exam-build",
                staging=log_root / "artifact",
                manifest_version="content-team-exam-hwpx-artifact/1.0",
            )
            self._transition(job_id, JobState.COMMITTING, "HWPX_EXAM_COMMIT_STARTED")
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            stored_result: dict[str, Any] = {
                "schema_version": "1.0",
                "builder_result": result.model_dump(mode="json"),
                "assembly": request.assembly.model_dump(mode="json"),
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
                    "HWPX_EXAM_ARTIFACT_COMMITTED",
                    data={
                        "build_id": build_id,
                        "assessment_assembly_revision_id": (
                            manifest.assessment_assembly_revision_id
                        ),
                        "logical_artifact_id": artifact_id,
                        "revision_id": artifact_revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            return self._receipt(
                job_id, artifact_id, artifact_revision_id, staged.primary_hash, result
            )
        except Exception as exc:
            self._fail_job(job_id, exc)
            raise

    @staticmethod
    def _receipt(
        job_id: str,
        artifact_id: str,
        revision_id: str,
        output_sha256: str,
        result: ContentTeamExamBuildResult,
    ) -> ContentTeamExamBuildReceipt:
        return ContentTeamExamBuildReceipt(
            build_id=result.build_id,
            job_id=job_id,
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            output_sha256=output_sha256,
            item_count=result.item_count,
            section_count=result.section_count,
            native_equation_count=result.equation_count,
            native_table_count=result.table_count,
            visual_count=result.visual_count,
        )

    def _completed_exam_receipt(
        self, job_id: str, expected_build_id: str
    ) -> ContentTeamExamBuildReceipt:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            revision = (
                session.get(ArtifactRevisionRecord, job.revision_id) if job is not None else None
            )
            raw = revision.result.get("builder_result") if revision is not None else None
            if (
                job is None
                or job.status != JobState.SUCCEEDED.value
                or revision is None
                or not isinstance(raw, dict)
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "existing exam build is not a completed immutable result",
                )
            result = ContentTeamExamBuildResult.model_validate(raw)
            if result.build_id != expected_build_id:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                    "completed exam build belongs to another request",
                )
            return self._receipt(
                job.job_id,
                job.logical_artifact_id,
                job.revision_id,
                revision.content_hash,
                result,
            )
