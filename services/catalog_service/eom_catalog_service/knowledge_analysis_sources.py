"""Resolve exact approved source pointers for knowledge-analysis requests."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from threading import get_ident
from types import MappingProxyType
from typing import Literal, cast

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V3_SCHEMA_REF,
    LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF,
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    AssessmentArtifactMemberPointer,
    ContentIntakeKnowledgeSourceV2,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationalDocumentRightsAttestation,
    KnowledgeAnalysisDocumentDependencyV3,
    KnowledgeAnalysisDocumentMaterializationMemberV3,
    KnowledgeAnalysisDocumentMaterializationMemberV4,
    KnowledgeAnalysisOriginalSourceMemberV3,
    KnowledgeAnalysisSourceArtifactMemberV2,
    TextbookAnalysisBundleManifest,
    TextbookAnalysisBundleManifestV2,
    TextbookPageAnalysisV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.artifacts import CatalogArtifactReader
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
from eom_catalog_service.legacy_item_media_compatibility_service import (
    LegacyItemMediaCompatibilityError,
    expected_promoted_legacy_item_content,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    EducationalDocumentRecord,
    EducationalDocumentRevisionRecord,
    ItemComponentRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.past_exam_source_provenance import (
    PastExamProvenanceMember,
    PastExamSourceResolutionCache,
)

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_ITEM_SOURCE_RELATION_REVISIONS = 1024
MAX_ITEM_SOURCE_RELATION_WORK_UNITS = 4096
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


@dataclass(frozen=True, slots=True)
class ItemSourceReadRelations:
    """Current relations for ONE capture, never a shared admission/authority cache."""

    _session: Session = field(repr=False)
    _root: SessionTransaction = field(repr=False)
    _thread_id: int = field(repr=False)
    _components: Mapping[str, tuple[ItemComponentRecord, ...]] = field(repr=False)
    _decisions: Mapping[tuple[str, str, int], tuple[LegacyItemExtractionDecisionRecord, ...]] = (
        field(repr=False)
    )
    _work_units: Mapping[tuple[str, str], tuple[LegacyItemExtractionBatchWorkUnitRecord, ...]] = (
        field(repr=False)
    )
    _acceptances: Mapping[str, LegacyItemExtractionAcceptanceRecord] = field(repr=False)
    _batches: Mapping[str, LegacyItemExtractionBatchRecord] = field(repr=False)
    _bundles: Mapping[str, AssessmentSourceBundleRevisionRecord] = field(repr=False)
    _layouts: Mapping[str, AssessmentLayoutObservationRecord] | None = field(repr=False)

    def _require(self, session: Session) -> None:
        if (
            session is not self._session
            or session.get_transaction() is not self._root
            or not self._root.is_active
            or get_ident() != self._thread_id
        ):
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "Item source read relations are out of scope"
            )

    def components(self, session: Session, revision_id: str) -> tuple[ItemComponentRecord, ...]:
        self._require(session)
        if revision_id not in self._components:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "Item source revision was not selected"
            )
        return self._components[revision_id]

    def decisions(
        self, session: Session, key: tuple[str, str, int]
    ) -> tuple[LegacyItemExtractionDecisionRecord, ...]:
        self._require(session)
        return self._decisions.get(key, ())

    def work_units(
        self, session: Session, key: tuple[str, str]
    ) -> tuple[LegacyItemExtractionBatchWorkUnitRecord, ...]:
        self._require(session)
        return self._work_units.get(key, ())

    def acceptance(
        self, session: Session, acceptance_id: str
    ) -> LegacyItemExtractionAcceptanceRecord | None:
        self._require(session)
        return self._acceptances.get(acceptance_id)

    def batch(self, session: Session, batch_id: str) -> LegacyItemExtractionBatchRecord | None:
        self._require(session)
        return self._batches.get(batch_id)

    def bundle(
        self, session: Session, revision_id: str
    ) -> AssessmentSourceBundleRevisionRecord | None:
        self._require(session)
        return self._bundles.get(revision_id)

    def layout(self, session: Session, layout_id: str) -> AssessmentLayoutObservationRecord | None:
        self._require(session)
        # Legacy metadata-only callers cannot select layout IDs without the
        # exact batch member. Production supplies the existing reader/cache.
        if self._layouts is None:
            return session.get(AssessmentLayoutObservationRecord, layout_id)
        return self._layouts.get(layout_id)


def read_item_source_relations(
    session: Session,
    item_revision_ids: tuple[str, ...],
    *,
    artifacts: CatalogArtifactReader | None = None,
    past_exam_cache: PastExamSourceResolutionCache | None = None,
) -> ItemSourceReadRelations:
    """Batch exact current inputs afresh; preserve duplicates and lineage ordering."""
    selected = tuple(sorted(set(item_revision_ids)))
    root = session.get_transaction()
    if root is None or not root.is_active or len(selected) > MAX_ITEM_SOURCE_RELATION_REVISIONS:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "Item source relation scope is invalid"
        )
    revisions = tuple(
        session.scalars(
            select(ItemRevisionRecord)
            .where(ItemRevisionRecord.item_revision_id.in_(selected))
            .execution_options(populate_existing=True)
        )
    )
    components = tuple(
        session.scalars(
            select(ItemComponentRecord)
            .where(
                ItemComponentRecord.item_revision_id.in_(selected),
                or_(
                    and_(
                        ItemComponentRecord.component_type == "ITEM_CONTENT",
                        ItemComponentRecord.ordinal == 0,
                    ),
                    and_(
                        ItemComponentRecord.component_type == "OTHER",
                        ItemComponentRecord.schema_ref
                        == LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF,
                    ),
                ),
            )
            .limit(4 * len(selected) + 1)
            .execution_options(populate_existing=True)
        )
    )
    if len(components) > 4 * len(selected):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "Item source component budget is exceeded"
        )
    decision_keys: set[tuple[str, str, int]] = set()
    work_unit_keys: set[tuple[str, str]] = set()
    for revision in revisions:
        metadata = revision.metadata_json
        acceptance, result = (
            metadata.get("extraction_acceptance_id"),
            metadata.get("extraction_result_id"),
        )
        proposal, number = metadata.get("item_proposal_id"), metadata.get("item_number")
        if (
            metadata.get("source_kind") == "PAST_EXAM"
            and isinstance(acceptance, str)
            and isinstance(result, str)
            and isinstance(proposal, str)
            and isinstance(number, int)
        ):
            decision_keys.add((acceptance, proposal, number))
            work_unit_keys.add((acceptance, result))
    decisions = (
        tuple(
            session.scalars(
                select(LegacyItemExtractionDecisionRecord)
                .where(
                    tuple_(
                        LegacyItemExtractionDecisionRecord.acceptance_id,
                        LegacyItemExtractionDecisionRecord.item_proposal_id,
                        LegacyItemExtractionDecisionRecord.item_number,
                    ).in_(tuple(sorted(decision_keys)))
                )
                .limit(2 * len(decision_keys) + 1)
                .execution_options(populate_existing=True)
            )
        )
        if decision_keys
        else ()
    )
    units = (
        tuple(
            session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .where(
                    tuple_(
                        LegacyItemExtractionBatchWorkUnitRecord.acceptance_id,
                        LegacyItemExtractionBatchWorkUnitRecord.extraction_result_id,
                    ).in_(tuple(sorted(work_unit_keys))),
                    LegacyItemExtractionBatchWorkUnitRecord.state == "ACCEPTED",
                )
                .order_by(
                    LegacyItemExtractionBatchWorkUnitRecord.created_at,
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.work_unit_id,
                )
                .limit(MAX_ITEM_SOURCE_RELATION_WORK_UNITS + 1)
                .execution_options(populate_existing=True)
            )
        )
        if work_unit_keys
        else ()
    )
    if len(decisions) > 2 * len(decision_keys) or len(units) > MAX_ITEM_SOURCE_RELATION_WORK_UNITS:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "Item extraction relation budget is exceeded"
        )
    acceptance_ids = tuple(sorted({key[0] for key in work_unit_keys}))
    acceptances = (
        tuple(
            session.scalars(
                select(LegacyItemExtractionAcceptanceRecord)
                .where(LegacyItemExtractionAcceptanceRecord.acceptance_id.in_(acceptance_ids))
                .execution_options(populate_existing=True)
            )
        )
        if acceptance_ids
        else ()
    )
    batch_ids = tuple(sorted({unit.extraction_batch_id for unit in units}))
    batches = (
        tuple(
            session.scalars(
                select(LegacyItemExtractionBatchRecord)
                .where(LegacyItemExtractionBatchRecord.extraction_batch_id.in_(batch_ids))
                .execution_options(populate_existing=True)
            )
        )
        if batch_ids
        else ()
    )
    bundle_ids = tuple(sorted({unit.assessment_source_bundle_revision_id for unit in units}))
    bundles = (
        tuple(
            session.scalars(
                select(AssessmentSourceBundleRevisionRecord)
                .where(
                    AssessmentSourceBundleRevisionRecord.assessment_source_bundle_revision_id.in_(
                        bundle_ids
                    )
                )
                .execution_options(populate_existing=True)
            )
        )
        if bundle_ids
        else ()
    )
    batches_by_id = {row.extraction_batch_id: row for row in batches}
    layouts: tuple[AssessmentLayoutObservationRecord, ...] | None = None
    if artifacts is not None:
        provenance = (
            past_exam_cache if past_exam_cache is not None else PastExamSourceResolutionCache()
        )
        layout_ids: set[str] = set()
        for unit in units:
            batch = batches_by_id.get(unit.extraction_batch_id)
            if batch is None:
                continue
            try:
                decoded = provenance.batch(
                    artifacts,
                    PastExamProvenanceMember(
                        artifact_id=batch.manifest_artifact_id,
                        artifact_revision_id=batch.manifest_artifact_revision_id,
                        member_path=batch.manifest_artifact_member_path,
                        sha256=batch.manifest_artifact_sha256,
                        schema_ref=batch.manifest_artifact_schema_ref,
                        media_type=batch.manifest_artifact_media_type,
                        max_bytes=MAX_DOCUMENT_JSON_BYTES,
                    ),
                )
            except (OSError, TypeError, ValueError, JsonSchemaError):
                # Preserve the canonical resolver's eligibility/error ordering.
                # Invalid members never grant a layout hint or become cached.
                continue
            matches = decoded.work_units_by_id.get(unit.work_unit_id, ())
            if len(matches) == 1:
                layout_ids.add(
                    matches[0].request.layout_observation.assessment_layout_observation_id
                )
        layouts = (
            tuple(
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
            if layout_ids
            else ()
        )
    components_by_revision: dict[str, list[ItemComponentRecord]] = {key: [] for key in selected}
    decisions_by_key: dict[tuple[str, str, int], list[LegacyItemExtractionDecisionRecord]] = (
        defaultdict(list)
    )
    units_by_key: dict[tuple[str, str], list[LegacyItemExtractionBatchWorkUnitRecord]] = (
        defaultdict(list)
    )
    for component in components:
        components_by_revision[component.item_revision_id].append(component)
    for decision in decisions:
        decisions_by_key[
            (decision.acceptance_id, decision.item_proposal_id, decision.item_number)
        ].append(decision)
    for unit in units:
        if unit.acceptance_id is None or unit.extraction_result_id is None:
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "accepted Item work unit has incomplete lineage"
            )
        units_by_key[(unit.acceptance_id, unit.extraction_result_id)].append(unit)
    return ItemSourceReadRelations(
        session,
        root,
        get_ident(),
        MappingProxyType({key: tuple(rows) for key, rows in components_by_revision.items()}),
        MappingProxyType({key: tuple(rows) for key, rows in decisions_by_key.items()}),
        MappingProxyType({key: tuple(rows) for key, rows in units_by_key.items()}),
        MappingProxyType({row.acceptance_id: row for row in acceptances}),
        MappingProxyType(batches_by_id),
        MappingProxyType({row.assessment_source_bundle_revision_id: row for row in bundles}),
        None
        if layouts is None
        else MappingProxyType({row.assessment_layout_observation_id: row for row in layouts}),
    )


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
    artifacts: CatalogArtifactReader | None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
    eligible_revision_states: frozenset[str],
    past_exam_cache: PastExamSourceResolutionCache | None = None,
    read_relations: ItemSourceReadRelations | None = None,
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
    scoped_components = (
        None if read_relations is None else read_relations.components(session, item_revision_id)
    )
    components = (
        tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == item_revision_id,
                    ItemComponentRecord.component_type == "ITEM_CONTENT",
                    ItemComponentRecord.ordinal == 0,
                )
            )
        )
        if scoped_components is None
        else tuple(
            component
            for component in scoped_components
            if component.component_type == "ITEM_CONTENT" and component.ordinal == 0
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
            ASSESSMENT_ITEM_CONTENT_V3_SCHEMA_REF,
            "eom://schemas/item-registry/assessment-item-content-v1",
            "eom://schemas/item-registry/assessment-item-content-v2",
            "eom://schemas/item-registry/assessment-item-content-v3",
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
            cache=past_exam_cache,
            read_relations=read_relations,
            components=scoped_components,
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
    artifacts: CatalogArtifactReader,
    revision: ItemRevisionRecord,
    artifact_member: KnowledgeAnalysisSourceArtifactMemberV2,
    cache: PastExamSourceResolutionCache | None = None,
    read_relations: ItemSourceReadRelations | None = None,
    components: tuple[ItemComponentRecord, ...] | None = None,
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
    acceptance_record = (
        session.get(LegacyItemExtractionAcceptanceRecord, acceptance_id)
        if read_relations is None
        else read_relations.acceptance(session, acceptance_id)
    )
    decisions = (
        tuple(
            session.scalars(
                select(LegacyItemExtractionDecisionRecord).where(
                    LegacyItemExtractionDecisionRecord.acceptance_id == acceptance_id,
                    LegacyItemExtractionDecisionRecord.item_proposal_id == item_proposal_id,
                    LegacyItemExtractionDecisionRecord.item_number == item_number,
                )
            )
        )
        if read_relations is None
        else read_relations.decisions(session, (acceptance_id, item_proposal_id, item_number))
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
    work_units = (
        tuple(
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
        if read_relations is None
        else read_relations.work_units(session, (acceptance_id, extraction_result_id))
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
    batch = (
        session.get(LegacyItemExtractionBatchRecord, work_unit.extraction_batch_id)
        if read_relations is None
        else read_relations.batch(session, work_unit.extraction_batch_id)
    )
    bundle = (
        session.get(
            AssessmentSourceBundleRevisionRecord, work_unit.assessment_source_bundle_revision_id
        )
        if read_relations is None
        else read_relations.bundle(session, work_unit.assessment_source_bundle_revision_id)
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

    # Standalone resolutions keep their uncached lifetime; retrieval supplies
    # one bounded cache for its actual owner transaction only.
    provenance = cache if cache is not None else PastExamSourceResolutionCache(max_members=0)
    try:
        decoded_batch = provenance.batch(
            artifacts,
            PastExamProvenanceMember(
                artifact_id=batch.manifest_artifact_id,
                artifact_revision_id=batch.manifest_artifact_revision_id,
                member_path=batch.manifest_artifact_member_path,
                sha256=batch.manifest_artifact_sha256,
                media_type=batch.manifest_artifact_media_type,
                schema_ref=batch.manifest_artifact_schema_ref,
                max_bytes=MAX_DOCUMENT_JSON_BYTES,
            ),
        )
        batch_manifest = decoded_batch.value
        manifest_units = decoded_batch.work_units_by_id.get(work_unit.work_unit_id, ())
        if len(manifest_units) != 1:
            raise ValueError("work unit is absent from its immutable batch manifest")
        request = manifest_units[0].request

        decoded_acceptance = provenance.acceptance(
            artifacts,
            PastExamProvenanceMember(
                artifact_id=acceptance_record.acceptance_artifact_id,
                artifact_revision_id=acceptance_record.acceptance_artifact_revision_id,
                member_path=acceptance_record.acceptance_artifact_member_path,
                sha256=acceptance_record.acceptance_artifact_sha256,
                media_type=acceptance_record.acceptance_artifact_media_type,
                schema_ref=acceptance_record.acceptance_artifact_schema_ref,
                max_bytes=MAX_DOCUMENT_JSON_BYTES,
            ),
        )
        acceptance = decoded_acceptance.value

        decoded_result = provenance.result(
            artifacts,
            PastExamProvenanceMember(
                artifact_id=acceptance_record.result_artifact_id,
                artifact_revision_id=acceptance_record.result_artifact_revision_id,
                member_path=acceptance_record.result_artifact_member_path,
                sha256=acceptance_record.result_artifact_sha256,
                media_type=acceptance_record.result_artifact_media_type,
                schema_ref=acceptance_record.result_artifact_schema_ref,
                max_bytes=MAX_DOCUMENT_JSON_BYTES,
            ),
        )
        result = decoded_result.value

        layout_record = (
            session.get(
                AssessmentLayoutObservationRecord,
                request.layout_observation.assessment_layout_observation_id,
            )
            if read_relations is None
            else read_relations.layout(
                session, request.layout_observation.assessment_layout_observation_id
            )
        )
        if layout_record is None:
            raise ValueError("layout observation record is absent")
        decoded_layout = provenance.layout(
            artifacts,
            PastExamProvenanceMember(
                artifact_id=layout_record.artifact_id,
                artifact_revision_id=layout_record.artifact_revision_id,
                member_path=layout_record.artifact_member_path,
                sha256=layout_record.artifact_sha256,
                media_type=layout_record.artifact_media_type,
                schema_ref=layout_record.artifact_schema_ref,
                max_bytes=MAX_DOCUMENT_JSON_BYTES,
            ),
        )
        layout = decoded_layout.value
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH",
            "past-exam Item extraction evidence bytes are invalid",
        ) from exc

    decision_models = decoded_acceptance.decisions_by_item.get((item_proposal_id, item_number), ())
    proposals = decoded_result.proposals_by_item.get((item_proposal_id, item_number), ())
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
    try:
        expected_item_content = expected_promoted_legacy_item_content(
            session,
            artifacts=artifacts,
            item_revision_id=revision.item_revision_id,
            acceptance=acceptance,
            result=result,
            request=request,
            proposal=proposal,
            components=components,
        )
    except LegacyItemMediaCompatibilityError as exc:
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "promoted Item media compatibility evidence is invalid",
        ) from exc
    if (
        decision_models[0].decision == "ACCEPT"
        and content_sha256(expected_item_content.model_dump(mode="json")) != artifact_member.sha256
    ):
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
            "promoted Item content differs from its extraction proposal",
        )
    page_by_id = decoded_layout.pages_by_id
    page_by_position = decoded_layout.pages_by_position
    boundaries = decoded_layout.boundaries_by_item.get(item_number, ())
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


def resolve_approved_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactReader | None = None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
    past_exam_cache: PastExamSourceResolutionCache | None = None,
    read_relations: ItemSourceReadRelations | None = None,
) -> ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3:
    """Resolve a currently approved Item Revision for a new analysis request."""

    return _resolve_item_source(
        session,
        artifacts=artifacts,
        item_revision_id=item_revision_id,
        source_class=source_class,
        eligible_revision_states=frozenset({"APPROVED"}),
        past_exam_cache=past_exam_cache,
        read_relations=read_relations,
    )


def resolve_historically_approved_item_source(
    session: Session,
    *,
    artifacts: CatalogArtifactReader | None = None,
    item_revision_id: str,
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
    past_exam_cache: PastExamSourceResolutionCache | None = None,
    read_relations: ItemSourceReadRelations | None = None,
) -> ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3:
    """Re-resolve an immutable published source without substituting its current revision."""

    return _resolve_item_source(
        session,
        artifacts=artifacts,
        item_revision_id=item_revision_id,
        source_class=source_class,
        eligible_revision_states=frozenset({"APPROVED", "SUPERSEDED", "RETIRED"}),
        past_exam_cache=past_exam_cache,
        read_relations=read_relations,
    )


def resolve_educational_document_source(
    session: Session,
    artifacts: CatalogArtifactReader,
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
