"""Shared evidence-bound publication for accepted Item knowledge analyses."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    CreateEvidenceBundleCommand,
    KnowledgeGraphPublicationResult,
    PublishKnowledgeGraphSnapshotCommandV5,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select
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
from eom_catalog_service.knowledge_graph_models import EvidenceBundleEntryRecord
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
)

INTEGRATED_SCIENCE_CORPUS_KEY = "integrated-science-textbooks"
MAX_AUTOMATIC_GRAPH_BATCH_SIZE = 25
_ACCESS_POLICY_REVISION_ID = re.compile(r"\Aaccessrev_[0-9a-f]{32}\Z", re.ASCII)
_IDEMPOTENCY_NAMESPACE = re.compile(r"\A[a-z][a-z0-9-]{2,31}\Z", re.ASCII)

AnalysisValidator = Callable[
    [Session, tuple[AcceptedAnalysisProposal, ...]],
    None,
]
AlignmentValidator = Callable[
    [tuple[AutomaticItemCurriculumAlignmentBinding, ...]],
    None,
]
OccurrenceBindingResolver = Callable[
    [
        Session,
        tuple[AcceptedAnalysisProposal, ...],
        tuple[AutomaticItemCurriculumAlignmentBinding, ...],
    ],
    tuple[AssessmentOccurrenceItemBinding, ...],
]


@dataclass(frozen=True)
class AutomaticItemGraphCandidate:
    analysis_run_id: str
    requested_by_operator_id: str
    graph_snapshot_revision_id: str


@dataclass(frozen=True)
class AutomaticItemGraphPublicationReceipt:
    graph_publication: KnowledgeGraphPublicationResult
    alignments: tuple[AutomaticItemCurriculumAlignmentBinding, ...]


def build_automatic_item_alignment_retrieval_command(
    *,
    context: CurrentKnowledgeGraphStructure,
    candidate: AutomaticItemGraphCandidate,
    topic_keys: tuple[str, ...],
    access_policy_revision_id: str,
    idempotency_namespace: str,
) -> CreateEvidenceBundleCommand:
    """Build the deterministic Graph-RAG retrieval request shared by both publishers."""

    if candidate.graph_snapshot_revision_id != context.graph_snapshot_revision_id:
        raise ValueError("automatic Graph retrieval candidate is stale")
    if _ACCESS_POLICY_REVISION_ID.fullmatch(access_policy_revision_id) is None:
        raise ValueError("automatic Graph access policy revision identity is invalid")
    if _IDEMPOTENCY_NAMESPACE.fullmatch(idempotency_namespace) is None:
        raise ValueError("automatic Graph retrieval idempotency namespace is invalid")
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
        "access_policy_revision_id": access_policy_revision_id,
        "requester_role": "ADMIN",
        "requester_permission_keys": list(AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS),
        "requested_by": candidate.requested_by_operator_id,
        "idempotency_key": (
            f"{idempotency_namespace}:{candidate.analysis_run_id}:"
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


class AutomaticItemGraphPublicationService:
    """Append a bounded Item-analysis set through one shared Graph publication path."""

    def __init__(
        self,
        engine: Engine,
        *,
        access_policy_revision_id: str,
        publication: KnowledgeGraphPublicationService | None = None,
        retrieval: KnowledgeRetrievalApplicationService | None = None,
    ) -> None:
        if _ACCESS_POLICY_REVISION_ID.fullmatch(access_policy_revision_id) is None:
            raise ValueError("automatic Graph access policy revision identity is invalid")
        self.sessions = build_session_factory(engine)
        self.access_policy_revision_id = access_policy_revision_id
        self.publication = publication or KnowledgeGraphPublicationService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)

    def publish(
        self,
        candidates: tuple[AutomaticItemGraphCandidate, ...],
        *,
        required_source_class: Literal["APPROVED_ITEM", "PAST_EXAM"],
        retrieval_idempotency_namespace: str,
        publication_idempotency_namespace: str,
        publisher_version: str,
        publication_idempotency_key: str | None = None,
        publication_authorized_at: datetime | None = None,
        analysis_validator: AnalysisValidator | None = None,
        alignment_validator: AlignmentValidator | None = None,
        occurrence_binding_resolver: OccurrenceBindingResolver | None = None,
    ) -> AutomaticItemGraphPublicationReceipt:
        """Publish the exact candidate tuple without implicit latest-revision substitution."""

        if not candidates or len(candidates) > MAX_AUTOMATIC_GRAPH_BATCH_SIZE:
            raise ValueError("automatic Graph publication candidate set is empty or too large")
        if (
            _IDEMPOTENCY_NAMESPACE.fullmatch(retrieval_idempotency_namespace) is None
            or _IDEMPOTENCY_NAMESPACE.fullmatch(publication_idempotency_namespace) is None
        ):
            raise ValueError("automatic Graph publication idempotency namespace is invalid")
        if publication_idempotency_key is not None and not (
            8 <= len(publication_idempotency_key) <= 128
            and all(0x21 <= ord(character) <= 0x7E for character in publication_idempotency_key)
        ):
            raise ValueError("automatic Graph publication idempotency key is invalid")
        context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
        candidate_ids = tuple(candidate.analysis_run_id for candidate in candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("automatic Graph publication candidates are duplicate")
        if any(
            candidate.graph_snapshot_revision_id != context.graph_snapshot_revision_id
            for candidate in candidates
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_STALE_CURRENT",
                "knowledge corpus changed before automatic publication",
            )
        if set(candidate_ids).intersection(context.accepted_analysis_run_ids):
            raise ValueError("automatic Graph publication candidate already belongs to the Graph")

        with self.publication.sessions() as session:
            analyses_by_id = {
                candidate.analysis_run_id: self.publication._load_accepted_analysis(
                    session, candidate.analysis_run_id
                )
                for candidate in candidates
            }
        analyses = tuple(analyses_by_id[candidate_id] for candidate_id in candidate_ids)
        item_revision_ids: list[str] = []
        for analysis in analyses:
            source = analysis.source
            if (
                not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or source.source_class != required_source_class
            ):
                raise ValueError(
                    "automatic Graph publication candidate has an incompatible Item source class"
                )
            item_revision_ids.append(source.item_revision_id)
        if len(item_revision_ids) != len(set(item_revision_ids)):
            raise ValueError("automatic Graph publication candidates duplicate an Item Revision")
        existing_item_revision_ids = {
            binding.item_revision_id
            for attribute in (
                "approved_item_curriculum_bindings",
                "automatic_item_curriculum_bindings",
            )
            for binding in getattr(context.structure, attribute, ())
        }
        if set(item_revision_ids).intersection(existing_item_revision_ids):
            raise ValueError("automatic Graph publication Item Revision already belongs to Graph")
        if required_source_class == "PAST_EXAM" and occurrence_binding_resolver is None:
            raise ValueError("PAST_EXAM Graph publication requires occurrence bindings")
        if required_source_class == "APPROVED_ITEM" and occurrence_binding_resolver is not None:
            raise ValueError("APPROVED_ITEM Graph publication cannot add exam occurrences")
        if analysis_validator is not None:
            with self.sessions() as session:
                analysis_validator(session, analyses)

        additions: list[AutomaticItemCurriculumAlignmentBinding] = []
        for candidate in candidates:
            analysis = analyses_by_id[candidate.analysis_run_id]
            topics = automatic_item_alignment_topic_keys(
                (str(node.node_type), node.stable_key) for node in analysis.proposal.nodes
            )
            evidence = self.retrieval.create(
                build_automatic_item_alignment_retrieval_command(
                    context=context,
                    candidate=candidate,
                    topic_keys=topics,
                    access_policy_revision_id=self.access_policy_revision_id,
                    idempotency_namespace=retrieval_idempotency_namespace,
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
            source = analysis.source
            if not isinstance(source, ApprovedItemKnowledgeSourceV2):  # pragma: no cover
                raise AssertionError("validated Item analysis source changed unexpectedly")
            value = {
                "alignment_mode": "AUTO_POLICY",
                "analysis_run_id": candidate.analysis_run_id,
                "item_id": source.item_id,
                "item_revision_id": source.item_revision_id,
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

        ordered_additions = tuple(additions)
        if alignment_validator is not None:
            # The caller-specific semantic gate runs before the structure artifact or Graph
            # publication is committed. Retrieval evidence may be reused by an exact retry.
            alignment_validator(ordered_additions)
        requested_at = max(binding.aligned_at for binding in ordered_additions)
        occurrence_bindings: tuple[AssessmentOccurrenceItemBinding, ...] = ()
        if occurrence_binding_resolver is not None:
            with self.sessions() as session:
                occurrence_bindings = occurrence_binding_resolver(
                    session,
                    analyses,
                    ordered_additions,
                )
        structure = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
            context.structure,
            ordered_additions,
            created_at=requested_at,
            assessment_item_occurrences=occurrence_bindings,
        )
        structure_pointer = self.publication.commit_structure_manifest(structure)
        all_run_ids = tuple(sorted({*context.accepted_analysis_run_ids, *candidate_ids}))
        request_value: dict[str, object] = {
            "schema_version": "knowledge-graph-publication/5.0",
            "corpus_key": context.corpus_key,
            "display_name": context.display_name,
            "accepted_analysis_run_ids": list(all_run_ids),
            "structure_manifest": structure_pointer.model_dump(mode="json"),
            "expected_current_snapshot_revision_id": context.graph_snapshot_revision_id,
            "publisher_version": publisher_version,
            "published_by_operator_id": candidates[0].requested_by_operator_id,
            "idempotency_key": publication_idempotency_key
            or (
                f"{publication_idempotency_namespace}:"
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
        graph_publication = self.publication.publish(
            PublishKnowledgeGraphSnapshotCommandV5.model_validate(request_value),
            authorized_at=publication_authorized_at,
        )
        return AutomaticItemGraphPublicationReceipt(
            graph_publication=graph_publication,
            alignments=ordered_additions,
        )
