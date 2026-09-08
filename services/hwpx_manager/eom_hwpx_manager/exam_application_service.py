"""FIFO application use case for released Assessment Assembly HWPX builds."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from eom_catalog_contracts import MockExamAssemblyManifestContract
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
from eom_hwpx_manager.assembly_render_projection import (
    AssemblyRenderPlacement,
    project_assembly_for_render,
)
from eom_hwpx_manager.content_team_exam_service import (
    EXAM_RENDERER,
    ContentTeamExamBuildReceipt,
    ContentTeamExamHwpxService,
    ContentTeamExamItemPointer,
    exam_renderer_version,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.models import HwpxAssessmentAssemblyBuildRecord


class ExamRecoveryState(StrEnum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    TERMINALIZED = "TERMINALIZED"


@dataclass(frozen=True)
class ExamRecoveryResult:
    state: ExamRecoveryState
    record: HwpxAssessmentAssemblyBuildRecord | None = None


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
        projection = project_assembly_for_render(manifest)
        self._resolve_items(manifest)
        handoff = self.renderer.snapshot()
        item_set_sha256 = projection.item_set_sha256()
        renderer_version = exam_renderer_version(manifest)
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
                assessment_assembly_id=projection.assessment_assembly_id,
                assessment_assembly_revision_id=projection.assessment_assembly_revision_id,
                assembly_manifest_sha256=projection.manifest_sha256,
                policy_revision_id=projection.policy_revision_id,
                policy_sha256=projection.policy_sha256,
                graph_snapshot_revision_id=projection.graph_snapshot_revision_id,
                graph_snapshot_sha256=projection.graph_snapshot_sha256,
                item_set_sha256=item_set_sha256,
                renderer=EXAM_RENDERER,
                renderer_version=renderer_version,
                request_sha256=request_sha256,
                idempotency_key=idempotency_key,
                created_by_operator_id=operator_id,
                state=ApplicationBuildState.REQUESTED.value,
                validation_state="PENDING",
                item_count=len(projection.placements),
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

    def recover_interrupted(self) -> ExamRecoveryResult:
        """Terminalize one orphaned build only after its fixed renderer is absent.

        The application runner invokes this only during its startup recovery phase. A nonterminal
        row therefore belongs to an earlier manager process. An independently running fixed unit is
        allowed to finish, but it is never replayed automatically.
        """

        with self.sessions() as session:
            record = session.scalar(
                select(HwpxAssessmentAssemblyBuildRecord)
                .where(
                    HwpxAssessmentAssemblyBuildRecord.state.in_(
                        (
                            ApplicationBuildState.RUNNING.value,
                            ApplicationBuildState.VALIDATING.value,
                        )
                    )
                )
                .order_by(
                    HwpxAssessmentAssemblyBuildRecord.started_at,
                    HwpxAssessmentAssemblyBuildRecord.build_id,
                )
                .limit(1)
            )
            if record is None:
                return ExamRecoveryResult(ExamRecoveryState.NONE)
            session.expunge(record)
        if self.renderer.build_may_be_active(record.build_id):
            return ExamRecoveryResult(ExamRecoveryState.ACTIVE, record)
        try:
            receipt = self.renderer.recover_interrupted_result(
                build_id=record.build_id,
                idempotency_key=record.idempotency_key,
            )
        except Exception as exc:
            self._fail_build(record.build_id, exc)
            return ExamRecoveryResult(
                ExamRecoveryState.TERMINALIZED,
                self.get_build(record.build_id),
            )
        with transaction(self.sessions) as session:
            current = session.execute(
                select(HwpxAssessmentAssemblyBuildRecord)
                .where(HwpxAssessmentAssemblyBuildRecord.build_id == record.build_id)
                .with_for_update()
            ).scalar_one_or_none()
            if current is None or current.state not in {
                ApplicationBuildState.RUNNING.value,
                ApplicationBuildState.VALIDATING.value,
            }:
                return ExamRecoveryResult(ExamRecoveryState.NONE)
            if receipt is None:
                self._terminalize_interrupted(current, datetime.now(UTC))
            else:
                self._complete_build(current, receipt, datetime.now(UTC))
            session.flush()
            session.expunge(current)
            return ExamRecoveryResult(ExamRecoveryState.TERMINALIZED, current)

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
            projection = project_assembly_for_render(manifest)
            if (
                projection.assessment_assembly_id != record.assessment_assembly_id
                or projection.manifest_sha256 != record.assembly_manifest_sha256
                or projection.policy_revision_id != record.policy_revision_id
                or projection.policy_sha256 != record.policy_sha256
                or projection.graph_snapshot_revision_id != record.graph_snapshot_revision_id
                or projection.graph_snapshot_sha256 != record.graph_snapshot_sha256
                or projection.item_set_sha256() != record.item_set_sha256
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
                current = session.execute(
                    select(HwpxAssessmentAssemblyBuildRecord)
                    .where(HwpxAssessmentAssemblyBuildRecord.build_id == record.build_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if current is None:
                    raise RuntimeError("claimed assessment HWPX build disappeared")
                self._complete_build(current, receipt, datetime.now(UTC))
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

    def _manifest(self, revision_id: str) -> MockExamAssemblyManifestContract:
        with self.sessions() as session:
            manifest = MockExamAssemblyService.inspect(session, revision_id)
        if manifest is None or manifest.revision_state != "RELEASED":
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "released Assessment Assembly revision is not HWPX-eligible",
            )
        return manifest

    def _resolve_items(
        self, manifest: MockExamAssemblyManifestContract
    ) -> tuple[ContentTeamExamItemPointer, ...]:
        projection = project_assembly_for_render(manifest)
        revision_ids = tuple(placement.item_revision_id for placement in projection.placements)
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
        for placement in projection.placements:
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
            source = self._content_source(placement, component, metadata)
            resolved.append(
                ContentTeamExamItemPointer(
                    position=placement.position,
                    display_number=placement.display_number,
                    points_milli=placement.points_milli,
                    placement_id=placement.placement_id,
                    item_id=placement.item_id,
                    item_revision_id=placement.item_revision_id,
                    item_manifest_sha256=placement.item_manifest_sha256,
                    source=source,
                    images=tuple(
                        ContentTeamImageSource.model_validate(value)
                        for value in HwpxApplicationService._content_team_image_sources(revision)
                    ),
                )
            )
        return tuple(resolved)

    @staticmethod
    def _content_source(
        placement: AssemblyRenderPlacement,
        component: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ContentTeamItemSource:
        pointer = placement.content
        if pointer is None:
            return ContentTeamItemSource(
                artifact_id=str(component["artifact_id"]),
                artifact_revision_id=str(component["artifact_revision_id"]),
                json_sha256=str(component["sha256"]),
                markdown_sha256=str(metadata["editorial_markdown_sha256"]),
            )
        if (
            component.get("item_component_id") != pointer.item_component_id
            or component.get("logical_name") != pointer.member_path
            or component.get("artifact_id") != pointer.artifact_id
            or component.get("artifact_revision_id") != pointer.artifact_revision_id
            or component.get("sha256") != pointer.sha256
            or component.get("media_type") != pointer.media_type
            or component.get("required") is not True
            or metadata.get("editorial_markdown_member") != pointer.editorial_markdown_member
            or metadata.get("editorial_markdown_sha256") != pointer.editorial_markdown_sha256
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "planned Assembly content pointer differs from its Item Revision",
            )
        return ContentTeamItemSource(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            json_sha256=pointer.sha256,
            markdown_sha256=pointer.editorial_markdown_sha256,
        )

    @staticmethod
    def _item_set_sha256(manifest: MockExamAssemblyManifestContract) -> str:
        return project_assembly_for_render(manifest).item_set_sha256()

    @staticmethod
    def _request_sha256(
        manifest: MockExamAssemblyManifestContract,
        handoff: ContentTeamHandoffSnapshot,
    ) -> str:
        projection = project_assembly_for_render(manifest)
        return content_sha256(
            {
                **projection.request_identity(),
                "renderer": EXAM_RENDERER,
                "renderer_version": exam_renderer_version(manifest),
                "handoff": handoff.model_dump(mode="json"),
            }
        )

    @staticmethod
    def _transition(
        record: HwpxAssessmentAssemblyBuildRecord, target: ApplicationBuildState
    ) -> None:
        require_application_transition(ApplicationBuildState(record.state), target)
        record.state = target.value

    @classmethod
    def _terminalize_interrupted(
        cls,
        record: HwpxAssessmentAssemblyBuildRecord,
        completed_at: datetime,
    ) -> None:
        cls._transition(record, ApplicationBuildState.FAILED)
        record.validation_state = "FAIL"
        record.failure_code = HwpxManagerErrorCode.HWPX_BUILD_INTERRUPTED.value
        record.failure_detail_sanitized = (
            "Assessment HWPX build was interrupted before terminal acceptance"
        )
        record.completed_at = completed_at
        record.resource_version += 1

    @classmethod
    def _complete_build(
        cls,
        record: HwpxAssessmentAssemblyBuildRecord,
        receipt: ContentTeamExamBuildReceipt,
        completed_at: datetime,
    ) -> None:
        if (
            receipt.build_id != record.build_id
            or receipt.renderer_version != record.renderer_version
            or receipt.assessment_assembly_revision_id != record.assessment_assembly_revision_id
            or receipt.assembly_manifest_sha256 != record.assembly_manifest_sha256
            or receipt.item_set_sha256 != record.item_set_sha256
            or receipt.item_count != record.item_count
            or receipt.section_count != record.item_count
        ):
            raise RuntimeError("assessment HWPX receipt differs from its admitted Item set")
        if record.state == ApplicationBuildState.RUNNING.value:
            cls._transition(record, ApplicationBuildState.VALIDATING)
        elif record.state != ApplicationBuildState.VALIDATING.value:
            raise RuntimeError("assessment HWPX build cannot accept a terminal result")
        record.platform_job_id = receipt.job_id
        record.item_count = receipt.item_count
        record.section_count = receipt.section_count
        record.native_equation_count = receipt.native_equation_count
        record.native_table_count = receipt.native_table_count
        record.visual_count = receipt.visual_count
        record.output_artifact_id = receipt.artifact_id
        record.output_artifact_revision_id = receipt.artifact_revision_id
        record.output_sha256 = receipt.output_sha256
        record.output_filename = f"eom-mock-exam-{record.assessment_assembly_revision_id}.hwpx"
        record.validation_state = "PASS"
        cls._transition(record, ApplicationBuildState.SUCCEEDED)
        record.completed_at = completed_at
        record.resource_version += 1

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
