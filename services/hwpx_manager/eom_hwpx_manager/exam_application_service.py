"""FIFO application use case for released Assessment Assembly HWPX builds."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from eom_catalog_contracts import MockExamAssemblyManifestV1
from eom_catalog_service.mock_exam_assembly_service import MockExamAssemblyService
from eom_hwpx_contracts import (
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    ContentTeamItemSource,
)
from eom_identifiers import content_sha256, new_hwpx_build_id
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import Engine, select

from eom_hwpx_manager.application_service import (
    HwpxApplicationService,
    ItemRevisionResolver,
    SecureHwpxDownload,
)
from eom_hwpx_manager.application_state import ApplicationBuildState, require_application_transition
from eom_hwpx_manager.content_team_exam_service import (
    EXAM_RENDERER,
    EXAM_RENDERER_VERSION,
    ContentTeamExamHwpxService,
    ContentTeamExamItemPointer,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.models import HwpxAssessmentAssemblyBuildRecord


class ExamHwpxApplicationService:
    """Persist and process immutable whole-exam builds without storing HWPX bytes in DB."""

    def __init__(
        self,
        engine: Engine,
        *,
        registry: ItemRevisionResolver,
        renderer: ContentTeamExamHwpxService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.registry = registry
        self.renderer = renderer or ContentTeamExamHwpxService(engine)

    def request_build(
        self,
        assembly_revision_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> tuple[HwpxAssessmentAssemblyBuildRecord, bool]:
        manifest = self._manifest(assembly_revision_id)
        handoff = self.renderer.snapshot()
        item_set_sha256 = self._item_set_sha256(manifest)
        request_sha256 = self._request_sha256(manifest, handoff)
        with transaction(self.sessions) as session:
            existing = session.scalar(
                select(HwpxAssessmentAssemblyBuildRecord).where(
                    HwpxAssessmentAssemblyBuildRecord.created_by_operator_id == operator_id,
                    HwpxAssessmentAssemblyBuildRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                        "exam HWPX build idempotency conflict",
                    )
                session.expunge(existing)
                return existing, False
            record = HwpxAssessmentAssemblyBuildRecord(
                build_id=new_hwpx_build_id(),
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                assembly_manifest_sha256=manifest.manifest_sha256,
                policy_revision_id=manifest.policy_revision_id,
                policy_sha256=manifest.policy_sha256,
                graph_snapshot_revision_id=manifest.graph_snapshot_revision_id,
                graph_snapshot_sha256=manifest.graph_snapshot_sha256,
                item_set_sha256=item_set_sha256,
                renderer=EXAM_RENDERER,
                renderer_version=EXAM_RENDERER_VERSION,
                request_sha256=request_sha256,
                idempotency_key=idempotency_key,
                created_by_operator_id=operator_id,
                state=ApplicationBuildState.REQUESTED.value,
                validation_state="PENDING",
                item_count=len(manifest.placements),
                resource_version=1,
            )
            session.add(record)
            session.flush()
            session.expunge(record)
            return record, True

    def get_build(self, build_id: str) -> HwpxAssessmentAssemblyBuildRecord:
        with self.sessions() as session:
            record = session.get(HwpxAssessmentAssemblyBuildRecord, build_id)
            if record is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND,
                    "assessment HWPX build does not exist",
                )
            session.expunge(record)
            return record

    def process_next(self) -> HwpxAssessmentAssemblyBuildRecord | None:
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(HwpxAssessmentAssemblyBuildRecord)
                .where(
                    HwpxAssessmentAssemblyBuildRecord.state == ApplicationBuildState.REQUESTED.value
                )
                .order_by(
                    HwpxAssessmentAssemblyBuildRecord.created_at,
                    HwpxAssessmentAssemblyBuildRecord.build_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            self._transition(record, ApplicationBuildState.RUNNING)
            record.started_at = datetime.now(UTC)
            record.resource_version += 1
            session.flush()
            session.expunge(record)
        try:
            manifest = self._manifest(record.assessment_assembly_revision_id)
            if (
                manifest.assessment_assembly_id != record.assessment_assembly_id
                or manifest.manifest_sha256 != record.assembly_manifest_sha256
                or manifest.policy_revision_id != record.policy_revision_id
                or manifest.policy_sha256 != record.policy_sha256
                or manifest.graph_snapshot_revision_id != record.graph_snapshot_revision_id
                or manifest.graph_snapshot_sha256 != record.graph_snapshot_sha256
                or self._item_set_sha256(manifest) != record.item_set_sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "released Assessment Assembly changed after request admission",
                )
            handoff = self.renderer.snapshot()
            if self._request_sha256(manifest, handoff) != record.request_sha256:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "content-team handoff release changed after exam request admission",
                )
            receipt = self.renderer.build_exam(
                manifest,
                self._resolve_items(manifest),
                idempotency_key=record.idempotency_key,
                build_id=record.build_id,
                handoff_snapshot=handoff,
            )
            with transaction(self.sessions) as session:
                current = session.get(HwpxAssessmentAssemblyBuildRecord, record.build_id)
                if current is None:
                    raise RuntimeError("claimed assessment HWPX build disappeared")
                self._transition(current, ApplicationBuildState.VALIDATING)
                current.platform_job_id = receipt.job_id
                current.item_count = receipt.item_count
                current.section_count = receipt.section_count
                current.native_equation_count = receipt.native_equation_count
                current.native_table_count = receipt.native_table_count
                current.visual_count = receipt.visual_count
                current.output_artifact_id = receipt.artifact_id
                current.output_artifact_revision_id = receipt.artifact_revision_id
                current.output_sha256 = receipt.output_sha256
                current.output_filename = (
                    f"eom-mock-exam-{current.assessment_assembly_revision_id}.hwpx"
                )
                current.validation_state = "PASS"
                self._transition(current, ApplicationBuildState.SUCCEEDED)
                current.completed_at = datetime.now(UTC)
                current.resource_version += 1
                session.flush()
                session.expunge(current)
                return current
        except Exception as exc:
            self._fail_build(record.build_id, exc)
            raise

    def secure_download(self, build_id: str) -> SecureHwpxDownload:
        record = self.get_build(build_id)
        if (
            record.state != ApplicationBuildState.SUCCEEDED.value
            or record.validation_state != "PASS"
            or not record.output_artifact_id
            or not record.output_artifact_revision_id
            or not record.output_sha256
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE,
                "validated assessment HWPX output is unavailable",
            )
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, record.output_artifact_revision_id)
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != record.output_artifact_id
                or revision.content_hash != record.output_sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "assessment HWPX Artifact Revision pointer is stale",
                )
            path = HwpxApplicationService._primary_file(revision)
        fd = HwpxApplicationService._verified_fd(path, record.output_sha256)
        size = os.fstat(fd).st_size
        filename = record.output_filename or f"eom-{record.build_id}.hwpx"
        return SecureHwpxDownload(
            fd,
            HwpxApplicationService._safe_filename(filename),
            size,
            record.output_sha256,
        )

    def _manifest(self, revision_id: str) -> MockExamAssemblyManifestV1:
        with self.sessions() as session:
            manifest = MockExamAssemblyService.inspect(session, revision_id)
        if manifest is None or manifest.revision_state != "RELEASED":
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "released Assessment Assembly revision does not exist",
            )
        return manifest

    def _resolve_items(
        self, manifest: MockExamAssemblyManifestV1
    ) -> tuple[ContentTeamExamItemPointer, ...]:
        revision_ids = tuple(placement.item_revision_id for placement in manifest.placements)
        try:
            revisions = self.registry.inspect_revisions(revision_ids)
        except Exception as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "Assembly Item Revision set no longer resolves",
            ) from exc
        revision_by_id = {str(revision["item_revision_id"]): revision for revision in revisions}
        if len(revision_by_id) != len(revision_ids):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "Assembly Item Revision set is incomplete or duplicated",
            )
        resolved: list[ContentTeamExamItemPointer] = []
        for placement in manifest.placements:
            revision: dict[str, Any] = revision_by_id[placement.item_revision_id]
            if (
                revision.get("item_id") != placement.item_id
                or revision.get("manifest_sha256") != placement.item_manifest_sha256
                or revision.get("revision_state") not in {"APPROVED", "SUPERSEDED"}
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                    "Assembly Item Revision pointer is stale",
                )
            component = HwpxApplicationService._content_team_item_component(revision)
            metadata = component.get("metadata")
            if (
                not isinstance(metadata, dict)
                or metadata.get("editorial_markdown_member") != "content-team-item.md"
                or not isinstance(metadata.get("editorial_markdown_sha256"), str)
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "Assembly item has no canonical content-team Markdown pointer",
                )
            resolved.append(
                ContentTeamExamItemPointer(
                    position=placement.position,
                    placement_id=placement.placement_id,
                    item_id=placement.item_id,
                    item_revision_id=placement.item_revision_id,
                    item_manifest_sha256=placement.item_manifest_sha256,
                    source=ContentTeamItemSource(
                        artifact_id=str(component["artifact_id"]),
                        artifact_revision_id=str(component["artifact_revision_id"]),
                        json_sha256=str(component["sha256"]),
                        markdown_sha256=str(metadata["editorial_markdown_sha256"]),
                    ),
                    images=tuple(
                        ContentTeamImageSource.model_validate(value)
                        for value in HwpxApplicationService._content_team_image_sources(revision)
                    ),
                )
            )
        return tuple(resolved)

    @staticmethod
    def _item_set_sha256(manifest: MockExamAssemblyManifestV1) -> str:
        return content_sha256(
            [
                {
                    "position": row.position,
                    "placement_id": row.placement_id,
                    "item_id": row.item_id,
                    "item_revision_id": row.item_revision_id,
                    "item_manifest_sha256": row.item_manifest_sha256,
                }
                for row in manifest.placements
            ]
        )

    @classmethod
    def _request_sha256(
        cls,
        manifest: MockExamAssemblyManifestV1,
        handoff: ContentTeamHandoffSnapshot,
    ) -> str:
        return content_sha256(
            {
                "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
                "assembly_manifest_sha256": manifest.manifest_sha256,
                "policy_revision_id": manifest.policy_revision_id,
                "policy_sha256": manifest.policy_sha256,
                "graph_snapshot_revision_id": manifest.graph_snapshot_revision_id,
                "graph_snapshot_sha256": manifest.graph_snapshot_sha256,
                "item_set_sha256": cls._item_set_sha256(manifest),
                "renderer": EXAM_RENDERER,
                "renderer_version": EXAM_RENDERER_VERSION,
                "handoff": handoff.model_dump(mode="json"),
            }
        )

    @staticmethod
    def _transition(
        record: HwpxAssessmentAssemblyBuildRecord, target: ApplicationBuildState
    ) -> None:
        require_application_transition(ApplicationBuildState(record.state), target)
        record.state = target.value

    def _fail_build(self, build_id: str, error: Exception) -> None:
        with transaction(self.sessions) as session:
            record = session.get(HwpxAssessmentAssemblyBuildRecord, build_id)
            if record is None or record.state in {"SUCCEEDED", "FAILED"}:
                return
            self._transition(record, ApplicationBuildState.FAILED)
            record.validation_state = "FAIL"
            record.failure_code = (
                error.code.value
                if isinstance(error, HwpxManagerError)
                else HwpxManagerErrorCode.HWPX_BUILDER_FAILED.value
            )
            record.failure_detail_sanitized = (
                "Assessment HWPX build failed at a validated manager boundary"
            )
            record.completed_at = datetime.now(UTC)
            record.resource_version += 1
