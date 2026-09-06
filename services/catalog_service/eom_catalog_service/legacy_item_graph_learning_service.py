"""Automatic, evidence-bound publication of accepted legacy Item analyses into Graph RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    CreateEvidenceBundleCommand,
    PublishKnowledgeGraphSnapshotCommandV5,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, and_, literal, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_curriculum_alignment import (
    AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
    AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS,
    AUTOMATIC_ITEM_ALIGNMENT_POLICY_SHA256,
    AUTOMATIC_ITEM_ALIGNMENT_POLICY_VERSION,
    AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES,
    automatic_item_alignment_topic_keys,
    derive_automatic_item_curriculum_unit_ids,
)
from eom_catalog_service.curriculum_graph_structure import (
    extend_integrated_science_structure_manifest_with_automatic_item_alignments,
)
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRevisionRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
)
from eom_catalog_service.knowledge_graph_models import (
    EvidenceBundleEntryRecord,
    KnowledgeSnapshotAnalysisRecord,
)
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

INTEGRATED_SCIENCE_CORPUS_KEY = "integrated-science-textbooks"
MAX_AUTOMATIC_GRAPH_BATCH_SIZE = 16
_ACCESS_POLICY_REVISION_ID = re.compile(r"\Aaccessrev_[0-9a-f]{32}\Z", re.ASCII)


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
        if _ACCESS_POLICY_REVISION_ID.fullmatch(access_policy_revision_id) is None:
            raise ValueError("automatic Graph access policy revision identity is invalid")
        self.sessions = build_session_factory(engine)
        self.extraction_batch_ids = extraction_batch_ids
        self.access_policy_revision_id = access_policy_revision_id
        self.publication = publication or KnowledgeGraphPublicationService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)

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

        if not candidates or len(candidates) > MAX_AUTOMATIC_GRAPH_BATCH_SIZE:
            raise ValueError("automatic Graph publication candidate set is empty or too large")
        context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
        candidate_ids = tuple(candidate.analysis_run_id for candidate in candidates)
        if len(candidate_ids) != len(set(candidate_ids)) or any(
            candidate.graph_snapshot_revision_id != context.graph_snapshot_revision_id
            for candidate in candidates
        ):
            raise ValueError("automatic Graph publication candidates are duplicate or stale")

        additions: list[AutomaticItemCurriculumAlignmentBinding] = []
        with self.publication.sessions() as session:
            analyses = {
                candidate.analysis_run_id: self.publication._load_accepted_analysis(
                    session, candidate.analysis_run_id
                )
                for candidate in candidates
            }
        for candidate in candidates:
            analysis = analyses[candidate.analysis_run_id]
            if not isinstance(analysis.source, ApprovedItemKnowledgeSourceV2):
                raise ValueError("automatic Graph publication candidate is not an approved Item")
            topics = automatic_item_alignment_topic_keys(
                (str(node.node_type), node.stable_key) for node in analysis.proposal.nodes
            )
            evidence = self.retrieval.create(
                self._retrieval_command(
                    context=context,
                    candidate=candidate,
                    topic_keys=topics,
                )
            )
            with self.sessions() as session:
                entries = tuple(
                    session.scalars(
                        select(EvidenceBundleEntryRecord)
                        .where(
                            EvidenceBundleEntryRecord.evidence_bundle_revision_id
                            == evidence.evidence_bundle_revision_id
                        )
                        .order_by(EvidenceBundleEntryRecord.evidence_id)
                    )
                )
                evidence_node_ids = tuple(
                    sorted({node_id for entry in entries for node_id in entry.graph_node_ids})
                )
                curriculum_unit_ids = derive_automatic_item_curriculum_unit_ids(
                    session,
                    graph_snapshot_revision_id=context.graph_snapshot_revision_id,
                    evidence_node_ids=evidence_node_ids,
                )
            value = {
                "alignment_mode": "AUTO_POLICY",
                "analysis_run_id": candidate.analysis_run_id,
                "item_id": analysis.source.item_id,
                "item_revision_id": analysis.source.item_revision_id,
                "accepted_result": analysis.accepted_result.model_dump(mode="json"),
                "prior_graph_snapshot_revision_id": context.graph_snapshot_revision_id,
                "evidence_bundle_id": evidence.evidence_bundle_id,
                "evidence_bundle_revision_id": evidence.evidence_bundle_revision_id,
                "retrieval_request_id": evidence.retrieval_request_id,
                "retrieval_request_sha256": evidence.retrieval_request_sha256,
                "evidence_manifest": evidence.manifest_artifact.model_dump(mode="json"),
                "evidence_node_ids": list(evidence_node_ids),
                "curriculum_unit_ids": list(curriculum_unit_ids),
                "alignment_policy_version": AUTOMATIC_ITEM_ALIGNMENT_POLICY_VERSION,
                "alignment_policy_sha256": AUTOMATIC_ITEM_ALIGNMENT_POLICY_SHA256,
                "requested_by_operator_id": candidate.requested_by_operator_id,
                "aligned_at": evidence.published_at.isoformat().replace("+00:00", "Z"),
                "alignment_sha256": "sha256:" + "0" * 64,
            }
            value["alignment_sha256"] = content_sha256(
                {key: item for key, item in value.items() if key != "alignment_sha256"}
            )
            additions.append(AutomaticItemCurriculumAlignmentBinding.model_validate(value))

        requested_at = max(binding.aligned_at for binding in additions)
        with self.sessions() as session:
            occurrence_bindings = self._assessment_item_occurrence_bindings(
                session,
                tuple(analyses[candidate.analysis_run_id] for candidate in candidates),
                tuple(additions),
            )
        structure = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
            context.structure,
            tuple(additions),
            created_at=requested_at,
            assessment_item_occurrences=occurrence_bindings,
        )
        structure_pointer = self.publication.commit_structure_manifest(structure)
        all_run_ids = tuple(
            sorted(
                {*context.accepted_analysis_run_ids, *(item.analysis_run_id for item in additions)}
            )
        )
        request_value: dict[str, object] = {
            "schema_version": "knowledge-graph-publication/5.0",
            "corpus_key": context.corpus_key,
            "display_name": context.display_name,
            "accepted_analysis_run_ids": list(all_run_ids),
            "structure_manifest": structure_pointer.model_dump(mode="json"),
            "expected_current_snapshot_revision_id": context.graph_snapshot_revision_id,
            "publisher_version": "1.6.0",
            "published_by_operator_id": candidates[0].requested_by_operator_id,
            "idempotency_key": (
                "legacy-auto-graph:"
                + content_sha256(
                    {
                        "prior": context.graph_snapshot_revision_id,
                        "analysis_run_ids": list(candidate_ids),
                    }
                ).removeprefix("sha256:")
            ),
            "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
            "request_sha256": "sha256:" + "0" * 64,
        }
        request_value["request_sha256"] = content_sha256(
            {key: item for key, item in request_value.items() if key != "request_sha256"}
        )
        result = self.publication.publish(
            PublishKnowledgeGraphSnapshotCommandV5.model_validate(request_value)
        )
        return result.graph_snapshot.graph_snapshot_revision_id

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
        if candidate.graph_snapshot_revision_id != context.graph_snapshot_revision_id:
            raise ValueError("automatic Graph retrieval candidate is stale")
        value: dict[str, object] = {
            "operation": "CREATE_EVIDENCE_BUNDLE",
            "graph_snapshot_revision_id": context.graph_snapshot_revision_id,
            "query_kind": "ITEM_PREPARATION",
            "curriculum_scope": None,
            "topic_keys": list(topic_keys),
            "target_item_revision_id": None,
            "required_item_elements": [],
            "source_classes": list(AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES),
            "evidence_budget": AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
            "access_policy_revision_id": self.access_policy_revision_id,
            "requester_role": "ADMIN",
            "requester_permission_keys": list(AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS),
            "requested_by": candidate.requested_by_operator_id,
            "idempotency_key": (
                f"legacy-auto-alignment:{candidate.analysis_run_id}:"
                f"{context.graph_snapshot_revision_id}"
            ),
            "submission_sha256": "sha256:" + "0" * 64,
        }
        value["submission_sha256"] = content_sha256(
            {
                key: item
                for key, item in value.items()
                if key not in {"idempotency_key", "submission_sha256"}
            }
        )
        return CreateEvidenceBundleCommand.model_validate(value)
