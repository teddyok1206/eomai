"""Legacy selection and occurrence provenance for shared Item Graph publication."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
    ApprovedItemKnowledgeSourceV2,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    CreateEvidenceBundleCommand,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, and_, literal, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
    build_automatic_item_alignment_retrieval_command,
)
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRevisionRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
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
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemRevisionRecord

MAX_AUTOMATIC_GRAPH_BATCH_SIZE = 16


@dataclass(frozen=True)
class LegacyItemGraphCandidate:
    analysis_run_id: str
    requested_by_operator_id: str
    graph_snapshot_revision_id: str


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
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionDecisionRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        with self.sessions() as session:
            rows = tuple(
                session.execute(
                    select(
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                        KnowledgeAnalysisRunRecord.created_by_operator_id,
                    )
                    .join(
                        ItemRevisionRecord,
                        ItemRevisionRecord.item_revision_id
                        == KnowledgeAnalysisRunRecord.source_revision_id,
                    )
                    .join(
                        ItemOriginProfileRecord,
                        ItemOriginProfileRecord.item_revision_id
                        == ItemRevisionRecord.item_revision_id,
                    )
                    .join(
                        ItemOriginOccurrenceRecord,
                        ItemOriginOccurrenceRecord.item_origin_profile_id
                        == ItemOriginProfileRecord.item_origin_profile_id,
                    )
                    .join(
                        AssessmentOccurrenceRevisionRecord,
                        AssessmentOccurrenceRevisionRecord.assessment_occurrence_revision_id
                        == ItemOriginOccurrenceRecord.assessment_occurrence_revision_id,
                    )
                    .join(
                        LegacyItemExtractionDecisionRecord,
                        ItemRevisionRecord.registration_key == registration_key,
                    )
                    .join(
                        LegacyItemExtractionBatchWorkUnitRecord,
                        LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                        == LegacyItemExtractionDecisionRecord.acceptance_id,
                    )
                    .join(
                        LegacyItemExtractionBatchRecord,
                        LegacyItemExtractionBatchRecord.extraction_batch_id
                        == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
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
                    .where(
                        LegacyItemExtractionBatchRecord.extraction_batch_id.in_(
                            self.extraction_batch_ids
                        ),
                        KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
                        KnowledgeAnalysisRunRecord.canonical_request["source"][
                            "source_class"
                        ].astext
                        == "PAST_EXAM",
                        KnowledgeAnalysisRunRecord.canonical_request["schema_version"].astext
                        == PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
                        KnowledgeAnalysisRunRecord.state == "ACCEPTED",
                        AssessmentOccurrenceRevisionRecord.schema_version
                        == "assessment-occurrence-revision/2.0",
                        ~and_(
                            AssessmentOccurrenceRevisionRecord.target_school_level == "HIGH_SCHOOL",
                            AssessmentOccurrenceRevisionRecord.target_grade == 1,
                            AssessmentOccurrenceRevisionRecord.administration_month == 3,
                        ),
                        KnowledgeSnapshotAnalysisRecord.analysis_run_id.is_(None),
                    )
                    .order_by(
                        LegacyItemExtractionBatchRecord.created_at,
                        LegacyItemExtractionBatchRecord.extraction_batch_id,
                        LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                        LegacyItemExtractionDecisionRecord.item_number,
                        KnowledgeAnalysisRunRecord.created_at,
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                    )
                    .limit(limit)
                )
            )
        return tuple(
            LegacyItemGraphCandidate(
                analysis_run_id=analysis_run_id,
                requested_by_operator_id=requested_by_operator_id,
                graph_snapshot_revision_id=context.graph_snapshot_revision_id,
            )
            for analysis_run_id, requested_by_operator_id in rows
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
            occurrence_binding_resolver=self._assessment_item_occurrence_bindings,
        )
        return receipt.graph_publication.graph_snapshot.graph_snapshot_revision_id

    @staticmethod
    def _assessment_item_occurrence_bindings(
        session: Session,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        alignments: tuple[AutomaticItemCurriculumAlignmentBinding, ...],
    ) -> tuple[AssessmentOccurrenceItemBinding, ...]:
        """Resolve new PAST_EXAM analyses into immutable placement values in bulk."""

        analysis_by_revision = {
            analysis.source.item_revision_id: analysis
            for analysis in analyses
            if isinstance(analysis.source, ApprovedItemKnowledgeSourceV2)
            and analysis.source.source_class == "PAST_EXAM"
        }
        alignment_by_revision = {alignment.item_revision_id: alignment for alignment in alignments}
        revision_ids = set(analysis_by_revision)
        if not revision_ids or revision_ids != set(alignment_by_revision):
            raise ValueError("PAST_EXAM analyses and automatic alignments must match exactly")

        profiles_by_revision: dict[str, list[ItemOriginProfileRecord]] = {}
        for profile in session.scalars(
            select(ItemOriginProfileRecord).where(
                ItemOriginProfileRecord.item_revision_id.in_(revision_ids)
            )
        ):
            profiles_by_revision.setdefault(profile.item_revision_id, []).append(profile)
        profile_ids = {
            row.item_origin_profile_id for values in profiles_by_revision.values() for row in values
        }
        occurrences_by_profile: dict[str, list[ItemOriginOccurrenceRecord]] = {}
        for occurrence_link in session.scalars(
            select(ItemOriginOccurrenceRecord).where(
                ItemOriginOccurrenceRecord.item_origin_profile_id.in_(profile_ids)
            )
        ):
            occurrences_by_profile.setdefault(occurrence_link.item_origin_profile_id, []).append(
                occurrence_link
            )
        derivations_by_profile: dict[str, list[ItemOriginDerivationRecord]] = {}
        for derivation in session.scalars(
            select(ItemOriginDerivationRecord).where(
                ItemOriginDerivationRecord.item_origin_profile_id.in_(profile_ids),
                ItemOriginDerivationRecord.source_kind == "ASSESSMENT_SOURCE_BUNDLE_REVISION",
            )
        ):
            derivations_by_profile.setdefault(derivation.item_origin_profile_id, []).append(
                derivation
            )
        occurrence_revision_ids = {
            row.assessment_occurrence_revision_id
            for values in occurrences_by_profile.values()
            for row in values
        }
        occurrences = {
            row.assessment_occurrence_revision_id: row
            for row in session.scalars(
                select(AssessmentOccurrenceRevisionRecord).where(
                    AssessmentOccurrenceRevisionRecord.assessment_occurrence_revision_id.in_(
                        occurrence_revision_ids
                    )
                )
            )
        }
        bundle_revision_ids = {
            row.revision_id for values in derivations_by_profile.values() for row in values
        }
        bundles = {
            row.assessment_source_bundle_revision_id: row
            for row in session.scalars(
                select(AssessmentSourceBundleRevisionRecord).where(
                    AssessmentSourceBundleRevisionRecord.assessment_source_bundle_revision_id.in_(
                        bundle_revision_ids
                    )
                )
            )
        }
        decision_rows = tuple(
            session.execute(
                select(ItemRevisionRecord.item_revision_id, LegacyItemExtractionDecisionRecord)
                .join(
                    LegacyItemExtractionDecisionRecord,
                    ItemRevisionRecord.registration_key
                    == (
                        literal("legacy-item-promotion:")
                        + LegacyItemExtractionDecisionRecord.acceptance_id
                        + literal(":")
                        + LegacyItemExtractionDecisionRecord.item_proposal_id
                    ),
                )
                .where(ItemRevisionRecord.item_revision_id.in_(revision_ids))
            )
        )
        decisions_by_revision: dict[str, list[LegacyItemExtractionDecisionRecord]] = {}
        for item_revision_id, decision in decision_rows:
            decisions_by_revision.setdefault(item_revision_id, []).append(decision)
        acceptance_ids = {decision.acceptance_id for _, decision in decision_rows}
        acceptances = {
            row.acceptance_id: row
            for row in session.scalars(
                select(LegacyItemExtractionAcceptanceRecord).where(
                    LegacyItemExtractionAcceptanceRecord.acceptance_id.in_(acceptance_ids)
                )
            )
        }

        bindings: list[AssessmentOccurrenceItemBinding] = []
        for item_revision_id in sorted(revision_ids):
            analysis = analysis_by_revision[item_revision_id]
            source = analysis.source
            profiles = profiles_by_revision.get(item_revision_id, [])
            if not isinstance(source, ApprovedItemKnowledgeSourceV2) or len(profiles) != 1:
                raise ValueError("PAST_EXAM Item must have one origin profile")
            profile = profiles[0]
            occurrence_links = occurrences_by_profile.get(profile.item_origin_profile_id, [])
            derivations = derivations_by_profile.get(profile.item_origin_profile_id, [])
            decisions = decisions_by_revision.get(item_revision_id, [])
            if len(occurrence_links) != 1 or len(derivations) != 1 or len(decisions) != 1:
                raise ValueError("PAST_EXAM Item origin placement is not unique")
            occurrence_link = occurrence_links[0]
            derivation = derivations[0]
            decision = decisions[0]
            occurrence = occurrences.get(occurrence_link.assessment_occurrence_revision_id)
            bundle = bundles.get(derivation.revision_id)
            acceptance = acceptances.get(decision.acceptance_id)
            alignment = alignment_by_revision[item_revision_id]
            if (
                occurrence is None
                or bundle is None
                or acceptance is None
                or occurrence.schema_version != "assessment-occurrence-revision/2.0"
                or occurrence.administration_month is None
                or occurrence.target_school_level is None
                or occurrence.target_grade is None
                or decision.decision not in {"ACCEPT", "CORRECT_AND_ACCEPT"}
            ):
                raise ValueError("PAST_EXAM Item placement metadata is incomplete")
            value: dict[str, object] = {
                "analysis_run_id": analysis.analysis_run_id,
                "item_id": source.item_id,
                "item_revision_id": source.item_revision_id,
                "item_origin_profile_id": profile.item_origin_profile_id,
                "item_origin_profile_sha256": profile.profile_sha256,
                "extraction_acceptance_id": acceptance.acceptance_id,
                "extraction_acceptance_sha256": acceptance.acceptance_sha256,
                "assessment_source_bundle_id": bundle.assessment_source_bundle_id,
                "assessment_source_bundle_revision_id": (
                    bundle.assessment_source_bundle_revision_id
                ),
                "assessment_source_bundle_sha256": bundle.bundle_manifest_sha256,
                "assessment_occurrence_id": occurrence.assessment_occurrence_id,
                "assessment_occurrence_revision_id": (occurrence.assessment_occurrence_revision_id),
                "assessment_occurrence_revision_sha256": occurrence.revision_sha256,
                "occurrence_display_label": occurrence.display_label,
                "administration_year": occurrence.administration_year,
                "administration_month": occurrence.administration_month,
                "target_school_level": occurrence.target_school_level,
                "target_grade": occurrence.target_grade,
                "subject_key": occurrence.subject_key,
                "item_number": decision.item_number,
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
