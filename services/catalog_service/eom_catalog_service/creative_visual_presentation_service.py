"""Resolve the approved original-image rendering without mutating Item/Graph history."""

from __future__ import annotations

import json
from typing import Protocol

from eom_catalog_contracts.assessment_item import (
    AssessmentItemContent,
    AssessmentItemContentContract,
)
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_ARTIFACT_TYPE,
    VISUAL_PRESENTATION_CONTENT_MEMBER,
    VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
    VISUAL_PRESENTATION_MEMBER,
    VISUAL_PRESENTATION_SCHEMA_REF,
    CreativeVisualPresentationManifest,
    ItemVisualPresentation,
    visual_presentation_key,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select

from eom_catalog_service.item_content_contract import read_item_content
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import resolve_pinned_artifact_member
from eom_catalog_service.settings import CatalogSettings


class CanonicalItemContentReader(Protocol):
    def load_item_content(self, revision_id: str) -> AssessmentItemContentContract: ...


class CreativeVisualPresentationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CreativeVisualPresentationService:
    """One indexed publication lookup per Item, no lock files or persistent read cache."""

    def __init__(
        self, engine: Engine, *, source: CanonicalItemContentReader, settings: CatalogSettings
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.source = source
        self.settings = settings

    def read(self, revision_id: str) -> ItemVisualPresentation:
        content = self.source.load_item_content(revision_id)
        with self.sessions() as session:
            revision = session.get(ItemRevisionRecord, revision_id)
            item = None if revision is None else session.get(ItemRecord, revision.item_id)
            if (
                revision is None
                or item is None
                or item.lifecycle_state != "ACTIVE"
                or not (
                    revision.revision_state == "APPROVED"
                    or (
                        revision.revision_state == "IN_REVIEW"
                        and revision.workflow_definition_version == "1.16.0"
                    )
                )
            ):
                raise CreativeVisualPresentationError("ITEM_VISUAL_PRESENTATION_SOURCE_UNAVAILABLE")
            component = session.scalar(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision_id,
                    ItemComponentRecord.component_type == "ITEM_CONTENT",
                    ItemComponentRecord.ordinal == 0,
                )
            )
            if component is None:
                raise CreativeVisualPresentationError("ITEM_VISUAL_PRESENTATION_SOURCE_UNAVAILABLE")
            source = ArtifactMemberPointer(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path=component.logical_name,
                schema_ref=component.schema_ref,
                media_type=component.media_type,
                sha256=component.sha256,
            )
            if revision.metadata_json.get("source_kind") != "CREATIVE" or not isinstance(
                content, AssessmentItemContent
            ):
                return ItemVisualPresentation(
                    item_id=revision.item_id,
                    item_revision_id=revision_id,
                    source_content=source,
                    display_content=source,
                    content=content,
                )
            # The versioned key selects exactly one admitted rendering for this
            # immutable source. An incomplete/conflicting job is not "missing".
            job = session.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key == visual_presentation_key(revision_id),
                )
            )
            if job is None:
                return ItemVisualPresentation(
                    item_id=revision.item_id,
                    item_revision_id=revision_id,
                    source_content=source,
                    display_content=source,
                    content=content,
                )
            artifact = session.get(ArtifactRecord, job.logical_artifact_id)
            published = session.get(ArtifactRevisionRecord, job.revision_id)
            if (
                job.status != "SUCCEEDED"
                or job.protocol_version != "control-file-set/1.0"
                or job.task_type != VISUAL_PRESENTATION_ARTIFACT_TYPE
                or job.worker_slot_id is not None
                or artifact is None
                or not artifact.approved
                or artifact.artifact_type != VISUAL_PRESENTATION_ARTIFACT_TYPE
                or published is None
                or not published.approved
                or published.logical_artifact_id != job.logical_artifact_id
                or published.job_id != job.job_id
                or published.manifest.get("primary_file") != VISUAL_PRESENTATION_CONTENT_MEMBER
            ):
                raise CreativeVisualPresentationError(
                    "ITEM_VISUAL_PRESENTATION_PUBLICATION_INVALID"
                )
            entries = published.manifest.get("files")
            if not isinstance(entries, list):
                raise CreativeVisualPresentationError(
                    "ITEM_VISUAL_PRESENTATION_PUBLICATION_INVALID"
                )
            manifests = [
                v
                for v in entries
                if isinstance(v, dict) and v.get("file_name") == VISUAL_PRESENTATION_MEMBER
            ]
            if len(manifests) != 1:
                raise CreativeVisualPresentationError(
                    "ITEM_VISUAL_PRESENTATION_PUBLICATION_INVALID"
                )
            recovery_pointer = ArtifactMemberPointer(
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                member_path=VISUAL_PRESENTATION_MEMBER,
                sha256=manifests[0]["sha256"],
                schema_ref=VISUAL_PRESENTATION_SCHEMA_REF,
                media_type="application/json",
            )
            recovery_raw = resolve_pinned_artifact_member(
                session,
                self.settings,
                **recovery_pointer.model_dump(),
                expected_artifact_types={VISUAL_PRESENTATION_ARTIFACT_TYPE},
                expected_primary_file=VISUAL_PRESENTATION_CONTENT_MEMBER,
                max_bytes=256 * 1024,
            ).payload
            recovered_value = json.loads(recovery_raw)
            validate_contract("creative-visual-presentation-v1", recovered_value)
            manifest = CreativeVisualPresentationManifest.model_validate(recovered_value)
            report = session.scalar(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision_id,
                    ItemComponentRecord.component_type == "REVIEW_REPORT",
                    ItemComponentRecord.ordinal == 0,
                )
            )
            if (
                manifest.item_id != revision.item_id
                or manifest.item_revision_id != revision_id
                or manifest.canonical_content != source
                or manifest.source_id != revision.metadata_json.get("source_id")
                or manifest.source_revision_id != revision.metadata_json.get("source_revision_id")
                or report is None
                or manifest.role_result
                != ArtifactMemberPointer(
                    artifact_id=report.artifact_id,
                    artifact_revision_id=report.artifact_revision_id,
                    member_path=report.logical_name,
                    sha256=report.sha256,
                    schema_ref=report.schema_ref,
                    media_type=report.media_type,
                )
            ):
                raise CreativeVisualPresentationError("ITEM_VISUAL_PRESENTATION_SOURCE_MISMATCH")
            display_pointer = ArtifactMemberPointer(
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                member_path=VISUAL_PRESENTATION_CONTENT_MEMBER,
                sha256=manifest.content_sha256,
                schema_ref=VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
                media_type="application/json",
            )
            raw = resolve_pinned_artifact_member(
                session,
                self.settings,
                **display_pointer.model_dump(),
                expected_artifact_types={VISUAL_PRESENTATION_ARTIFACT_TYPE},
                expected_primary_file=VISUAL_PRESENTATION_CONTENT_MEMBER,
                max_bytes=1024 * 1024,
            ).payload
            displayed = read_item_content(source.schema_ref, json.loads(raw))
            expected = derive_creative_visual_content(
                content,
                manifest,
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
            )
            if (
                displayed != expected
                or content_sha256(expected.model_dump(mode="json")) != manifest.content_sha256
            ):
                raise CreativeVisualPresentationError("ITEM_VISUAL_PRESENTATION_CONTENT_MISMATCH")
            return ItemVisualPresentation(
                item_id=revision.item_id,
                item_revision_id=revision_id,
                source_content=source,
                display_content=display_pointer,
                recovery_manifest=recovery_pointer,
                content=displayed,
            )
