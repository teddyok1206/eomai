"""Bounded caller-root provenance metadata preparation, never source authorization."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_analysis_sources import MAX_DOCUMENT_JSON_BYTES
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.past_exam_source_provenance import (
    PastExamProvenanceMember,
    PastExamSourceResolutionCache,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
    artifact_identity_hints,
)


def prefetch_past_exam_artifact_closure(
    session: Session,
    revisions: tuple[ItemRevisionRecord, ...],
    reader: PinnedArtifactReadContext,
) -> None:
    """Prepare exact hints before the existing resolver checks each source again.

    Current source/IAM authorization belongs to the caller, not this adapter.
    Malformed/missing Item provenance still fails the canonical source resolver;
    no metadata hint returned here can waive that validation.
    """
    reader.require_session(session)
    acceptance_ids = tuple(
        sorted(
            {
                value
                for revision in revisions
                if revision.metadata_json.get("source_kind") == "PAST_EXAM"
                and isinstance(value := revision.metadata_json.get("extraction_acceptance_id"), str)
            }
        )
    )
    if not acceptance_ids:
        return
    maximum = reader.MAX_REVISIONS
    if len(revisions) > 1024 or len(acceptance_ids) > 1024:
        raise PinnedArtifactResolutionError("past-exam metadata preparation budget exceeded")
    acceptances = tuple(
        session.scalars(
            select(LegacyItemExtractionAcceptanceRecord)
            .where(LegacyItemExtractionAcceptanceRecord.acceptance_id.in_(acceptance_ids))
            .execution_options(populate_existing=True)
        )
    )
    units = tuple(
        session.scalars(
            select(LegacyItemExtractionBatchWorkUnitRecord)
            .where(
                LegacyItemExtractionBatchWorkUnitRecord.acceptance_id.in_(acceptance_ids),
                LegacyItemExtractionBatchWorkUnitRecord.state == "ACCEPTED",
            )
            .order_by(LegacyItemExtractionBatchWorkUnitRecord.work_unit_id)
            .limit(maximum + 1)
        )
    )
    if len(units) > maximum:
        raise PinnedArtifactResolutionError("past-exam metadata preparation budget exceeded")
    batch_ids = tuple(sorted({unit.extraction_batch_id for unit in units}))
    batches = tuple(
        session.scalars(
            select(LegacyItemExtractionBatchRecord)
            .where(LegacyItemExtractionBatchRecord.extraction_batch_id.in_(batch_ids))
            .execution_options(populate_existing=True)
        )
    )
    batch_members = {
        row.extraction_batch_id: PastExamProvenanceMember(
            row.manifest_artifact_id,
            row.manifest_artifact_revision_id,
            row.manifest_artifact_member_path,
            row.manifest_artifact_sha256,
            row.manifest_artifact_media_type,
            row.manifest_artifact_schema_ref,
            MAX_DOCUMENT_JSON_BYTES,
        )
        for row in batches
    }
    accepted_members = tuple(
        (
            PastExamProvenanceMember(
                row.acceptance_artifact_id,
                row.acceptance_artifact_revision_id,
                row.acceptance_artifact_member_path,
                row.acceptance_artifact_sha256,
                row.acceptance_artifact_media_type,
                row.acceptance_artifact_schema_ref,
                MAX_DOCUMENT_JSON_BYTES,
            ),
            PastExamProvenanceMember(
                row.result_artifact_id,
                row.result_artifact_revision_id,
                row.result_artifact_member_path,
                row.result_artifact_sha256,
                row.result_artifact_media_type,
                row.result_artifact_schema_ref,
                MAX_DOCUMENT_JSON_BYTES,
            ),
        )
        for row in acceptances
    )
    members = (*batch_members.values(), *(member for pair in accepted_members for member in pair))
    reader.prefetch(tuple(sorted({(m.artifact_id, m.artifact_revision_id) for m in members})))
    cache = PastExamSourceResolutionCache()
    hints: set[tuple[str, str]] = set()
    layout_ids: set[str] = set()
    for unit in units:
        member = batch_members.get(unit.extraction_batch_id)
        if member is None:
            raise PinnedArtifactResolutionError("past-exam batch metadata is missing")
        decoded = cache.batch(reader, member)
        selected = decoded.work_units_by_id.get(unit.work_unit_id, ())
        if len(selected) != 1:
            raise PinnedArtifactResolutionError("past-exam batch work unit is ambiguous")
        request = selected[0].request
        hints.update(artifact_identity_hints(request.model_dump(mode="json")))
        layout_ids.add(request.layout_observation.assessment_layout_observation_id)
    for acceptance_member, result_member in accepted_members:
        hints.update(
            artifact_identity_hints(
                cache.acceptance(reader, acceptance_member).value.model_dump(mode="json")
            )
        )
        hints.update(
            artifact_identity_hints(
                cache.result(reader, result_member).value.model_dump(mode="json")
            )
        )
    layouts = tuple(
        session.scalars(
            select(AssessmentLayoutObservationRecord)
            .where(
                AssessmentLayoutObservationRecord.assessment_layout_observation_id.in_(
                    tuple(sorted(layout_ids))
                )
            )
            .execution_options(populate_existing=True)
        )
    )
    layout_members = tuple(
        PastExamProvenanceMember(
            row.artifact_id,
            row.artifact_revision_id,
            row.artifact_member_path,
            row.artifact_sha256,
            row.artifact_media_type,
            row.artifact_schema_ref,
            MAX_DOCUMENT_JSON_BYTES,
        )
        for row in layouts
    )
    hints.update((m.artifact_id, m.artifact_revision_id) for m in layout_members)
    reader.prefetch(tuple(sorted(hints)))
    page_hints: set[tuple[str, str]] = set()
    for member in layout_members:
        page_hints.update(
            artifact_identity_hints(cache.layout(reader, member).value.model_dump(mode="json"))
        )
    reader.prefetch(tuple(sorted(page_hints)))
