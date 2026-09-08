"""Resolve exact approved source pointers for knowledge-analysis requests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal, NoReturn, cast

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    AssessmentArtifactMemberPointer,
    AssessmentLayoutObservation,
    ContentIntakeKnowledgeSourceV2,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationalDocumentRightsAttestation,
    KnowledgeAnalysisDocumentDependencyV3,
    KnowledgeAnalysisDocumentMaterializationMemberV3,
    KnowledgeAnalysisDocumentMaterializationMemberV4,
    KnowledgeAnalysisOriginalSourceMemberV3,
    KnowledgeAnalysisSourceArtifactMemberV2,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionResult,
    TextbookAnalysisBundleManifest,
    TextbookAnalysisBundleManifestV2,
    TextbookPageAnalysisV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    EducationalDocumentRecord,
    EducationalDocumentRevisionRecord,
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
DOCUMENT_MARKDOWN_MEDIA_TYPE: Literal["text/markdown; charset=utf-8"] = (
    "text/markdown; charset=utf-8"
)
DOCUMENT_MARKDOWN_SCHEMA_REF: Literal[
    "eom://schemas/educational-document/extracted-markdown/1.0"
] = "eom://schemas/educational-document/extracted-markdown/1.0"
DOCUMENT_BUNDLE_SCHEMA_REF: Literal[
    "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
] = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
DOCUMENT_BUNDLE_SCHEMA_REF_V2: Literal[
    "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
] = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
DOCUMENT_RIGHTS_SCHEMA_REF = "eom://schemas/educational-document/rights-attestation/1.0"
DOCUMENT_PDF_SCHEMA_REF: Literal["eom://schemas/educational-document/pdf-source/1.0"] = (
    "eom://schemas/educational-document/pdf-source/1.0"
)
DOCUMENT_PAGE_IMAGE_MEDIA_TYPE: Literal["image/png"] = "image/png"
DOCUMENT_PAGE_IMAGE_SCHEMA_REF: Literal["eom://schemas/educational-document/page-image/1.0"] = (
    "eom://schemas/educational-document/page-image/1.0"
)
MAX_DOCUMENT_MATERIALIZATION_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_MULTIMODAL_MATERIALIZATION_BYTES = 128 * 1024 * 1024
MAX_DOCUMENT_SELECTION_PAGES = 32
MAX_DOCUMENT_JSON_BYTES = 8 * 1024 * 1024


class KnowledgeAnalysisSourceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _ArtifactMemberIndex:
    logical: ArtifactRecord
    revision: ArtifactRevisionRecord
    members_by_path: dict[str, dict[str, object]]


@dataclass
class EducationalDocumentSourceResolutionCache:
    """Transaction-scoped cache for immutable document dependencies during batch creation."""

    artifact_indexes: dict[tuple[str, str], _ArtifactMemberIndex] = field(default_factory=dict)
    dependency_documents: dict[
        tuple[str, str, str, str, str, str, str],
        tuple[
            TextbookAnalysisBundleManifest | TextbookAnalysisBundleManifestV2,
            EducationalDocumentRightsAttestation,
        ],
    ] = field(default_factory=dict)


def resolve_content_intake_source(
    session: Session,
    *,
    intake_batch_id: str,
    source_file_id: str,
    source_class: Literal["CURRICULUM", "TEXTBOOK", "PAST_EXAM", "INTERNAL_GUIDE"],
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
            source_class=source_class,
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


def _resolve_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactService | None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
    eligible_revision_states: frozenset[str],
) -> ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3:
    revision = session.get(ItemRevisionRecord, item_revision_id)
    if revision is None:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "Item Revision source does not exist"
        )
    if revision.revision_state not in eligible_revision_states:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Item Revision source is not approved",
        )
    if revision.revision_state == "SUPERSEDED" and (
        revision.approved_at is None
        or revision.approved_by is None
        or revision.superseded_at is None
        or revision.superseded_by_revision_id is None
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "superseded Item Revision has incomplete approval history",
        )
    if revision.revision_state == "RETIRED" and (
        revision.approved_at is None or revision.approved_by is None
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "retired Item Revision has incomplete approval history",
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
            ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
            "eom://schemas/item-registry/assessment-item-content-v1",
            "eom://schemas/item-registry/assessment-item-content-v2",
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
    artifact_member = KnowledgeAnalysisSourceArtifactMemberV2(
        artifact_id=component.artifact_id,
        artifact_revision_id=component.artifact_revision_id,
        member_path=component.logical_name,
        materialized_path="source/item-content.json",
        sha256=component.sha256,
        bytes=size_bytes,
        schema_ref=component.schema_ref,
        media_type=component.media_type,
        logical_name="item-content.json",
    )
    if source_class == "PAST_EXAM":
        if artifacts is None:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
                "past-exam Item analysis requires immutable extraction evidence",
            )
        return _resolve_past_exam_item_source(
            session,
            artifacts=artifacts,
            revision=revision,
            artifact_member=artifact_member,
        )
    try:
        return ApprovedItemKnowledgeSourceV2(
            source_class=source_class,
            item_id=revision.item_id,
            item_revision_id=item_revision_id,
            artifact_member=artifact_member,
        )
    except ValueError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "Item Revision source contract is invalid"
        ) from exc


def _resolve_past_exam_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactService,
    revision: ItemRevisionRecord,
    artifact_member: KnowledgeAnalysisSourceArtifactMemberV2,
) -> ApprovedPastExamItemKnowledgeSourceV3:
    """Resolve one promoted Item back to its exact extraction request and PNG evidence."""

    metadata = revision.metadata_json
    acceptance_id = metadata.get("extraction_acceptance_id")
    extraction_result_id = metadata.get("extraction_result_id")
    item_proposal_id = metadata.get("item_proposal_id")
    item_number = metadata.get("item_number")
    if (
        metadata.get("source_kind") != "PAST_EXAM"
        or not isinstance(acceptance_id, str)
        or not isinstance(extraction_result_id, str)
        or not isinstance(item_proposal_id, str)
        or not isinstance(item_number, int)
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "past-exam Item promotion provenance is incomplete",
        )
    acceptance_record = session.get(LegacyItemExtractionAcceptanceRecord, acceptance_id)
    decisions = tuple(
        session.scalars(
            select(LegacyItemExtractionDecisionRecord).where(
                LegacyItemExtractionDecisionRecord.acceptance_id == acceptance_id,
                LegacyItemExtractionDecisionRecord.item_proposal_id == item_proposal_id,
                LegacyItemExtractionDecisionRecord.item_number == item_number,
            )
        )
    )
    if (
        acceptance_record is None
        or acceptance_record.state not in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}
        or acceptance_record.coverage_state != "COMPLETE"
        or acceptance_record.extraction_result_id != extraction_result_id
        or len(decisions) != 1
        or decisions[0].decision not in {"ACCEPT", "CORRECT_AND_ACCEPT"}
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "past-exam Item acceptance or decision does not resolve",
        )
    work_units = tuple(
        session.scalars(
            select(LegacyItemExtractionBatchWorkUnitRecord)
            .where(
                LegacyItemExtractionBatchWorkUnitRecord.acceptance_id == acceptance_id,
                LegacyItemExtractionBatchWorkUnitRecord.extraction_result_id
                == extraction_result_id,
                LegacyItemExtractionBatchWorkUnitRecord.state == "ACCEPTED",
            )
            .order_by(
                LegacyItemExtractionBatchWorkUnitRecord.created_at,
                LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                LegacyItemExtractionBatchWorkUnitRecord.work_unit_id,
            )
        )
    )
    lineage = {
        (
            unit.extraction_request_id,
            unit.request_sha256,
            unit.assessment_source_bundle_id,
            unit.assessment_source_bundle_revision_id,
            unit.bundle_manifest_sha256,
            unit.result_sha256,
            unit.acceptance_sha256,
        )
        for unit in work_units
    }
    if (
        not work_units
        or len(lineage) != 1
        or next(iter(lineage))[5:]  # result and acceptance self hashes
        != (acceptance_record.result_sha256, acceptance_record.acceptance_sha256)
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "past-exam Item extraction lineage is ambiguous",
        )
    work_unit = work_units[0]
    batch = session.get(LegacyItemExtractionBatchRecord, work_unit.extraction_batch_id)
    bundle = session.get(
        AssessmentSourceBundleRevisionRecord,
        work_unit.assessment_source_bundle_revision_id,
    )
    if (
        batch is None
        or bundle is None
        or batch.manifest_sha256 == ""
        or bundle.assessment_source_bundle_id != work_unit.assessment_source_bundle_id
        or bundle.bundle_manifest_sha256 != work_unit.bundle_manifest_sha256
        or bundle.state not in {"REVIEWED", "SUPERSEDED"}
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "past-exam Item batch or bundle revision is stale",
        )

    try:
        manifest_value = _read_json_member(
            artifacts,
            artifact_id=batch.manifest_artifact_id,
            revision_id=batch.manifest_artifact_revision_id,
            member_path=batch.manifest_artifact_member_path,
            sha256=batch.manifest_artifact_sha256,
            media_type=batch.manifest_artifact_media_type,
            schema_ref=batch.manifest_artifact_schema_ref,
        )
        validate_contract("legacy-item-extraction-batch-v2", manifest_value)
        batch_manifest = LegacyItemExtractionBatchManifestV2.model_validate(manifest_value)
        manifest_units = tuple(
            unit
            for unit in batch_manifest.work_units
            if unit.work_unit_id == work_unit.work_unit_id
        )
        if len(manifest_units) != 1:
            raise ValueError("work unit is absent from its immutable batch manifest")
        request = manifest_units[0].request

        acceptance_value = _read_json_member(
            artifacts,
            artifact_id=acceptance_record.acceptance_artifact_id,
            revision_id=acceptance_record.acceptance_artifact_revision_id,
            member_path=acceptance_record.acceptance_artifact_member_path,
            sha256=acceptance_record.acceptance_artifact_sha256,
            media_type=acceptance_record.acceptance_artifact_media_type,
            schema_ref=acceptance_record.acceptance_artifact_schema_ref,
        )
        validate_contract("legacy-item-extraction-acceptance", acceptance_value)
        acceptance = LegacyItemExtractionAcceptance.model_validate(acceptance_value)

        result_value = _read_json_member(
            artifacts,
            artifact_id=acceptance_record.result_artifact_id,
            revision_id=acceptance_record.result_artifact_revision_id,
            member_path=acceptance_record.result_artifact_member_path,
            sha256=acceptance_record.result_artifact_sha256,
            media_type=acceptance_record.result_artifact_media_type,
            schema_ref=acceptance_record.result_artifact_schema_ref,
        )
        validate_contract("legacy-item-extraction-result", result_value)
        result = LegacyItemExtractionResult.model_validate(result_value)

        layout_record = session.get(
            AssessmentLayoutObservationRecord,
            request.layout_observation.assessment_layout_observation_id,
        )
        if layout_record is None:
            raise ValueError("layout observation record is absent")
        layout_value = _read_json_member(
            artifacts,
            artifact_id=layout_record.artifact_id,
            revision_id=layout_record.artifact_revision_id,
            member_path=layout_record.artifact_member_path,
            sha256=layout_record.artifact_sha256,
            media_type=layout_record.artifact_media_type,
            schema_ref=layout_record.artifact_schema_ref,
        )
        validate_contract("assessment-layout-observation", layout_value)
        layout = AssessmentLayoutObservation.model_validate(layout_value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH",
            "past-exam Item extraction evidence bytes are invalid",
        ) from exc

    decision_models = tuple(
        value
        for value in acceptance.item_decisions
        if value.item_proposal_id == item_proposal_id and value.item_number == item_number
    )
    proposals = tuple(
        value
        for value in result.items
        if value.item_proposal_id == item_proposal_id and value.item_number == item_number
    )
    expected_result_pointer = AssessmentArtifactMemberPointer(
        artifact_id=acceptance_record.result_artifact_id,
        artifact_revision_id=acceptance_record.result_artifact_revision_id,
        member_path=acceptance_record.result_artifact_member_path,
        schema_ref=acceptance_record.result_artifact_schema_ref,
        media_type=acceptance_record.result_artifact_media_type,
        sha256=acceptance_record.result_artifact_sha256,
    )
    expected_layout_pointer = AssessmentArtifactMemberPointer(
        artifact_id=layout_record.artifact_id,
        artifact_revision_id=layout_record.artifact_revision_id,
        member_path=layout_record.artifact_member_path,
        schema_ref=layout_record.artifact_schema_ref,
        media_type=layout_record.artifact_media_type,
        sha256=layout_record.artifact_sha256,
    )
    if (
        batch_manifest.extraction_batch_id != batch.extraction_batch_id
        or batch_manifest.manifest_sha256 != batch.manifest_sha256
        or request.extraction_request_id != work_unit.extraction_request_id
        or request.request_sha256 != work_unit.request_sha256
        or request.bundle.assessment_source_bundle_id != bundle.assessment_source_bundle_id
        or request.bundle.assessment_source_bundle_revision_id
        != bundle.assessment_source_bundle_revision_id
        or request.bundle.bundle_manifest_sha256 != bundle.bundle_manifest_sha256
        or acceptance.acceptance_id != acceptance_record.acceptance_id
        or acceptance.acceptance_sha256 != acceptance_record.acceptance_sha256
        or acceptance.extraction_result.extraction_result_id != result.extraction_result_id
        or acceptance.extraction_result.result_sha256 != result.result_sha256
        or acceptance.extraction_result.artifact != expected_result_pointer
        or result.extraction_result_id != extraction_result_id
        or result.extraction_request_id != request.extraction_request_id
        or result.request_sha256 != request.request_sha256
        or result.result_sha256 != acceptance_record.result_sha256
        or len(decision_models) != 1
        or decision_models[0].decision not in {"ACCEPT", "CORRECT_AND_ACCEPT"}
        or decision_models[0].decision != decisions[0].decision
        or len(proposals) != 1
        or result.observed_page_input_ids
        != tuple(page.page_input_id for page in request.page_inputs)
        or layout.assessment_layout_observation_id
        != request.layout_observation.assessment_layout_observation_id
        or request.layout_observation.artifact != expected_layout_pointer
        or layout.observation_sha256 != request.layout_observation.observation_sha256
        or layout.bundle != request.bundle
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "past-exam Item evidence is not cross-bound",
        )
    proposal = proposals[0]
    if (
        decision_models[0].decision == "ACCEPT"
        and content_sha256(proposal.item_content.model_dump(mode="json")) != artifact_member.sha256
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "promoted Item content differs from its extraction proposal",
        )
    page_by_id = {page.page.page_input_id: page.page for page in layout.pages}
    page_by_position = {
        (page.page.source_role, page.page.physical_page): page.page for page in layout.pages
    }
    boundaries = tuple(
        value for value in layout.item_boundaries if value.item_number == item_number
    )
    if len(boundaries) != 1:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "past-exam Item layout boundary is ambiguous"
        )
    selected_page_ids = {segment.page_input_id for segment in boundaries[0].segments}
    for anchor in proposal.source_anchors:
        if anchor.source_role not in {"PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"}:
            continue
        if anchor.physical_page is None:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
                "past-exam Item image anchor has no physical page",
            )
        source_role = cast(
            Literal["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"], anchor.source_role
        )
        page = page_by_position.get((source_role, anchor.physical_page))
        if page is None or anchor.source != page.image:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
                "past-exam Item page anchor differs from its immutable PNG",
            )
        selected_page_ids.add(page.page_input_id)
    if not selected_page_ids.issubset(page_by_id):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "past-exam Item page selection is dangling"
        )
    page_inputs = tuple(
        sorted(
            (page_by_id[page_id] for page_id in selected_page_ids),
            key=lambda page: (
                0 if page.source_role == "PROBLEM_DOCUMENT" else 1,
                page.physical_page,
                page.page_input_id,
            ),
        )
    )
    for page in page_inputs:
        for pointer, max_bytes in ((page.source, MAX_SOURCE_BYTES), (page.image, 32 * 1024 * 1024)):
            _resolve_artifact_member(
                session,
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                size_bytes=None,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
            )
            artifacts.verify_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max_bytes,
            )
    try:
        return ApprovedPastExamItemKnowledgeSourceV3(
            item_id=revision.item_id,
            item_revision_id=revision.item_revision_id,
            artifact_member=artifact_member,
            extraction_acceptance_id=acceptance.acceptance_id,
            extraction_acceptance_sha256=acceptance.acceptance_sha256,
            extraction_acceptance_artifact=AssessmentArtifactMemberPointer(
                artifact_id=acceptance_record.acceptance_artifact_id,
                artifact_revision_id=acceptance_record.acceptance_artifact_revision_id,
                member_path=acceptance_record.acceptance_artifact_member_path,
                schema_ref=acceptance_record.acceptance_artifact_schema_ref,
                media_type=acceptance_record.acceptance_artifact_media_type,
                sha256=acceptance_record.acceptance_artifact_sha256,
            ),
            extraction_result_id=result.extraction_result_id,
            extraction_result_sha256=result.result_sha256,
            extraction_result_artifact=AssessmentArtifactMemberPointer(
                artifact_id=acceptance_record.result_artifact_id,
                artifact_revision_id=acceptance_record.result_artifact_revision_id,
                member_path=acceptance_record.result_artifact_member_path,
                schema_ref=acceptance_record.result_artifact_schema_ref,
                media_type=acceptance_record.result_artifact_media_type,
                sha256=acceptance_record.result_artifact_sha256,
            ),
            item_proposal_id=item_proposal_id,
            item_number=item_number,
            bundle=request.bundle,
            layout_observation=request.layout_observation,
            page_inputs=page_inputs,
            page_image_count=len(page_inputs),
        )
    except ValueError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "past-exam Item visual source contract is invalid",
        ) from exc


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON value")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = member
    return value


def _read_json_member(
    artifacts: CatalogArtifactService,
    *,
    artifact_id: str,
    revision_id: str,
    member_path: str,
    sha256: str,
    media_type: str,
    schema_ref: str,
) -> dict[str, Any]:
    raw = artifacts.read_member(
        artifact_id=artifact_id,
        revision_id=revision_id,
        member_path=member_path,
        sha256=sha256,
        media_type=media_type,
        schema_ref=schema_ref,
        max_bytes=MAX_DOCUMENT_JSON_BYTES,
    )
    value = json.loads(
        raw,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("Artifact member is not a JSON object")
    return value


def resolve_approved_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactService | None = None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
) -> ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3:
    """Resolve a currently approved Item Revision for a new analysis request."""

    return _resolve_item_source(
        session,
        artifacts=artifacts,
        item_revision_id=item_revision_id,
        source_class=source_class,
        eligible_revision_states=frozenset({"APPROVED"}),
    )


def resolve_historically_approved_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactService | None = None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
) -> ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3:
    """Re-resolve an immutable published source without substituting its current revision."""

    return _resolve_item_source(
        session,
        artifacts=artifacts,
        item_revision_id=item_revision_id,
        source_class=source_class,
        eligible_revision_states=frozenset({"APPROVED", "SUPERSEDED", "RETIRED"}),
    )


def resolve_educational_document_source(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    document_revision_id: str,
    source_class: Literal["TEXTBOOK", "CURRICULUM", "INTERNAL_GUIDE"],
    first_physical_page: int,
    last_physical_page: int,
    curriculum_unit_keys: tuple[str, ...],
    cache: EducationalDocumentSourceResolutionCache | None = None,
) -> EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4:
    revision = session.get(EducationalDocumentRevisionRecord, document_revision_id)
    document = (
        session.get(EducationalDocumentRecord, revision.document_id)
        if revision is not None
        else None
    )
    if revision is None or document is None:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "Educational Document Revision does not exist"
        )
    if (
        revision.revision_state != "APPROVED"
        or document.lifecycle_state != "ACTIVE"
        or document.current_revision_id != revision.document_revision_id
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document Revision is not the active approved revision",
        )
    expected_source_classes = {
        "TEXTBOOK": {"TEXTBOOK"},
        "CURRICULUM": {"CURRICULUM"},
        "REFERENCE_BOOK": {"INTERNAL_GUIDE"},
        "GUIDANCE": {"INTERNAL_GUIDE"},
    }
    if source_class not in expected_source_classes.get(document.document_kind, set()):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document class does not match the registered document kind",
        )
    if (
        first_physical_page < 1
        or last_physical_page < first_physical_page
        or last_physical_page > revision.source_page_count
        or last_physical_page - first_physical_page + 1 > MAX_DOCUMENT_SELECTION_PAGES
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document page range is outside the bounded source contract",
        )
    if curriculum_unit_keys != tuple(sorted(set(curriculum_unit_keys))):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document curriculum keys are not sorted and unique",
        )
    source_index = _cached_artifact_member_index(
        session,
        artifact_id=revision.source_artifact_id,
        artifact_revision_id=revision.source_artifact_revision_id,
        cache=cache,
    )
    analysis_index = _cached_artifact_member_index(
        session,
        artifact_id=revision.analysis_artifact_id,
        artifact_revision_id=revision.analysis_artifact_revision_id,
        cache=cache,
    )
    rights_index = _cached_artifact_member_index(
        session,
        artifact_id=revision.rights_artifact_id,
        artifact_revision_id=revision.rights_artifact_revision_id,
        cache=cache,
    )
    source_pointer = _exact_artifact_member(
        source_index,
        member_path="source/original.pdf",
        sha256=revision.source_sha256,
        size_bytes=revision.source_size_bytes,
        media_type="application/pdf",
        schema_ref=DOCUMENT_PDF_SCHEMA_REF,
    )
    analysis_manifest_member = _exact_artifact_member(
        analysis_index,
        member_path="analysis/manifest.json",
        sha256=revision.analysis_manifest_sha256,
        size_bytes=None,
        media_type="application/json",
        schema_ref=None,
    )
    analysis_schema_ref = analysis_manifest_member.get("schema_ref")
    if analysis_schema_ref not in {DOCUMENT_BUNDLE_SCHEMA_REF, DOCUMENT_BUNDLE_SCHEMA_REF_V2}:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
            "Educational Document analysis schema is unsupported",
        )
    _exact_artifact_member(
        rights_index,
        member_path="rights/attestation.json",
        sha256=revision.rights_attestation_sha256,
        size_bytes=None,
        media_type="application/json",
        schema_ref=DOCUMENT_RIGHTS_SCHEMA_REF,
    )
    dependency_key = (
        revision.analysis_artifact_id,
        revision.analysis_artifact_revision_id,
        revision.analysis_manifest_sha256,
        revision.rights_artifact_id,
        revision.rights_artifact_revision_id,
        revision.rights_attestation_sha256,
        str(analysis_schema_ref),
    )
    dependencies = cache.dependency_documents.get(dependency_key) if cache is not None else None
    if dependencies is None:
        try:
            bundle_value = json.loads(
                artifacts.read_member(
                    artifact_id=revision.analysis_artifact_id,
                    revision_id=revision.analysis_artifact_revision_id,
                    member_path="analysis/manifest.json",
                    sha256=revision.analysis_manifest_sha256,
                    media_type="application/json",
                    schema_ref=str(analysis_schema_ref),
                    max_bytes=MAX_DOCUMENT_JSON_BYTES,
                )
            )
            rights_value = json.loads(
                artifacts.read_member(
                    artifact_id=revision.rights_artifact_id,
                    revision_id=revision.rights_artifact_revision_id,
                    member_path="rights/attestation.json",
                    sha256=revision.rights_attestation_sha256,
                    media_type="application/json",
                    schema_ref=DOCUMENT_RIGHTS_SCHEMA_REF,
                    max_bytes=MAX_DOCUMENT_JSON_BYTES,
                )
            )
            is_multimodal = analysis_schema_ref == DOCUMENT_BUNDLE_SCHEMA_REF_V2
            validate_contract(
                "textbook-analysis-bundle-manifest-v2"
                if is_multimodal
                else "textbook-analysis-bundle-manifest",
                bundle_value,
            )
            bundle_model = (
                TextbookAnalysisBundleManifestV2
                if is_multimodal
                else TextbookAnalysisBundleManifest
            )
            bundle = bundle_model.model_validate(bundle_value)
            validate_contract("educational-document-rights-attestation", rights_value)
            rights = EducationalDocumentRightsAttestation.model_validate(rights_value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH",
                "Educational Document dependency bytes are invalid",
            ) from exc
        dependencies = (bundle, rights)
        if cache is not None:
            cache.dependency_documents[dependency_key] = dependencies
    bundle, rights = dependencies
    if (
        bundle.bundle_state != "CANONICAL"
        or bundle.canonical_source is None
        or bundle.canonical_source.artifact_id != revision.source_artifact_id
        or bundle.canonical_source.artifact_revision_id != revision.source_artifact_revision_id
        or bundle.canonical_source.member_path != "source/original.pdf"
        or bundle.canonical_source.sha256 != revision.source_sha256
        or bundle.source.sha256 != revision.source_sha256
        or bundle.source.page_count != revision.source_page_count
        or rights.source_sha256 != revision.source_sha256
        or rights.rights_state != "CLEARED_LICENSED"
        or not {"KNOWLEDGE_ANALYSIS", "GRAPH_INDEXING"}.issubset(set(rights.permitted_uses))
        or "DATA_ANALYST_WORKER" not in rights.allowed_roles
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "Educational Document bundle or rights dependency differs from the revision",
        )
    overlapping_keys = {
        mapping.eom_unit_key
        for mapping in bundle.curriculum_mappings
        if mapping.last_physical_page >= first_physical_page
        and mapping.first_physical_page <= last_physical_page
    }
    if not set(curriculum_unit_keys).issubset(overlapping_keys):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document curriculum keys do not overlap the selected pages",
        )
    pages_by_number = {page.physical_page: page for page in bundle.pages}
    expected_pages = tuple(range(first_physical_page, last_physical_page + 1))
    if any(page not in pages_by_number for page in expected_pages):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document analysis bundle has a page gap",
        )
    if isinstance(bundle, TextbookAnalysisBundleManifestV2):
        multimodal_pages_by_number: dict[int, TextbookPageAnalysisV2] = {
            page.physical_page: page for page in bundle.pages
        }
        materialization_v4: list[KnowledgeAnalysisDocumentMaterializationMemberV4] = []
        index_path = f"analysis/{bundle.index_member.member_path}"
        index_member = _exact_artifact_member(
            analysis_index,
            member_path=index_path,
            sha256=bundle.index_member.member_sha256,
            size_bytes=None,
            media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
            schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
        )
        materialization_v4.append(
            KnowledgeAnalysisDocumentMaterializationMemberV4(
                member_kind="INDEX",
                physical_page=None,
                artifact_id=revision.analysis_artifact_id,
                artifact_revision_id=revision.analysis_artifact_revision_id,
                member_path=index_path,
                materialized_path="source/document/index.md",
                sha256=bundle.index_member.member_sha256,
                bytes=_member_bytes(index_member),
                schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
                media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
                logical_name="index.md",
                width_pixels=None,
                height_pixels=None,
            )
        )
        for physical_page in expected_pages:
            page = multimodal_pages_by_number[physical_page]
            text_path = f"analysis/{page.member_path}"
            text_member = _exact_artifact_member(
                analysis_index,
                member_path=text_path,
                sha256=page.member_sha256,
                size_bytes=None,
                media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
                schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
            )
            materialization_v4.append(
                KnowledgeAnalysisDocumentMaterializationMemberV4(
                    member_kind="PAGE_TEXT",
                    physical_page=physical_page,
                    artifact_id=revision.analysis_artifact_id,
                    artifact_revision_id=revision.analysis_artifact_revision_id,
                    member_path=text_path,
                    materialized_path=f"source/document/pages/page-{physical_page:06d}.md",
                    sha256=page.member_sha256,
                    bytes=_member_bytes(text_member),
                    schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
                    media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
                    logical_name=f"page-{physical_page:06d}.md",
                    width_pixels=None,
                    height_pixels=None,
                )
            )
        for physical_page in expected_pages:
            page = multimodal_pages_by_number[physical_page]
            image_path = f"analysis/{page.image_member_path}"
            image_member = _exact_artifact_member(
                analysis_index,
                member_path=image_path,
                sha256=page.image_sha256,
                size_bytes=page.image_bytes,
                media_type=DOCUMENT_PAGE_IMAGE_MEDIA_TYPE,
                schema_ref=DOCUMENT_PAGE_IMAGE_SCHEMA_REF,
            )
            materialization_v4.append(
                KnowledgeAnalysisDocumentMaterializationMemberV4(
                    member_kind="PAGE_IMAGE",
                    physical_page=physical_page,
                    artifact_id=revision.analysis_artifact_id,
                    artifact_revision_id=revision.analysis_artifact_revision_id,
                    member_path=image_path,
                    materialized_path=f"source/document/images/page-{physical_page:06d}.png",
                    sha256=page.image_sha256,
                    bytes=_member_bytes(image_member),
                    schema_ref=DOCUMENT_PAGE_IMAGE_SCHEMA_REF,
                    media_type=DOCUMENT_PAGE_IMAGE_MEDIA_TYPE,
                    logical_name=f"page-{physical_page:06d}.png",
                    width_pixels=page.image_width_pixels,
                    height_pixels=page.image_height_pixels,
                )
            )
        total_bytes = sum(member.bytes for member in materialization_v4)
        if total_bytes > MAX_DOCUMENT_MULTIMODAL_MATERIALIZATION_BYTES:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
                "Educational Document multimodal materialization exceeds the byte budget",
            )
        try:
            return EducationalDocumentKnowledgeSourceV4(
                source_class=source_class,
                document_id=document.document_id,
                document_revision_id=revision.document_revision_id,
                artifact_member=KnowledgeAnalysisOriginalSourceMemberV3(
                    artifact_id=revision.source_artifact_id,
                    artifact_revision_id=revision.source_artifact_revision_id,
                    member_path="source/original.pdf",
                    sha256=revision.source_sha256,
                    bytes=_member_bytes(source_pointer),
                    schema_ref=DOCUMENT_PDF_SCHEMA_REF,
                    logical_name="original.pdf",
                ),
                analysis_bundle_manifest=KnowledgeAnalysisDocumentDependencyV3(
                    artifact_id=revision.analysis_artifact_id,
                    artifact_revision_id=revision.analysis_artifact_revision_id,
                    member_path="analysis/manifest.json",
                    sha256=revision.analysis_manifest_sha256,
                    schema_ref=DOCUMENT_BUNDLE_SCHEMA_REF_V2,
                    logical_name="manifest.json",
                ),
                rights_attestation=KnowledgeAnalysisDocumentDependencyV3(
                    artifact_id=revision.rights_artifact_id,
                    artifact_revision_id=revision.rights_artifact_revision_id,
                    member_path="rights/attestation.json",
                    sha256=revision.rights_attestation_sha256,
                    schema_ref=DOCUMENT_RIGHTS_SCHEMA_REF,
                    logical_name="attestation.json",
                ),
                first_physical_page=first_physical_page,
                last_physical_page=last_physical_page,
                curriculum_unit_keys=curriculum_unit_keys,
                materialization_members=tuple(materialization_v4),
                materialization_bytes=total_bytes,
                page_image_count=len(expected_pages),
            )
        except ValueError as exc:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
                "Educational Document multimodal source contract is invalid",
            ) from exc
    materialization: list[KnowledgeAnalysisDocumentMaterializationMemberV3] = []
    index_path = f"analysis/{bundle.index_member.member_path}"
    index_member = _exact_artifact_member(
        analysis_index,
        member_path=index_path,
        sha256=bundle.index_member.member_sha256,
        size_bytes=None,
        media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
        schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
    )
    materialization.append(
        KnowledgeAnalysisDocumentMaterializationMemberV3(
            member_kind="INDEX",
            physical_page=None,
            artifact_id=revision.analysis_artifact_id,
            artifact_revision_id=revision.analysis_artifact_revision_id,
            member_path=index_path,
            materialized_path="source/document/index.md",
            sha256=bundle.index_member.member_sha256,
            bytes=_member_bytes(index_member),
            schema_ref="eom://schemas/educational-document/extracted-markdown/1.0",
            logical_name="index.md",
        )
    )
    for physical_page in expected_pages:
        text_page = pages_by_number[physical_page]
        member_path = f"analysis/{text_page.member_path}"
        member = _exact_artifact_member(
            analysis_index,
            member_path=member_path,
            sha256=text_page.member_sha256,
            size_bytes=None,
            media_type=DOCUMENT_MARKDOWN_MEDIA_TYPE,
            schema_ref=DOCUMENT_MARKDOWN_SCHEMA_REF,
        )
        materialization.append(
            KnowledgeAnalysisDocumentMaterializationMemberV3(
                member_kind="PAGE",
                physical_page=physical_page,
                artifact_id=revision.analysis_artifact_id,
                artifact_revision_id=revision.analysis_artifact_revision_id,
                member_path=member_path,
                materialized_path=f"source/document/pages/page-{physical_page:06d}.md",
                sha256=text_page.member_sha256,
                bytes=_member_bytes(member),
                schema_ref="eom://schemas/educational-document/extracted-markdown/1.0",
                logical_name=f"page-{physical_page:06d}.md",
            )
        )
    total_bytes = sum(member.bytes for member in materialization)
    if total_bytes > MAX_DOCUMENT_MATERIALIZATION_BYTES:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document materialization exceeds the byte budget",
        )
    try:
        return EducationalDocumentKnowledgeSourceV3(
            source_class=source_class,
            document_id=document.document_id,
            document_revision_id=revision.document_revision_id,
            artifact_member=KnowledgeAnalysisOriginalSourceMemberV3(
                artifact_id=revision.source_artifact_id,
                artifact_revision_id=revision.source_artifact_revision_id,
                member_path="source/original.pdf",
                sha256=revision.source_sha256,
                bytes=_member_bytes(source_pointer),
                schema_ref="eom://schemas/educational-document/pdf-source/1.0",
                logical_name="original.pdf",
            ),
            analysis_bundle_manifest=KnowledgeAnalysisDocumentDependencyV3(
                artifact_id=revision.analysis_artifact_id,
                artifact_revision_id=revision.analysis_artifact_revision_id,
                member_path="analysis/manifest.json",
                sha256=revision.analysis_manifest_sha256,
                schema_ref=DOCUMENT_BUNDLE_SCHEMA_REF,
                logical_name="manifest.json",
            ),
            rights_attestation=KnowledgeAnalysisDocumentDependencyV3(
                artifact_id=revision.rights_artifact_id,
                artifact_revision_id=revision.rights_artifact_revision_id,
                member_path="rights/attestation.json",
                sha256=revision.rights_attestation_sha256,
                schema_ref=DOCUMENT_RIGHTS_SCHEMA_REF,
                logical_name="attestation.json",
            ),
            first_physical_page=first_physical_page,
            last_physical_page=last_physical_page,
            curriculum_unit_keys=curriculum_unit_keys,
            materialization_members=tuple(materialization),
            materialization_bytes=total_bytes,
        )
    except ValueError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE",
            "Educational Document source contract is invalid",
        ) from exc


def _artifact_member_index(
    session: Session,
    *,
    artifact_id: str,
    artifact_revision_id: str,
) -> _ArtifactMemberIndex:
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
    if not isinstance(files, list):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member inventory is absent"
        )
    members_by_path: dict[str, dict[str, object]] = {}
    for raw_member in files:
        if not isinstance(raw_member, dict):
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "source Artifact member inventory is malformed",
            )
        member = {str(key): value for key, value in raw_member.items()}
        member_path = member.get("file_name")
        if not isinstance(member_path, str) or member_path in members_by_path:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "source Artifact member inventory is duplicated or malformed",
            )
        members_by_path[member_path] = member
    return _ArtifactMemberIndex(
        logical=logical,
        revision=revision,
        members_by_path=members_by_path,
    )


def _cached_artifact_member_index(
    session: Session,
    *,
    artifact_id: str,
    artifact_revision_id: str,
    cache: EducationalDocumentSourceResolutionCache | None,
) -> _ArtifactMemberIndex:
    key = (artifact_id, artifact_revision_id)
    if cache is not None and key in cache.artifact_indexes:
        return cache.artifact_indexes[key]
    index = _artifact_member_index(
        session,
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
    )
    if cache is not None:
        cache.artifact_indexes[key] = index
    return index


def _exact_artifact_member(
    index: _ArtifactMemberIndex,
    *,
    member_path: str,
    sha256: str,
    size_bytes: int | None,
    media_type: str,
    schema_ref: str | None,
) -> dict[str, object]:
    path = PurePosixPath(member_path)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member path is unsafe"
        )
    member = index.members_by_path.get(member_path)
    if member is None:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member is absent"
        )
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
    return member


def _member_bytes(member: dict[str, object]) -> int:
    value = member.get("bytes")
    if not isinstance(value, int) or value < 1:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "source Artifact member byte count is invalid"
        )
    return value


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
    index = _artifact_member_index(
        session,
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
    )
    member = _exact_artifact_member(
        index,
        member_path=member_path,
        sha256=sha256,
        size_bytes=size_bytes,
        media_type=media_type,
        schema_ref=schema_ref,
    )
    return index.logical, index.revision, member
