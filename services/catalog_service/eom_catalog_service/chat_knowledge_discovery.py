"""Bounded Registry/Graph metadata reads using existing indexes, never source bytes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from eom_api_contracts.chat_knowledge import (
    ChatExactQuery,
    ChatExamPlacement,
    ChatExamQuery,
    ChatGraphSnapshot,
    ChatItemCard,
    ChatItemReference,
    ChatKnowledgeRequest,
    ChatKnowledgeSelection,
    ChatRecentQuery,
    ChatTopicQuery,
)
from eom_api_contracts.items import ItemApprovalView
from eom_catalog_contracts import INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY
from eom_catalog_contracts.chat_ranked_candidate_read import ChatRankedCandidateKey
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, Select, and_, case, exists, func, select, text, tuple_
from sqlalchemy.orm import Session, aliased

from eom_catalog_service.item_origin_models import ItemOriginProfileRecord
from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord as Placement,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeNodeTermRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord


class ChatDiscoveryError(ValueError):
    def __init__(self, status: int, code: str, title: str, detail: str) -> None:
        self.status, self.code, self.title, self.detail = status, code, title, detail
        super().__init__(code)


RevisionProjector = Callable[[Session, tuple[ItemRevisionRecord, ...]], dict[str, ItemApprovalView]]


@dataclass(frozen=True, slots=True)
class DiscoveryOrigin:
    item_revision_id: str
    item_id: str
    item_manifest_sha256: str
    source_domain: str


def discovery_origin_statement(ids: tuple[str, ...]) -> Select[tuple[str, str, str, str]]:
    return select(
        ItemOriginProfileRecord.item_revision_id,
        ItemOriginProfileRecord.item_id,
        ItemOriginProfileRecord.item_manifest_sha256,
        ItemOriginProfileRecord.source_domain,
    ).where(ItemOriginProfileRecord.item_revision_id.in_(ids))


def topic_source_statement(query: ChatTopicQuery, snapshot_id: str | None) -> Select[tuple[int]]:
    pointer = KnowledgeNodeSourcePointerRecord
    term = KnowledgeNodeTermRecord
    statement = (
        select(pointer.pointer_id)
        .join(
            term,
            (term.graph_snapshot_revision_id == pointer.graph_snapshot_revision_id)
            & (term.node_id == pointer.node_id),
        )
        .where(
            pointer.graph_snapshot_revision_id == snapshot_id,
            pointer.source_class.in_(("PAST_EXAM", "APPROVED_ITEM")),
            term.term.in_(query.terms),
        )
    )
    if query.source != "ALL":
        statement = statement.where(
            pointer.source_class
            == ("PAST_EXAM" if query.source == "PAST_EXAM" else "APPROVED_ITEM")
        )
    return statement


def candidate_statement(
    request: ChatKnowledgeRequest,
    snapshot_id: str | None,
    *,
    ranked_candidates: tuple[ChatRankedCandidateKey, ...] | None = None,
) -> Select[tuple[ItemRecord, ItemRevisionRecord]]:
    """Keep filtering inside SQL, before top-K; no unrestricted title/count side channel."""

    query = request.query
    if ranked_candidates is not None and not isinstance(query, ChatTopicQuery):
        raise ValueError("ranked metadata is TOPIC-only")
    join_key = (
        ItemRevisionRecord.item_id == ItemRecord.item_id
        if isinstance(query, ChatExactQuery)
        else ItemRevisionRecord.item_revision_id == ItemRecord.current_revision_id
    )
    statement = (
        select(ItemRecord, ItemRevisionRecord)
        .join(
            ItemRevisionRecord,
            join_key
            if ranked_candidates is None
            else and_(join_key, ItemRevisionRecord.item_id == ItemRecord.item_id),
        )
        .where(
            ItemRecord.lifecycle_state == "ACTIVE",
            ItemRevisionRecord.revision_state.in_(("IN_REVIEW", "APPROVED")),
        )
    )
    if isinstance(query, ChatExactQuery):
        return statement.where(
            ItemRevisionRecord.item_revision_id.in_(
                ref.item_revision_id for ref in query.references
            )
        ).limit(6)
    if isinstance(query, ChatExamQuery):
        exam_conditions = [
            Placement.graph_snapshot_revision_id == snapshot_id,
            Placement.item_revision_id == ItemRevisionRecord.item_revision_id,
            Placement.administration_year == query.administration_year,
            Placement.administration_month == query.administration_month,
            Placement.target_school_level == query.target_school_level,
            Placement.target_grade == query.target_grade,
            Placement.subject_key == query.subject_key,
        ]
        if query.item_number is not None:
            exam_conditions.append(Placement.item_number == query.item_number)
        statement = statement.where(exists().where(*exam_conditions)).order_by(
            select(func.min(Placement.item_number)).where(*exam_conditions).scalar_subquery()
        )
    elif isinstance(query, ChatTopicQuery):
        # Only item metadata discovery is authorized here. Document/answer-bearing
        # excerpts and Graph node labels are not projected into these cards.
        pointer = KnowledgeNodeSourcePointerRecord
        matches = topic_source_statement(query, snapshot_id).where(
            pointer.source_revision_id == ItemRevisionRecord.item_revision_id
        )
        if ranked_candidates is not None:
            matches = matches.where(
                tuple_(
                    pointer.source_revision_id,
                    pointer.source_class,
                    pointer.source_artifact_id,
                    pointer.artifact_revision_id,
                    pointer.source_sha256,
                ).in_(
                    tuple(
                        (
                            key.item_revision_id,
                            key.source_class,
                            key.component_artifact_id,
                            key.component_artifact_revision_id,
                            key.component_sha256,
                        )
                        for key in ranked_candidates
                    )
                )
            )
        statement = statement.where(matches.exists())
    if isinstance(query, (ChatRecentQuery, ChatTopicQuery)) and query.source == "GENERATED":
        statement = statement.where(
            select(ItemOriginProfileRecord.item_revision_id)
            .where(
                ItemOriginProfileRecord.item_revision_id == ItemRevisionRecord.item_revision_id,
                ItemOriginProfileRecord.source_domain == "INTERNAL_EOM",
            )
            .exists()
        )
    if ranked_candidates is not None:
        ranks = {key.item_revision_id: rank for rank, key in enumerate(ranked_candidates)}
        statement = statement.where(
            ItemRevisionRecord.item_revision_id.in_(tuple(ranks)),
            ItemRevisionRecord.revision_state == "APPROVED",
        )
        if ranks:
            statement = statement.order_by(case(ranks, value=ItemRevisionRecord.item_revision_id))
        return statement.order_by(ItemRecord.item_id).limit(request.limit + 1)
    return statement.order_by(ItemRecord.created_at.desc(), ItemRecord.item_id.desc()).limit(
        request.limit + 1
    )


def validate_ranked_candidate_relations(
    session: Session,
    keys: tuple[ChatRankedCandidateKey, ...],
    snapshot_id: str,
) -> None:
    """One indexed metadata join, not per-source file/report resolution or a read grant."""
    if not keys:
        return
    expected = {key.item_revision_id: key for key in keys}
    component = ItemComponentRecord
    association = KnowledgeSnapshotAnalysisRecord
    current_owner = aliased(ItemRevisionRecord)
    statement = (
        select(
            ItemRecord.item_id,
            ItemRecord.current_revision_id,
            ItemRecord.lifecycle_state,
            ItemRevisionRecord.item_revision_id,
            ItemRevisionRecord.revision_state,
            ItemRevisionRecord.manifest_sha256,
            current_owner.item_id,
        )
        .join(ItemRevisionRecord, ItemRevisionRecord.item_id == ItemRecord.item_id)
        .join(component, component.item_revision_id == ItemRevisionRecord.item_revision_id)
        .outerjoin(current_owner, current_owner.item_revision_id == ItemRecord.current_revision_id)
        .where(
            tuple_(
                component.item_revision_id,
                component.artifact_id,
                component.artifact_revision_id,
                component.sha256,
            ).in_(
                tuple(
                    (
                        key.item_revision_id,
                        key.component_artifact_id,
                        key.component_artifact_revision_id,
                        key.component_sha256,
                    )
                    for key in keys
                )
            )
        )
        .where(
            exists().where(
                association.graph_snapshot_revision_id == snapshot_id,
                association.source_kind == "APPROVED_ITEM_REVISION",
                association.source_revision_id == component.item_revision_id,
                association.source_artifact_id == component.artifact_id,
                association.source_artifact_revision_id == component.artifact_revision_id,
                association.source_sha256 == component.sha256,
            )
        )
    )
    found = set()
    for (
        item_id,
        current,
        lifecycle,
        revision,
        state,
        manifest_sha256,
        current_item_id,
    ) in session.execute(statement).tuples():
        key = expected.get(revision)
        if (
            key is None
            or key.item_id != item_id
            or current is None
            or current_item_id != item_id
            or lifecycle != "ACTIVE"
            or state not in {"APPROVED", "SUPERSEDED"}
        ):
            raise ChatDiscoveryError(
                409,
                "CHAT_KNOWLEDGE_POINTER_INVALID",
                "Invalid ranked source",
                "A pinned Item/component/Graph relation is not active or valid approved history.",
            )
        # This is the Registry manifest hash, not the analyzed component hash.
        ChatItemReference(
            item_id=item_id, item_revision_id=revision, manifest_sha256=manifest_sha256
        )
        found.add(revision)
    if found != set(expected):
        raise ChatDiscoveryError(
            409,
            "CHAT_KNOWLEDGE_POINTER_INVALID",
            "Invalid ranked source",
            "A pinned Item/component/Graph relation is missing or differs.",
        )


class ChatKnowledgeQueryAdapter:
    def __init__(self, engine: Engine, project_revisions: RevisionProjector) -> None:
        self.sessions = build_session_factory(engine)
        self.project_revisions = project_revisions

    def search(
        self, request: ChatKnowledgeRequest, *, actor_id: str | None = None
    ) -> ChatKnowledgeSelection:
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            return self.search_in_session(session, request, actor_id=actor_id)

    def search_in_session(
        self,
        session: Session,
        request: ChatKnowledgeRequest,
        *,
        actor_id: str | None,
        ranked_candidates: tuple[ChatRankedCandidateKey, ...] | None = None,
    ) -> ChatKnowledgeSelection:
        """Reuse current discovery inside its caller's authorized read-only transaction."""
        if actor_id is not None:
            actor = session.get(OperatorRecord, actor_id)
            if (
                actor is None
                or actor.status != "ACTIVE"
                or actor.deleted_at is not None
                or actor.must_change_password
                or not {PermissionKey.GENERAL_CHAT_READ, PermissionKey.ITEM_READ}
                <= effective_permissions(session, actor_id)
            ):
                raise ChatDiscoveryError(
                    403,
                    "CHAT_KNOWLEDGE_FORBIDDEN",
                    "Permission denied",
                    "Chat and Item read permission are required",
                )
        snapshot = self._snapshot(session, request.snapshot)
        snapshot_id = snapshot.graph_snapshot_revision_id if snapshot else None
        if ranked_candidates is not None:
            if (
                actor_id is None
                or snapshot_id is None
                or not isinstance(request.query, ChatTopicQuery)
            ):
                raise ChatDiscoveryError(
                    403,
                    "CHAT_KNOWLEDGE_FORBIDDEN",
                    "Permission denied",
                    "Ranked discovery requires an actual actor and exact TOPIC scope.",
                )
            validate_ranked_candidate_relations(session, ranked_candidates, snapshot_id)
        if snapshot is None and isinstance(request.query, (ChatExamQuery, ChatTopicQuery)):
            raise ChatDiscoveryError(
                503,
                "CHAT_KNOWLEDGE_GRAPH_UNAVAILABLE",
                "Graph unavailable",
                "No published discovery graph is available.",
            )
        if isinstance(request.query, ChatTopicQuery):
            missing_statement = (
                topic_source_statement(request.query, snapshot_id)
                .outerjoin(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeNodeSourcePointerRecord.source_revision_id,
                )
                .where(ItemRevisionRecord.item_revision_id.is_(None))
                .limit(1)
            )
            if ranked_candidates is not None:
                missing_statement = missing_statement.where(
                    KnowledgeNodeSourcePointerRecord.source_revision_id.in_(
                        tuple(key.item_revision_id for key in ranked_candidates)
                    )
                )
            missing = session.scalar(missing_statement)
            if missing is not None:
                raise ChatDiscoveryError(
                    503,
                    "CHAT_KNOWLEDGE_POINTER_INVALID",
                    "Dangling Graph source",
                    "A matched Item source revision is missing from the Registry.",
                )
        rows = tuple(
            session.execute(
                candidate_statement(request, snapshot_id, ranked_candidates=ranked_candidates)
            ).tuples()
        )
        if any(item.item_id != revision.item_id for item, revision in rows):
            raise ChatDiscoveryError(
                503,
                "CHAT_KNOWLEDGE_POINTER_INVALID",
                "Invalid Item pointer",
                "Current revision does not belong to its Item.",
            )
        indexed = {revision.item_revision_id: (item, revision) for item, revision in rows}
        if isinstance(request.query, ChatExactQuery):
            for ref in request.query.references:
                pair = indexed.get(ref.item_revision_id)
                if pair is None or pair[0].item_id != ref.item_id:
                    raise ChatDiscoveryError(
                        404,
                        "CHAT_KNOWLEDGE_ITEM_UNAVAILABLE",
                        "Item unavailable",
                        "The pinned Item revision is missing or no longer eligible.",
                    )
                if pair[1].manifest_sha256 != ref.manifest_sha256:
                    raise ChatDiscoveryError(
                        409,
                        "CHAT_KNOWLEDGE_HASH_MISMATCH",
                        "Hash mismatch",
                        "The pinned Item manifest hash does not match.",
                    )
            rows = tuple(indexed[ref.item_revision_id] for ref in request.query.references)
        truncated = len(rows) > request.limit
        rows = rows[: request.limit]
        revisions = tuple(revision for _, revision in rows)
        approvals = self.project_revisions(session, revisions)
        ids = tuple(indexed_id.item_revision_id for indexed_id in revisions)
        origins = (
            {
                revision_id: DiscoveryOrigin(revision_id, item_id, manifest_sha256, domain)
                for revision_id, item_id, manifest_sha256, domain in session.execute(
                    discovery_origin_statement(ids)
                ).tuples()
            }
            if ids
            else {}
        )
        placements: dict[str, list[Placement]] = {}
        membership: set[str] = set()
        if snapshot_id is not None and ids:
            # A Graph source hash is the analyzed component member's hash,
            # not the Item manifest hash. Keep these independent identities.
            components = {
                (
                    component.item_revision_id,
                    component.artifact_id,
                    component.artifact_revision_id,
                    component.sha256,
                )
                for component in session.scalars(
                    select(ItemComponentRecord).where(ItemComponentRecord.item_revision_id.in_(ids))
                )
            }
            for row in session.scalars(
                select(Placement)
                .where(
                    Placement.graph_snapshot_revision_id == snapshot_id,
                    Placement.item_revision_id.in_(ids),
                )
                .order_by(Placement.item_number, Placement.assessment_occurrence_revision_id)
            ):
                placements.setdefault(row.item_revision_id, []).append(row)
            for analysis in session.scalars(
                select(KnowledgeSnapshotAnalysisRecord).where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
                    KnowledgeSnapshotAnalysisRecord.source_revision_id.in_(ids),
                )
            ):
                if (
                    analysis.source_revision_id,
                    analysis.source_artifact_id,
                    analysis.source_artifact_revision_id,
                    analysis.source_sha256,
                ) not in components:
                    raise ChatDiscoveryError(
                        503,
                        "CHAT_KNOWLEDGE_POINTER_INVALID",
                        "Invalid graph pointer",
                        "Discovery graph source and Registry component disagree.",
                    )
                membership.add(analysis.source_revision_id)
        cards: list[ChatItemCard] = []
        for item, revision in rows:
            approval = approvals[revision.item_revision_id]
            origin = origins.get(revision.item_revision_id)
            if origin is not None and (
                origin.item_id != item.item_id
                or origin.item_manifest_sha256 != revision.manifest_sha256
            ):
                raise ChatDiscoveryError(
                    503,
                    "CHAT_KNOWLEDGE_POINTER_INVALID",
                    "Invalid origin pointer",
                    "Item origin and Registry manifest disagree.",
                )
            exams = placements.get(revision.item_revision_id, [])
            source: Literal["PAST_EXAM", "GENERATED", "UNCLASSIFIED"] = (
                "PAST_EXAM"
                if exams
                else "GENERATED"
                if origin is not None and origin.source_domain == "INTERNAL_EOM"
                else "UNCLASSIFIED"
            )
            if isinstance(request.query, ChatExamQuery):
                query = request.query
                exams = [
                    exam
                    for exam in exams
                    if (
                        exam.administration_year == query.administration_year
                        and exam.administration_month == query.administration_month
                        and exam.target_school_level == query.target_school_level
                        and exam.target_grade == query.target_grade
                        and exam.subject_key == query.subject_key
                        and (query.item_number is None or exam.item_number == query.item_number)
                    )
                ]
            card_exams: list[Placement | None] = list(exams) if exams else [None]
            if ranked_candidates is not None:
                card_exams = card_exams[:1]
            for exam in card_exams:
                if exam is not None and exam.item_id != item.item_id:
                    raise ChatDiscoveryError(
                        503,
                        "CHAT_KNOWLEDGE_POINTER_INVALID",
                        "Invalid placement",
                        "Exam placement and Item identity disagree.",
                    )
                if exam is not None:
                    display_name = f"{exam.occurrence_display_label} · {exam.item_number}번"
                elif item.human_reference_code:
                    display_name = item.human_reference_code
                else:
                    display_name = "제작 문항" if source == "GENERATED" else "문항"
                cards.append(
                    ChatItemCard(
                        item_id=item.item_id,
                        item_revision_id=revision.item_revision_id,
                        manifest_sha256=revision.manifest_sha256,
                        revision_number=revision.revision_number,
                        display_name=display_name,
                        created_at=revision.created_at,
                        approval=approval,
                        source_kind=source,
                        graph_membership=(
                            "UNAVAILABLE"
                            if snapshot is None
                            else "INDEXED"
                            if revision.item_revision_id in membership
                            else "NOT_INDEXED"
                        ),
                        exam=(
                            ChatExamPlacement(
                                assessment_occurrence_revision_id=exam.assessment_occurrence_revision_id,
                                display_label=exam.occurrence_display_label,
                                item_number=exam.item_number,
                            )
                            if exam
                            else None
                        ),
                    )
                )
        if isinstance(request.query, ChatExamQuery):
            cards.sort(
                key=lambda card: (
                    card.exam.item_number if card.exam else 0,
                    card.exam.assessment_occurrence_revision_id if card.exam else "",
                    card.item_revision_id,
                )
            )
        return ChatKnowledgeSelection(
            values=tuple(cards[: request.limit]),
            snapshot=snapshot,
            truncated=truncated or len(cards) > request.limit,
        )

    @staticmethod
    def _snapshot(session: Session, pin: ChatGraphSnapshot | None) -> ChatGraphSnapshot | None:
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
                KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
            )
        )
        snapshot_id = (
            pin.graph_snapshot_revision_id
            if pin
            else corpus.current_graph_snapshot_revision_id
            if corpus
            else None
        )
        if snapshot_id is None:
            if pin is not None:
                raise ChatDiscoveryError(
                    404,
                    "CHAT_KNOWLEDGE_SNAPSHOT_UNAVAILABLE",
                    "Snapshot unavailable",
                    "The pinned discovery corpus is unavailable.",
                )
            return None
        row = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
        if (
            corpus is None
            or row is None
            or row.graph_id != corpus.graph_id
            or row.state != "PUBLISHED"
            or row.ontology_version != "education-knowledge-graph/1.1"
        ):
            raise ChatDiscoveryError(
                404,
                "CHAT_KNOWLEDGE_SNAPSHOT_UNAVAILABLE",
                "Snapshot unavailable",
                "The exact discovery snapshot is missing or unsupported.",
            )
        if pin is not None and pin.snapshot_sha256 != row.snapshot_sha256:
            raise ChatDiscoveryError(
                409,
                "CHAT_KNOWLEDGE_HASH_MISMATCH",
                "Hash mismatch",
                "The pinned graph hash does not match.",
            )
        return ChatGraphSnapshot(
            graph_snapshot_revision_id=row.graph_snapshot_revision_id,
            snapshot_sha256=row.snapshot_sha256,
        )
