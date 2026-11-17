"""Kakao concept evidence through the same authoring retrieval and textbook materializer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from eom_catalog_contracts import (
    ContentIntakeKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationRetrievalAccessPolicy,
    EvidenceBudget,
)
from eom_catalog_contracts.kakao_concept_knowledge import (
    KakaoConceptKnowledge,
    KakaoConceptTextbookPin,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.material_knowledge_analysis import EducationalDocumentKnowledgeSourceV5
from eom_identifiers import content_sha256
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptEvidenceContext,
    ConceptPlan,
    ConceptResult,
)
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.preset_model_selection import validated_preset
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy, ChatRagScope
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from .item_textbook_context import (
    ResolvedTextbookContext,
    TextbookContextSelection,
    resolve_item_textbook_context,
)
from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_binding_scope
from .kakao_concept_task_service import KakaoConceptSourceAuthority
from .knowledge_graph_models import KnowledgeCorpusRecord, KnowledgeGraphSnapshotRecord
from .knowledge_graph_projection import knowledge_node_terms
from .knowledge_graph_publication_service import KnowledgeGraphPublicationService
from .knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from .models import ContentIntakeSourceFileRecord, EducationalDocumentRevisionRecord
from .settings import CatalogSettings

if TYPE_CHECKING:
    from .kakao_concept_pages import PreparedConceptCapture, PreparedConceptPages

RequesterRole = Literal["ADMIN", "EDITOR", "REVIEWER"]


@dataclass(frozen=True, slots=True)
class ConceptTextbookMaterial:
    title: str
    graph_node_ids: tuple[str, ...]
    analysis: ResolvedTextbookContext

    def selection(self) -> TextbookContextSelection:
        return TextbookContextSelection(
            analysis_run_id=self.analysis.analysis_run_id,
            source=self.analysis.source,
            node_ids=self.graph_node_ids,
            anchor_ids=tuple(a.anchor_id for a in self.analysis.selected_anchors),
        )

    def pin(self) -> KakaoConceptTextbookPin:
        source = self.analysis.source
        if not isinstance(
            source,
            (
                ContentIntakeKnowledgeSourceV2,
                EducationalDocumentKnowledgeSourceV3,
                EducationalDocumentKnowledgeSourceV4,
                EducationalDocumentKnowledgeSourceV5,
            ),
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
        return KakaoConceptTextbookPin(
            title=self.title,
            analysis_run_id=self.analysis.analysis_run_id,
            source=source,
            node_ids=self.graph_node_ids,
            anchor_ids=tuple(anchor.anchor_id for anchor in self.analysis.selected_anchors),
            accepted_result=ArtifactMemberPointer.model_validate(
                self.analysis.accepted_result.model_dump(exclude={"logical_name"})
            ),
            normalized_markdown=self.analysis.normalized_markdown,
            analysis_text_sha256=sha256(self.analysis.approved_analysis_text.encode("utf-8")),
        )


@dataclass(frozen=True, slots=True)
class ResolvedConceptTextbookKnowledge:
    # Scope is an existing small Graph/policy value, not conversational execution authority.
    scope: ChatRagScope
    snapshot: KnowledgeGraphSnapshotPointer
    materials: tuple[ConceptTextbookMaterial, ...]

    def __post_init__(self) -> None:
        if (
            self.scope.snapshot.graph_snapshot_revision_id
            != self.snapshot.graph_snapshot_revision_id
            or len(self.materials) > 3
            or len({m.analysis.analysis_run_id for m in self.materials}) != len(self.materials)
            or any(m.analysis.source.source_class != "TEXTBOOK" for m in self.materials)
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")

    def worker_context(self) -> ConceptEvidenceContext:
        value = dict(
            schema_version="kakao-concept-evidence-context/1.0",
            evidence=[
                dict(
                    evidence_key=f"E{index}",
                    source_class="TEXTBOOK",
                    display_title=material.title,
                    location="교재 분석 근거 · 원문 위치 확인 전",
                    text_kind="APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE",
                    analysis_text=material.analysis.approved_analysis_text,
                    original_passages=[],
                )
                for index, material in enumerate(self.materials, 1)
            ],
            pages=[],
            limitations=[
                "승인된 분석 텍스트이며 교재 원문 인용이 아닙니다.",
                "교재 원문 페이지는 아직 열람하지 않았습니다. 인용·캡처 위치를 만들지 마세요.",
                *(
                    ("허용된 교재에서 관련 분석 근거를 찾지 못했습니다.",)
                    if not self.materials
                    else ()
                ),
            ],
        )
        return ConceptEvidenceContext.model_validate(
            value | dict(context_sha256=sha256(canonical_bytes(value)))
        )


class KakaoConceptKnowledgeReader:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.retrieval = KnowledgeRetrievalApplicationService(engine, settings)
        self.analyses = KnowledgeGraphPublicationService(engine, settings)

    def capture_authoring_scope(
        self, session: Session, actor: ActorContext, binding_id: str
    ) -> ChatRagScope:
        """Initial intent only: pin the currently published authoring policy and its one corpus."""
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "knowledge-grounded-item"
            )
        )
        revision = (
            session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if logical is not None and logical.current_revision_id is not None
            else None
        )
        if (
            logical is None
            or logical.state != "ACTIVE"
            or revision is None
            or revision.preset_id != logical.preset_id
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_SCOPE_NOT_CONFIGURED")
        preset = validated_preset(revision)
        if not isinstance(preset, ExecutionPresetRevisionV2) or preset.state != "RELEASED":
            raise KakaoArchiveError("KAKAO_CONCEPT_SCOPE_NOT_CONFIGURED")
        policy = preset.retrieval_policy
        if (
            len(policy.allowed_corpus_keys) != 1
            or "TEXTBOOK" not in policy.allowed_source_classes
            or "ITEM_PREPARATION" not in policy.allowed_query_kinds
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_SCOPE_NOT_CONFIGURED")
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == policy.allowed_corpus_keys[0],
                KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
            )
        )
        if corpus is None or corpus.current_graph_snapshot_revision_id is None:
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_AVAILABLE")
        snapshot = self.retrieval.resolve_snapshot_pointer(
            session, corpus.current_graph_snapshot_revision_id
        )
        row = session.get(KnowledgeGraphSnapshotRecord, snapshot.graph_snapshot_revision_id)
        if row is None or snapshot.graph_id != corpus.graph_id:
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
        scope = ChatRagScope(
            snapshot=ChatKnowledgeSnapshot(
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                sha256=row.snapshot_sha256,
            ),
            policy=ChatRagPolicy(
                access_policy_revision_id=policy.access_policy_revision_id,
                sha256=policy.access_policy_sha256,
            ),
        )
        self._authority(session, actor, binding_id, scope)
        return scope

    def prepare_pages(
        self,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        knowledge: ResolvedConceptTextbookKnowledge,
        *,
        source_root: Path,
        reauthorize_question: Callable[[], None],
    ) -> PreparedConceptPages:
        """Materialize exact original page PNGs under current question/source authority."""
        from .kakao_concept_pages import prepare_kakao_concept_pages

        return prepare_kakao_concept_pages(
            self.analyses.artifacts,
            knowledge=knowledge,
            source_root=source_root,
            authorize=lambda: self.reauthorize(
                actor, binding_id, knowledge, reauthorize_question=reauthorize_question
            ),
        )

    def prepare_captures(
        self,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        prepared: PreparedConceptPages,
        *,
        request: ConceptComposeRequest,
        result: ConceptResult,
        output_root: Path,
        reauthorize_question: Callable[[], None],
    ) -> tuple[PreparedConceptCapture, ...]:
        """Create local crop proposals, not publication or permission to edit the textbook."""
        from .kakao_concept_pages import prepare_kakao_concept_captures

        return prepare_kakao_concept_captures(
            self.analyses.artifacts,
            prepared=prepared,
            request=request,
            result=result,
            output_root=output_root,
            authorize=lambda: self.reauthorize(
                actor,
                binding_id,
                prepared.knowledge,
                reauthorize_question=reauthorize_question,
            ),
        )

    def _authority(
        self,
        session: Session,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        scope: ChatRagScope,
    ) -> tuple[
        RequesterRole,
        frozenset[PermissionKey],
        EducationRetrievalAccessPolicy,
        KnowledgeGraphSnapshotPointer,
    ]:
        if isinstance(actor, ActorContext):
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
            )
        else:
            stored = actor.service.accepted_intent_row(
                session, actor.intent, operator_id=actor.owner_operator_id
            )
            if stored.source_binding_id != binding_id or actor.intent.scope != scope:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_FORBIDDEN")
            owner = stored.owner_operator_id
        permissions = effective_permissions(session, owner)
        if (
            not {
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
                PermissionKey.KNOWLEDGE_ANALYSIS_READ,
                PermissionKey.CONTENT_INTAKE_READ,
            }
            <= permissions
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_FORBIDDEN")
        policy = self.retrieval.resolve_access_policy(
            session,
            scope.policy.access_policy_revision_id,
            sha256=scope.policy.sha256,
        )
        roles = {r.role_key for _, r in active_role_assignments(session, owner)}
        role = next(
            (
                r
                for r in ("ADMIN", "EDITOR", "REVIEWER")
                if r in roles and r in policy.allowed_requester_roles
            ),
            None,
        )
        if (
            role is None
            or "ITEM_PREPARATION" not in policy.allowed_query_kinds
            or "TEXTBOOK" not in policy.allowed_source_classes
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_FORBIDDEN")
        row = session.get(KnowledgeGraphSnapshotRecord, scope.snapshot.graph_snapshot_revision_id)
        if row is None or row.snapshot_sha256 != scope.snapshot.sha256:
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
        snapshot = self.retrieval.resolve_snapshot_pointer(
            session,
            scope.snapshot.graph_snapshot_revision_id,
        )
        return cast(RequesterRole, role), permissions, policy, snapshot

    @staticmethod
    def _titles(session: Session, values: tuple[ResolvedTextbookContext, ...]) -> dict[str, str]:
        document_ids = {
            v.source.document_revision_id
            for v in values
            if isinstance(
                v.source,
                (
                    EducationalDocumentKnowledgeSourceV3,
                    EducationalDocumentKnowledgeSourceV4,
                    EducationalDocumentKnowledgeSourceV5,
                ),
            )
        }
        file_ids = {
            v.source.source_file_id
            for v in values
            if isinstance(v.source, ContentIntakeKnowledgeSourceV2)
        }
        documents = (
            {
                r.document_revision_id: r.title
                for r in session.scalars(
                    select(EducationalDocumentRevisionRecord).where(
                        EducationalDocumentRevisionRecord.document_revision_id.in_(document_ids)
                    )
                )
            }
            if document_ids
            else {}
        )
        files = (
            {
                r.source_file_id: r.original_filename
                for r in session.scalars(
                    select(ContentIntakeSourceFileRecord).where(
                        ContentIntakeSourceFileRecord.source_file_id.in_(file_ids)
                    )
                )
            }
            if file_ids
            else {}
        )
        result = {}
        for value in values:
            source = value.source
            if isinstance(source, ContentIntakeKnowledgeSourceV2):
                title = files.get(source.source_file_id)
            elif isinstance(
                source,
                (
                    EducationalDocumentKnowledgeSourceV3,
                    EducationalDocumentKnowledgeSourceV4,
                    EducationalDocumentKnowledgeSourceV5,
                ),
            ):
                title = documents.get(source.document_revision_id)
            else:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
            if not title:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
            result[value.analysis_run_id] = title
        return result

    def retrieve(
        self,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        *,
        scope: ChatRagScope,
        plan: ConceptPlan,
        reauthorize_question: Callable[[], None],
    ) -> ResolvedConceptTextbookKnowledge:
        if plan.status != "PLANNED":
            raise KakaoArchiveError("KAKAO_CONCEPT_PLAN_NOT_READY")
        # This callback belongs to the exact stored-question owner; it is mandatory.
        reauthorize_question()
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            role, permissions, policy, snapshot = self._authority(session, actor, binding_id, scope)
            maximum = policy.maximum_budget
            budget = EvidenceBudget(
                max_documents=min(3, maximum.max_documents),
                max_item_revisions=0,
                max_graph_nodes=min(32, maximum.max_graph_nodes),
                max_claims=min(32, maximum.max_claims),
                max_context_tokens=min(4000, maximum.max_context_tokens),
            )
            selected: dict[str, TextbookContextSelection] = {}
            nodes: set[str] = set()
            for query in plan.queries:
                terms = knowledge_node_terms("", query.concept + " " + query.query)[:8]
                if not terms:
                    raise KakaoArchiveError("KAKAO_CONCEPT_QUERY_INVALID")
                topics = self.retrieval.topic_keys_for_terms(
                    session,
                    snapshot_id=scope.snapshot.graph_snapshot_revision_id,
                    terms=terms,
                    source_classes=("TEXTBOOK",),
                    allow_answer_bearing=role in policy.answer_bearing_roles,
                )
                if not topics:
                    continue
                body = dict(
                    operation="CREATE_EVIDENCE_BUNDLE",
                    graph_snapshot_revision_id=scope.snapshot.graph_snapshot_revision_id,
                    query_kind="ITEM_PREPARATION",
                    curriculum_scope=None,
                    topic_keys=topics,
                    required_item_elements=(),
                    source_classes=("TEXTBOOK",),
                    evidence_budget=budget.model_dump(mode="json"),
                    access_policy_revision_id=scope.policy.access_policy_revision_id,
                    requester_role=role,
                    requester_permission_keys=tuple(sorted(p.value for p in permissions)),
                    requested_by=actor.actor_id
                    if isinstance(actor, ActorContext)
                    else actor.owner_operator_id,
                    target_item_revision_id=None,
                )
                digest = content_sha256(body)
                command = CreateEvidenceBundleCommand.model_validate(
                    body
                    | dict(
                        submission_sha256=digest, idempotency_key="kakao-concept-read:" + digest[7:]
                    )
                )
                # Explicitly supports the same uploaded-material source family as current authoring.
                selection = self.retrieval.retrieve_material_read_only(session, command)
                if (
                    selection.request.graph_snapshot != snapshot
                    or selection.request.access_policy_sha256 != scope.policy.sha256
                ):
                    raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
                for candidate in selection.candidates:
                    if candidate.source.source_class != "TEXTBOOK":
                        raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
                    if (
                        candidate.analysis_run_id in selected
                        or len(nodes | set(candidate.node_ids)) > budget.max_graph_nodes
                    ):
                        continue
                    selected[candidate.analysis_run_id] = TextbookContextSelection(
                        analysis_run_id=candidate.analysis_run_id,
                        source=candidate.source,
                        node_ids=candidate.node_ids,
                        anchor_ids=candidate.anchor_ids,
                    )
                    nodes.update(candidate.node_ids)
                    if len(selected) == min(3, budget.max_documents):
                        break
                if len(selected) == min(3, budget.max_documents):
                    break
            materialized = resolve_item_textbook_context(
                session,
                analyses=self.analyses,
                graph_snapshot_revision_id=scope.snapshot.graph_snapshot_revision_id,
                selections=tuple(selected.values()),
            )
            values = tuple(materialized[key] for key in selected)
            titles = self._titles(session, values)
            result = ResolvedConceptTextbookKnowledge(
                scope,
                snapshot,
                tuple(
                    ConceptTextbookMaterial(
                        titles[v.analysis_run_id], selected[v.analysis_run_id].node_ids, v
                    )
                    for v in values
                ),
            )
        self.reauthorize(actor, binding_id, result, reauthorize_question=reauthorize_question)
        return result

    def reauthorize(
        self,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        value: ResolvedConceptTextbookKnowledge,
        *,
        reauthorize_question: Callable[[], None],
    ) -> None:
        reauthorize_question()
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            _, _, _, snapshot = self._authority(session, actor, binding_id, value.scope)
            current = resolve_item_textbook_context(
                session,
                analyses=self.analyses,
                graph_snapshot_revision_id=value.scope.snapshot.graph_snapshot_revision_id,
                selections=tuple(m.selection() for m in value.materials),
            )
            if snapshot != value.snapshot or tuple(
                current[m.analysis.analysis_run_id] for m in value.materials
            ) != tuple(m.analysis for m in value.materials):
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
        reauthorize_question()

    def restore(
        self,
        actor: ActorContext | KakaoConceptSourceAuthority,
        binding_id: str,
        receipt: KakaoConceptKnowledge,
        *,
        reauthorize_question: Callable[[], None],
    ) -> ResolvedConceptTextbookKnowledge:
        """Reauthorize exact saved selections; never rerank or substitute a newer textbook."""
        reauthorize_question()
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            _, _, _, snapshot = self._authority(session, actor, binding_id, receipt.scope)
            resolved = resolve_item_textbook_context(
                session,
                analyses=self.analyses,
                graph_snapshot_revision_id=receipt.scope.snapshot.graph_snapshot_revision_id,
                selections=tuple(
                    TextbookContextSelection(p.analysis_run_id, p.source, p.node_ids, p.anchor_ids)
                    for p in receipt.materials
                ),
            )
            materials = tuple(
                ConceptTextbookMaterial(p.title, p.node_ids, resolved[p.analysis_run_id])
                for p in receipt.materials
            )
            if tuple(material.pin() for material in materials) != receipt.materials:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
        reauthorize_question()
        return ResolvedConceptTextbookKnowledge(receipt.scope, snapshot, materials)
