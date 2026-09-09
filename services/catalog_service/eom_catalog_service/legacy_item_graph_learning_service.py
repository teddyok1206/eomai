"""Legacy selection and occurrence provenance for shared Item Graph publication."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    ApprovedPastExamItemKnowledgeSourceV3,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    CreateEvidenceBundleCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisRequestV9,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from pydantic import BaseModel
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
    build_automatic_item_alignment_retrieval_command,
)
from eom_catalog_service.knowledge_graph_models import KnowledgeSnapshotAnalysisRecord
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
)
from eom_catalog_service.legacy_assessment_models import LegacyItemExtractionDecisionRecord
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginInput as _PastExamOriginInput,
)
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginResolution as _PastExamOriginResolution,
)
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginResolutionError,
    past_exam_origin_inputs,
    resolve_past_exam_origins,
)
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginStatus as _PastExamOriginStatus,
)

MAX_AUTOMATIC_GRAPH_BATCH_SIZE = 16

_HISTORICAL_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "knowledge-analysis-request/2.0": KnowledgeAnalysisRequestV2,
    "knowledge-analysis-request/3.0": KnowledgeAnalysisRequestV3,
    "knowledge-analysis-request/4.0": KnowledgeAnalysisRequestV4,
    "knowledge-analysis-request/5.0": KnowledgeAnalysisRequestV5,
    "knowledge-analysis-request/6.0": KnowledgeAnalysisRequestV6,
    "knowledge-analysis-request/7.0": KnowledgeAnalysisRequestV7,
    "knowledge-analysis-request/8.0": KnowledgeAnalysisRequestV8,
}


def _validate_historical_request(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, str):
        return False
    model = _HISTORICAL_REQUEST_MODELS.get(schema_version)
    if model is None:
        return False
    model.model_validate(value)
    return True


@dataclass(frozen=True)
class LegacyItemGraphCandidate:
    analysis_run_id: str
    requested_by_operator_id: str
    graph_snapshot_revision_id: str


class LegacyItemGraphLearningError(ValueError):
    """Stable fail-closed error raised before any retrieval side effect."""

    code = "LEGACY_ITEM_GRAPH_ORIGIN_INVALID"

    def __init__(self, *, analysis_run_id: str, item_revision_id: str, reason: str) -> None:
        self.analysis_run_id = analysis_run_id
        self.item_revision_id = item_revision_id
        self.reason = reason
        super().__init__(
            f"{self.code}: {reason}; analysis_run_id={analysis_run_id}; "
            f"item_revision_id={item_revision_id}"
        )


@dataclass(frozen=True)
class _AllowedBatchMembership:
    order: int
    state: str
    acceptance_id: str
    acceptance_sha256: str | None
    extraction_result_id: str | None
    result_sha256: str | None
    bundle_id: str
    bundle_revision_id: str
    bundle_sha256: str


@dataclass(frozen=True)
class _PendingPastExamCandidate:
    analysis_order: int
    analysis_run_id: str
    requested_by_operator_id: str
    source_kind: str
    source_revision_id: str
    item_id: str | None
    item_revision_id: str | None
    source: ApprovedPastExamItemKnowledgeSourceV3
    memberships: tuple[_AllowedBatchMembership, ...]


class LegacyItemGraphLearningService:
    """Batch accepted Item analyses into immutable, policy-aligned Graph snapshots."""

    def __init__(
        self,
        engine: Engine,
        *,
        extraction_batch_ids: tuple[str, ...],
        access_policy_revision_id: str,
        publication: KnowledgeGraphPublicationService | None = None,
        retrieval: KnowledgeRetrievalApplicationService | None = None,
    ) -> None:
        if not extraction_batch_ids or len(extraction_batch_ids) != len(set(extraction_batch_ids)):
            raise ValueError("automatic Graph batch identities must be non-empty and unique")
        self.sessions = build_session_factory(engine)
        self.extraction_batch_ids = extraction_batch_ids
        self.access_policy_revision_id = access_policy_revision_id
        self.publication = publication or KnowledgeGraphPublicationService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)
        self.automatic_publication = AutomaticItemGraphPublicationService(
            engine,
            access_policy_revision_id=access_policy_revision_id,
            publication=self.publication,
            retrieval=self.retrieval,
        )

    def pending_candidates(self, *, limit: int) -> tuple[LegacyItemGraphCandidate, ...]:
        if limit < 1 or limit > MAX_AUTOMATIC_GRAPH_BATCH_SIZE:
            raise ValueError("Graph publication candidate limit must be within 1..16")
        context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
        with self.sessions() as session:
            # Batch membership is a small ordered provenance relation.  Group it before touching
            # analyses so reuse of one acceptance by multiple allowlisted batches cannot multiply
            # candidates or make LIMIT hide a corrupt origin.
            membership_rows = tuple(
                session.execute(
                    select(
                        LegacyItemExtractionBatchWorkUnitRecord.acceptance_id,
                        LegacyItemExtractionBatchWorkUnitRecord.acceptance_sha256,
                        LegacyItemExtractionBatchWorkUnitRecord.extraction_result_id,
                        LegacyItemExtractionBatchWorkUnitRecord.result_sha256,
                        LegacyItemExtractionBatchWorkUnitRecord.state,
                        LegacyItemExtractionBatchWorkUnitRecord.assessment_source_bundle_id,
                        LegacyItemExtractionBatchWorkUnitRecord.assessment_source_bundle_revision_id,
                        LegacyItemExtractionBatchWorkUnitRecord.bundle_manifest_sha256,
                    )
                    .join(
                        LegacyItemExtractionBatchRecord,
                        LegacyItemExtractionBatchRecord.extraction_batch_id
                        == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                    )
                    .where(
                        LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                            self.extraction_batch_ids
                        )
                    )
                    .order_by(
                        LegacyItemExtractionBatchRecord.created_at,
                        LegacyItemExtractionBatchRecord.extraction_batch_id,
                        LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                        LegacyItemExtractionBatchWorkUnitRecord.work_unit_id,
                    )
                )
            )
            memberships_by_acceptance: dict[str, list[_AllowedBatchMembership]] = {}
            for membership_order, row in enumerate(membership_rows):
                (
                    acceptance_id,
                    acceptance_sha256,
                    extraction_result_id,
                    result_sha256,
                    state,
                    bundle_id,
                    bundle_revision_id,
                    bundle_sha256,
                ) = row
                if acceptance_id is None:
                    continue
                memberships_by_acceptance.setdefault(acceptance_id, []).append(
                    _AllowedBatchMembership(
                        order=membership_order,
                        state=state,
                        acceptance_id=acceptance_id,
                        acceptance_sha256=acceptance_sha256,
                        extraction_result_id=extraction_result_id,
                        result_sha256=result_sha256,
                        bundle_id=bundle_id,
                        bundle_revision_id=bundle_revision_id,
                        bundle_sha256=bundle_sha256,
                    )
                )
            if not memberships_by_acceptance:
                return ()
            allowed_acceptance_ids = tuple(sorted(memberships_by_acceptance))

            # The JSON acceptance pointer is the direct scope anchor.  Independently resolve the
            # immutable promotion registration lineage so corruption of that JSON pointer cannot
            # silently remove an otherwise allowlisted Item from preflight.
            registration_keys = tuple(
                sorted(
                    {
                        f"legacy-item-promotion:{acceptance_id}:{item_proposal_id}"
                        for acceptance_id, item_proposal_id in session.execute(
                            select(
                                LegacyItemExtractionDecisionRecord.acceptance_id,
                                LegacyItemExtractionDecisionRecord.item_proposal_id,
                            ).where(
                                LegacyItemExtractionDecisionRecord.acceptance_id.in_(
                                    allowed_acceptance_ids
                                )
                            )
                        )
                    }
                )
            )

            # The configured legacy corpus has 520 Items.  Fetch its unique pending analysis base
            # once, scope by either independent acceptance or promotion-lineage anchor, then fully
            # parse only exact allowlisted memberships.  Historical request revisions can share the
            # promoted Item lineage, but only the current V9 visual analysis is publishable here.
            # Validate and skip valid immutable history; malformed in-scope history still fails
            # closed without letting an unrelated batch's malformed request block this coordinator.
            analysis_rows = tuple(
                session.execute(
                    select(
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                        KnowledgeAnalysisRunRecord.created_by_operator_id,
                        KnowledgeAnalysisRunRecord.source_kind,
                        KnowledgeAnalysisRunRecord.source_revision_id,
                        KnowledgeAnalysisRunRecord.item_id,
                        KnowledgeAnalysisRunRecord.item_revision_id,
                        KnowledgeAnalysisRunRecord.canonical_request,
                    )
                    .outerjoin(
                        KnowledgeSnapshotAnalysisRecord,
                        and_(
                            KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                            == context.graph_snapshot_revision_id,
                            KnowledgeSnapshotAnalysisRecord.analysis_run_id
                            == KnowledgeAnalysisRunRecord.analysis_run_id,
                        ),
                    )
                    .outerjoin(
                        ItemRevisionRecord,
                        ItemRevisionRecord.item_revision_id
                        == KnowledgeAnalysisRunRecord.item_revision_id,
                    )
                    .where(
                        or_(
                            KnowledgeAnalysisRunRecord.canonical_request["source"][
                                "extraction_acceptance_id"
                            ].astext.in_(allowed_acceptance_ids),
                            ItemRevisionRecord.registration_key.in_(registration_keys),
                        ),
                        KnowledgeAnalysisRunRecord.state == "ACCEPTED",
                        KnowledgeSnapshotAnalysisRecord.analysis_run_id.is_(None),
                    )
                    .order_by(
                        KnowledgeAnalysisRunRecord.created_at,
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                    )
                )
            )
            pending: list[_PendingPastExamCandidate] = []
            for analysis_order, row in enumerate(analysis_rows):
                (
                    analysis_run_id,
                    requested_by_operator_id,
                    source_kind,
                    source_revision_id,
                    item_id,
                    item_revision_id,
                    canonical_request,
                ) = row
                try:
                    if _validate_historical_request(canonical_request):
                        continue
                    source = KnowledgeAnalysisRequestV9.model_validate(canonical_request).source
                except ValueError as exc:
                    raise LegacyItemGraphLearningError(
                        analysis_run_id=analysis_run_id,
                        item_revision_id="unknown",
                        reason="canonical_request_invalid",
                    ) from exc
                memberships = tuple(
                    memberships_by_acceptance.get(source.extraction_acceptance_id, ())
                )
                if not memberships:
                    raise LegacyItemGraphLearningError(
                        analysis_run_id=analysis_run_id,
                        item_revision_id=source.item_revision_id,
                        reason="batch_membership_or_decision_invalid",
                    )
                pending.append(
                    _PendingPastExamCandidate(
                        analysis_order=analysis_order,
                        analysis_run_id=analysis_run_id,
                        requested_by_operator_id=requested_by_operator_id,
                        source_kind=source_kind,
                        source_revision_id=source_revision_id,
                        item_id=item_id,
                        item_revision_id=item_revision_id,
                        source=source,
                        memberships=memberships,
                    )
                )
            pending.sort(
                key=lambda candidate: (
                    candidate.memberships[0].order,
                    candidate.source.item_number,
                    candidate.analysis_order,
                    candidate.analysis_run_id,
                )
            )

            resolutions = self._resolve_past_exam_origins(
                session,
                tuple(
                    _PastExamOriginInput(
                        analysis_run_id=candidate.analysis_run_id,
                        source=candidate.source,
                    )
                    for candidate in pending
                ),
            )

        resolution_by_analysis = {
            resolution.analysis_run_id: resolution for resolution in resolutions
        }
        if len(resolution_by_analysis) != len(pending):
            duplicate = pending[0] if pending else None
            raise LegacyItemGraphLearningError(
                analysis_run_id=(duplicate.analysis_run_id if duplicate else "unknown"),
                item_revision_id=(duplicate.source.item_revision_id if duplicate else "unknown"),
                reason="origin_resolution_coverage_invalid",
            )
        selected: list[LegacyItemGraphCandidate] = []
        for candidate in pending:
            source = candidate.source
            resolution = resolution_by_analysis[candidate.analysis_run_id]
            invalid_membership = (
                candidate.source_kind != "APPROVED_ITEM_REVISION"
                or candidate.source_revision_id != source.item_revision_id
                or candidate.item_id != source.item_id
                or candidate.item_revision_id != source.item_revision_id
            )
            for membership in candidate.memberships:
                invalid_membership = invalid_membership or (
                    membership.state != "ACCEPTED"
                    or membership.acceptance_id != source.extraction_acceptance_id
                    or membership.acceptance_sha256 != source.extraction_acceptance_sha256
                    or membership.extraction_result_id != source.extraction_result_id
                    or membership.result_sha256 != source.extraction_result_sha256
                    or membership.bundle_id != source.bundle.assessment_source_bundle_id
                    or membership.bundle_revision_id
                    != source.bundle.assessment_source_bundle_revision_id
                    or membership.bundle_sha256 != source.bundle.bundle_manifest_sha256
                    or resolution.item_number != source.item_number
                    or resolution.assessment_source_bundle_id != membership.bundle_id
                    or resolution.assessment_source_bundle_revision_id
                    != membership.bundle_revision_id
                    or resolution.assessment_source_bundle_sha256 != membership.bundle_sha256
                )
            if invalid_membership:
                raise LegacyItemGraphLearningError(
                    analysis_run_id=candidate.analysis_run_id,
                    item_revision_id=source.item_revision_id,
                    reason="batch_membership_or_decision_invalid",
                )
            if resolution.status == _PastExamOriginStatus.POLICY_EXCLUDED:
                continue
            if len(selected) < limit:
                selected.append(
                    LegacyItemGraphCandidate(
                        analysis_run_id=candidate.analysis_run_id,
                        requested_by_operator_id=candidate.requested_by_operator_id,
                        graph_snapshot_revision_id=context.graph_snapshot_revision_id,
                    )
                )
        return tuple(selected)

    @staticmethod
    def _resolve_past_exam_origins(
        session: Session,
        inputs: tuple[_PastExamOriginInput, ...],
    ) -> tuple[_PastExamOriginResolution, ...]:
        try:
            return resolve_past_exam_origins(session, inputs)
        except PastExamOriginResolutionError as exc:
            raise LegacyItemGraphLearningError(
                analysis_run_id=exc.analysis_run_id,
                item_revision_id=exc.item_revision_id,
                reason=exc.reason,
            ) from exc

    @classmethod
    def _resolve_past_exam_analyses(
        cls,
        session: Session,
        analyses: tuple[AcceptedAnalysisProposal, ...],
    ) -> tuple[_PastExamOriginResolution, ...]:
        try:
            inputs = past_exam_origin_inputs(analyses)
        except PastExamOriginResolutionError as exc:
            raise LegacyItemGraphLearningError(
                analysis_run_id=exc.analysis_run_id,
                item_revision_id=exc.item_revision_id,
                reason=exc.reason,
            ) from exc
        return cls._resolve_past_exam_origins(session, inputs)

    @classmethod
    def _validate_past_exam_analyses(
        cls,
        session: Session,
        analyses: tuple[AcceptedAnalysisProposal, ...],
    ) -> None:
        resolutions = cls._resolve_past_exam_analyses(session, analyses)
        excluded = next(
            (
                resolution
                for resolution in resolutions
                if resolution.status == _PastExamOriginStatus.POLICY_EXCLUDED
            ),
            None,
        )
        if excluded is not None:
            raise LegacyItemGraphLearningError(
                analysis_run_id=excluded.analysis_run_id,
                item_revision_id=excluded.item_revision_id,
                reason="past_exam_origin_policy_excluded",
            )

    def publish(self, candidates: tuple[LegacyItemGraphCandidate, ...]) -> str:
        """Publish one fresh snapshot containing the exact ordered candidate set."""

        receipt = self.automatic_publication.publish(
            tuple(
                AutomaticItemGraphCandidate(
                    analysis_run_id=candidate.analysis_run_id,
                    requested_by_operator_id=candidate.requested_by_operator_id,
                    graph_snapshot_revision_id=candidate.graph_snapshot_revision_id,
                )
                for candidate in candidates
            ),
            required_source_class="PAST_EXAM",
            retrieval_idempotency_namespace="legacy-auto-alignment",
            publication_idempotency_namespace="legacy-auto-graph",
            publisher_version="1.6.0",
            analysis_validator=self._validate_past_exam_analyses,
            occurrence_binding_resolver=self._assessment_item_occurrence_bindings,
        )
        return receipt.graph_publication.graph_snapshot.graph_snapshot_revision_id

    @staticmethod
    def _assessment_item_occurrence_bindings(
        session: Session,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        alignments: tuple[AutomaticItemCurriculumAlignmentBinding, ...],
    ) -> tuple[AssessmentOccurrenceItemBinding, ...]:
        """Revalidate origins, then add alignment IDs to immutable placement values."""

        resolutions = LegacyItemGraphLearningService._resolve_past_exam_analyses(session, analyses)
        resolution_by_revision = {
            resolution.item_revision_id: resolution for resolution in resolutions
        }
        alignment_by_revision = {alignment.item_revision_id: alignment for alignment in alignments}
        if (
            not resolution_by_revision
            or len(resolution_by_revision) != len(resolutions)
            or len(alignment_by_revision) != len(alignments)
            or set(resolution_by_revision) != set(alignment_by_revision)
        ):
            raise ValueError("PAST_EXAM analyses and automatic alignments must match exactly")

        bindings: list[AssessmentOccurrenceItemBinding] = []
        for resolution in resolutions:
            if resolution.status != _PastExamOriginStatus.ELIGIBLE:
                raise LegacyItemGraphLearningError(
                    analysis_run_id=resolution.analysis_run_id,
                    item_revision_id=resolution.item_revision_id,
                    reason="past_exam_origin_policy_excluded",
                )
            alignment = alignment_by_revision[resolution.item_revision_id]
            value: dict[str, object] = {
                "analysis_run_id": resolution.analysis_run_id,
                "item_id": resolution.item_id,
                "item_revision_id": resolution.item_revision_id,
                "item_origin_profile_id": resolution.item_origin_profile_id,
                "item_origin_profile_sha256": resolution.item_origin_profile_sha256,
                "extraction_acceptance_id": resolution.extraction_acceptance_id,
                "extraction_acceptance_sha256": resolution.extraction_acceptance_sha256,
                "assessment_source_bundle_id": resolution.assessment_source_bundle_id,
                "assessment_source_bundle_revision_id": (
                    resolution.assessment_source_bundle_revision_id
                ),
                "assessment_source_bundle_sha256": (resolution.assessment_source_bundle_sha256),
                "assessment_occurrence_id": resolution.assessment_occurrence_id,
                "assessment_occurrence_revision_id": (resolution.assessment_occurrence_revision_id),
                "assessment_occurrence_revision_sha256": (
                    resolution.assessment_occurrence_revision_sha256
                ),
                "occurrence_display_label": resolution.occurrence_display_label,
                "administration_year": resolution.administration_year,
                "administration_month": resolution.administration_month,
                "target_school_level": resolution.target_school_level,
                "target_grade": resolution.target_grade,
                "subject_key": resolution.subject_key,
                "item_number": resolution.item_number,
                "curriculum_unit_ids": list(alignment.curriculum_unit_ids),
                "placement_sha256": "sha256:" + "0" * 64,
            }
            value["placement_sha256"] = content_sha256(
                {key: item for key, item in value.items() if key != "placement_sha256"}
            )
            bindings.append(AssessmentOccurrenceItemBinding.model_validate(value))
        return tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.administration_year,
                    item.administration_month,
                    item.target_school_level,
                    item.target_grade,
                    item.assessment_occurrence_revision_id,
                    item.item_number,
                    item.item_revision_id,
                ),
            )
        )

    def _retrieval_command(
        self,
        *,
        context: CurrentKnowledgeGraphStructure,
        candidate: LegacyItemGraphCandidate,
        topic_keys: tuple[str, ...],
    ) -> CreateEvidenceBundleCommand:
        return build_automatic_item_alignment_retrieval_command(
            context=context,
            candidate=AutomaticItemGraphCandidate(
                analysis_run_id=candidate.analysis_run_id,
                requested_by_operator_id=candidate.requested_by_operator_id,
                graph_snapshot_revision_id=candidate.graph_snapshot_revision_id,
            ),
            topic_keys=topic_keys,
            access_policy_revision_id=self.access_policy_revision_id,
            idempotency_namespace="legacy-auto-alignment",
        )
