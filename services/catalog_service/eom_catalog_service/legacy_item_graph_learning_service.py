"""Automatic, evidence-bound publication of accepted legacy Item analyses into Graph RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AutomaticItemCurriculumAlignmentBinding,
    CreateEvidenceBundleCommand,
    PublishKnowledgeGraphSnapshotCommandV4,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, and_, literal, select

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
from eom_catalog_service.knowledge_graph_models import (
    EvidenceBundleEntryRecord,
    KnowledgeSnapshotAnalysisRecord,
)
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
                        KnowledgeAnalysisRunRecord.state == "ACCEPTED",
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
        structure = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
            context.structure,
            tuple(additions),
            created_at=requested_at,
        )
        structure_pointer = self.publication.commit_structure_manifest(structure)
        all_run_ids = tuple(
            sorted(
                {*context.accepted_analysis_run_ids, *(item.analysis_run_id for item in additions)}
            )
        )
        request_value: dict[str, object] = {
            "schema_version": "knowledge-graph-publication/4.0",
            "corpus_key": context.corpus_key,
            "display_name": context.display_name,
            "accepted_analysis_run_ids": list(all_run_ids),
            "structure_manifest": structure_pointer.model_dump(mode="json"),
            "expected_current_snapshot_revision_id": context.graph_snapshot_revision_id,
            "publisher_version": "1.5.0",
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
            PublishKnowledgeGraphSnapshotCommandV4.model_validate(request_value)
        )
        return result.graph_snapshot.graph_snapshot_revision_id

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
