"""Resolve exact approved source pointers for knowledge-analysis requests."""

from __future__ import annotations

from pathlib import PurePosixPath

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ApprovedItemKnowledgeSourceV2,
    ContentIntakeKnowledgeSourceV2,
    KnowledgeAnalysisSourceArtifactMemberV2,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    ItemComponentRecord,
    ItemRevisionRecord,
)

MAX_SOURCE_BYTES = 100 * 1024 * 1024
CONTENT_INTAKE_ELIGIBLE_STATES = frozenset(
    {
        "HASHED",
        "ANALYSIS_PENDING",
        "ANALYSIS_ATTACHED",
        "VALIDATING",
        "NEEDS_DECISION",
        "ACCEPTED",
        "IMPORTED",
    }
)
ANALYSIS_MEDIA_SUFFIXES = {
    "application/json": ".json",
    "application/pdf": ".pdf",
    "image/png": ".png",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


class KnowledgeAnalysisSourceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_content_intake_source(
    session: Session,
    *,
    intake_batch_id: str,
    source_file_id: str,
    source_class: str,
) -> ContentIntakeKnowledgeSourceV2:
    batch = session.get(ContentIntakeBatchRecord, intake_batch_id)
    source = session.get(ContentIntakeSourceFileRecord, source_file_id)
    if batch is None or source is None or source.intake_batch_id != intake_batch_id:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "content intake source does not exist"
        )
    if batch.state not in CONTENT_INTAKE_ELIGIBLE_STATES:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "content intake source is not eligible for analysis",
        )
    _validate_media_and_size(source.media_type, source.size_bytes)
    logical, revision, member = _resolve_artifact_member(
        session,
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        member_path=source.relative_path,
        sha256=source.sha256,
        size_bytes=source.size_bytes,
        media_type=source.media_type,
        schema_ref=None,
    )
    del logical, revision
    suffix = ANALYSIS_MEDIA_SUFFIXES[source.media_type]
    logical_name = f"source-{source.sha256.removeprefix('sha256:')[:16]}{suffix}"
    raw_schema_ref = member.get("schema_ref")
    schema_ref = raw_schema_ref if isinstance(raw_schema_ref, str) else None
    try:
        return ContentIntakeKnowledgeSourceV2(
            source_class=source_class,  # type: ignore[arg-type]
            intake_batch_id=intake_batch_id,
            source_file_id=source_file_id,
            artifact_member=KnowledgeAnalysisSourceArtifactMemberV2(
                artifact_id=source.artifact_id,
                artifact_revision_id=source.artifact_revision_id,
                member_path=source.relative_path,
                materialized_path=f"source/{logical_name}",
                sha256=source.sha256,
                bytes=source.size_bytes,
                schema_ref=schema_ref,
                media_type=source.media_type,
                logical_name=logical_name,
            ),
        )
    except ValueError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "content intake source contract is invalid"
        ) from exc


def resolve_approved_item_source(
    session: Session,
    *,
    item_revision_id: str,
    source_class: str,
) -> ApprovedItemKnowledgeSourceV2:
    revision = session.get(ItemRevisionRecord, item_revision_id)
    if revision is None:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "Item Revision source does not exist"
        )
    if revision.revision_state != "APPROVED":
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Item Revision source is not approved",
        )
    components = tuple(
        session.scalars(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == item_revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
                ItemComponentRecord.ordinal == 0,
            )
        )
    )
    if len(components) != 1:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Item Revision must have one canonical content component",
        )
    component = components[0]
    if (
        not component.required
        or component.media_type != ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE
        or component.schema_ref
        not in {
            ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
            "eom://schemas/item-registry/assessment-item-content-v1",
        }
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Item Revision content component is incompatible",
        )
    logical, artifact_revision, member = _resolve_artifact_member(
        session,
        artifact_id=component.artifact_id,
        artifact_revision_id=component.artifact_revision_id,
        member_path=component.logical_name,
        sha256=component.sha256,
        size_bytes=None,
        media_type=component.media_type,
        schema_ref=component.schema_ref,
    )
    del logical
    size_bytes = member.get("bytes")
    if not isinstance(size_bytes, int):
        size_bytes = artifact_revision.content_bytes
    _validate_media_and_size(component.media_type, size_bytes)
    try:
        return ApprovedItemKnowledgeSourceV2(
            source_class=source_class,  # type: ignore[arg-type]
            item_id=revision.item_id,
            item_revision_id=item_revision_id,
            artifact_member=KnowledgeAnalysisSourceArtifactMemberV2(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path=component.logical_name,
                materialized_path="source/item-content.json",
                sha256=component.sha256,
                bytes=size_bytes,
                schema_ref=component.schema_ref,
                media_type=component.media_type,
                logical_name="item-content.json",
            ),
        )
    except ValueError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "Item Revision source contract is invalid"
        ) from exc


def _validate_media_and_size(media_type: str, size_bytes: int) -> None:
    if media_type not in ANALYSIS_MEDIA_SUFFIXES or not 0 < size_bytes <= MAX_SOURCE_BYTES:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "source media type or byte size is outside the analysis contract",
        )


def _resolve_artifact_member(
    session: Session,
    *,
    artifact_id: str,
    artifact_revision_id: str,
    member_path: str,
    sha256: str,
    size_bytes: int | None,
    media_type: str,
    schema_ref: str | None,
) -> tuple[ArtifactRecord, ArtifactRevisionRecord, dict[str, object]]:
    path = PurePosixPath(member_path)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member path is unsafe"
        )
    logical = session.get(ArtifactRecord, artifact_id)
    revision = session.get(ArtifactRevisionRecord, artifact_revision_id)
    if logical is None or revision is None:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "source Artifact pointer does not resolve"
        )
    if not logical.approved or not revision.approved or revision.logical_artifact_id != artifact_id:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "source Artifact Revision is stale or unapproved"
        )
    files = revision.manifest.get("files")
    matches = (
        [
            value
            for value in files
            if isinstance(value, dict) and value.get("file_name") == member_path
        ]
        if isinstance(files, list)
        else []
    )
    if len(matches) != 1:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member is absent"
        )
    member = matches[0]
    if (
        member.get("sha256") != sha256
        or member.get("media_type") != media_type
        or (size_bytes is not None and member.get("bytes") != size_bytes)
        or (schema_ref is not None and member.get("schema_ref") != schema_ref)
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH",
            "source Artifact member metadata does not match its pinned pointer",
        )
    return logical, revision, member
