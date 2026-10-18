"""Read-only conversational evidence using the official authoring GraphRAG boundary."""

from __future__ import annotations

import json
from typing import Literal, cast

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    ContentIntakeKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationRetrievalAccessPolicy,
    EvidenceBudget,
    KnowledgeAnalysisSourceV3,
    validate_contract,
)
from eom_catalog_contracts.chat_private_query_scope import (
    ChatPrivateQueryScopeReply,
    ChatPrivateQueryScopeRequest,
    failed_chat_private_query_scope_reply,
    parse_chat_private_query_scope_request,
    validate_chat_private_query_scope_reply,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagAnchor,
    ChatRagAuthorizeCommand,
    ChatRagCatalogReply,
    ChatRagCatalogRequest,
    ChatRagContext,
    ChatRagDocumentReference,
    ChatRagIntakeReference,
    ChatRagItemReference,
    ChatRagOriginalPointer,
    ChatRagPolicy,
    ChatRagPrepareCommand,
    ChatRagReference,
    ChatRagScope,
    ChatRagSource,
    ChatRagSourceReference,
    RagError,
    chat_rag_context,
    read_rag,
    read_rag_catalog_reply,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, and_, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
    MaterializedAcceptedAnalysis,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalCandidate,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.models import (
    ContentIntakeSourceFileRecord,
    EducationalDocumentRevisionRecord,
    ItemRecord,
)
from eom_catalog_service.settings import CatalogSettings

type RequesterRole = Literal["ADMIN", "EDITOR", "REVIEWER"]
SUPPORTED_CLASSES = frozenset({"TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM"})
ANALYSIS_LIMITATION = (
    "승인된 분석 텍스트이며 원본 페이지의 직접 인용이나 그림 육안 확인이 아닙니다."
)
TEXT_LIMITATION = "분석 본문은 문맥 예산 안에서 일부만 제공됩니다."
SOURCE_TEXT_BYTES = 2500


class ChatRagResolutionError(ValueError):
    def __init__(self, code: RagError) -> None:
        self.code = code
        super().__init__(code)


def source_reference(
    source: KnowledgeAnalysisSourceV3
    | EducationalDocumentKnowledgeSourceV4
    | ApprovedPastExamItemKnowledgeSourceV3,
) -> ChatRagSourceReference:
    """Remove staging/batch details, not immutable source identity."""
    pointer = ChatRagOriginalPointer.model_validate(
        source.artifact_member.model_dump(
            mode="json", include=set(ChatRagOriginalPointer.model_fields)
        )
    )
    if isinstance(
        source, EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4
    ):
        return ChatRagDocumentReference.model_validate(
            {
                "source_class": source.source_class,
                "document_id": source.document_id,
                "document_revision_id": source.document_revision_id,
                "artifact_member": pointer,
                "first_physical_page": source.first_physical_page,
                "last_physical_page": source.last_physical_page,
            }
        )
    if isinstance(source, ContentIntakeKnowledgeSourceV2):
        return ChatRagIntakeReference.model_validate(
            {
                "source_class": source.source_class,
                "source_file_id": source.source_file_id,
                "artifact_member": pointer,
            }
        )
    return ChatRagItemReference.model_validate(
        {
            "source_class": source.source_class,
            "item_id": source.item_id,
            "item_revision_id": source.item_revision_id,
            "artifact_member": pointer,
        }
    )


def analysis_excerpt(value: str, *, max_bytes: int = SOURCE_TEXT_BYTES) -> str:
    # Deterministic, UTF-8-safe prefix; retain a separate limitation rather than
    # silently pretending this bounded materialization is a complete document.
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").strip()


class ChatRagResolutionService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.retrieval = KnowledgeRetrievalApplicationService(engine, settings)
        self.analyses = KnowledgeGraphPublicationService(engine, settings)

    def resolve_private_query_scope(
        self, request: ChatPrivateQueryScopeRequest
    ) -> ChatPrivateQueryScopeReply:
        """Read an exact selected scope through the same actor/policy/Graph boundary."""
        request = parse_chat_private_query_scope_request(request)
        try:
            with self.sessions() as session, session.begin():
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET TRANSACTION READ ONLY"))
                self._authority(session, request.actor_id, request.scope.policy)
                pointer = self._scope(session, request.scope)
                reply = ChatPrivateQueryScopeReply(
                    schema_version="chat-private-query-scope-reply/1.0",
                    request_sha256=request.request_sha256,
                    status="SUCCEEDED",
                    scope=request.scope,
                    graph_snapshot=pointer,
                    error_code=None,
                )
        except ChatRagResolutionError as error:
            reply = failed_chat_private_query_scope_reply(
                request,
                "CHAT_KNOWLEDGE_FORBIDDEN"
                if error.code == "CHAT_KNOWLEDGE_FORBIDDEN"
                else "CHAT_KNOWLEDGE_UNAVAILABLE"
                if error.code == "CHAT_KNOWLEDGE_UNAVAILABLE"
                else "CHAT_KNOWLEDGE_POINTER_INVALID",
            )
        except KnowledgeRetrievalServiceError as error:
            reply = failed_chat_private_query_scope_reply(
                request,
                "CHAT_KNOWLEDGE_FORBIDDEN"
                if error.code
                in {"KNOWLEDGE_RETRIEVAL_UNAUTHORIZED", "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID"}
                else "CHAT_KNOWLEDGE_POINTER_INVALID",
            )
        except SQLAlchemyError:
            reply = failed_chat_private_query_scope_reply(request, "CHAT_KNOWLEDGE_UNAVAILABLE")
        except (KnowledgeGraphPublicationError, JsonSchemaValidationError, ValueError, OSError):
            reply = failed_chat_private_query_scope_reply(request, "CHAT_KNOWLEDGE_POINTER_INVALID")
        return validate_chat_private_query_scope_reply(request, reply)

    def resolve(self, request: ChatRagCatalogRequest) -> ChatRagCatalogReply:
        request = read_rag("CatalogRequest", request.model_dump(mode="json"), ChatRagCatalogRequest)
        try:
            with self.sessions() as session, session.begin():
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET TRANSACTION READ ONLY"))
                reply = self._resolve(session, request)
        except ChatRagResolutionError as exc:
            reply = self._failed(exc.code)
        except KnowledgeRetrievalServiceError as exc:
            if exc.code == "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE":
                # No partial context escaped; retrieval already checked exact scope.
                command = request.command
                if isinstance(command, ChatRagPrepareCommand | ChatRagAuthorizeCommand):
                    reply = self._failed("CHAT_KNOWLEDGE_POINTER_INVALID")
                else:
                    reply = ChatRagCatalogReply(
                        status="EMPTY", scope=command.scope, context=None, error_code=None
                    )
            else:
                reply = self._failed(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if exc.code
                    in {
                        "KNOWLEDGE_RETRIEVAL_UNAUTHORIZED",
                        "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID",
                    }
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                )
        except (KnowledgeGraphPublicationError, JsonSchemaValidationError, ValueError, OSError):
            reply = self._failed("CHAT_KNOWLEDGE_POINTER_INVALID")
        return read_rag_catalog_reply(reply.model_dump(mode="json"), request=request)

    @staticmethod
    def _failed(code: RagError) -> ChatRagCatalogReply:
        return ChatRagCatalogReply(status="FAILED", scope=None, context=None, error_code=code)

    def _resolve(self, session: Session, request: ChatRagCatalogRequest) -> ChatRagCatalogReply:
        command = request.command
        if isinstance(command, ChatRagPrepareCommand):
            policy, _role, _permissions = self._authority(session, request.actor_id, command.policy)
            snapshot = command.snapshot
            if snapshot is None:
                corpus = session.scalar(
                    select(KnowledgeCorpusRecord).where(
                        KnowledgeCorpusRecord.corpus_key == "integrated-science-textbooks",
                        KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
                    )
                )
                if corpus is None or corpus.current_graph_snapshot_revision_id is None:
                    raise ChatRagResolutionError("CHAT_KNOWLEDGE_UNAVAILABLE")
                pointer = self.retrieval.resolve_snapshot_pointer(
                    session, corpus.current_graph_snapshot_revision_id
                )
                if pointer.graph_id != corpus.graph_id:
                    raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
                row = session.get(KnowledgeGraphSnapshotRecord, pointer.graph_snapshot_revision_id)
                if row is None:
                    raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
                snapshot = ChatKnowledgeSnapshot(
                    graph_snapshot_revision_id=pointer.graph_snapshot_revision_id,
                    sha256=row.snapshot_sha256,
                )
            scope = ChatRagScope(snapshot=snapshot, policy=command.policy)
            self._scope(session, scope)
            if not SUPPORTED_CLASSES.intersection(policy.allowed_source_classes):
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
            return ChatRagCatalogReply(
                status="SUCCEEDED", scope=scope, context=None, error_code=None
            )

        context = (
            command.context
            if isinstance(command, ChatRagAuthorizeCommand)
            else command.prior_context
        )
        scope = (
            command.context.scope if isinstance(command, ChatRagAuthorizeCommand) else command.scope
        )
        policy, role, permissions = self._authority(session, request.actor_id, scope.policy)
        self._scope(session, scope)
        if context is not None:
            self._authorize_context(session, context, permissions, policy, role)
        if isinstance(command, ChatRagAuthorizeCommand):
            return ChatRagCatalogReply(
                status="SUCCEEDED", scope=scope, context=context, error_code=None
            )
        args = command.arguments
        self._source_authority(args.source_classes, permissions, policy)
        if context is not None and len(context.sources) >= min(3, policy.maximum_budget.max_claims):
            return ChatRagCatalogReply(status="EMPTY", scope=scope, context=None, error_code=None)
        topics = self.retrieval.topic_keys_for_terms(
            session,
            snapshot_id=scope.snapshot.graph_snapshot_revision_id,
            terms=args.terms,
            source_classes=args.source_classes,
            allow_answer_bearing=role in policy.answer_bearing_roles,
        )
        if not topics:
            return ChatRagCatalogReply(status="EMPTY", scope=scope, context=None, error_code=None)
        budget = policy.maximum_budget
        body = {
            "operation": "CREATE_EVIDENCE_BUNDLE",
            "graph_snapshot_revision_id": scope.snapshot.graph_snapshot_revision_id,
            "query_kind": "ITEM_PREPARATION",
            "curriculum_scope": None,
            "topic_keys": topics,
            "required_item_elements": (),
            "source_classes": tuple(sorted(args.source_classes)),
            "evidence_budget": EvidenceBudget(
                max_documents=min(3, budget.max_documents),
                max_item_revisions=min(3, budget.max_item_revisions),
                max_graph_nodes=min(32, budget.max_graph_nodes),
                max_claims=min(32, budget.max_claims),
                max_context_tokens=min(4000, budget.max_context_tokens),
            ).model_dump(mode="json"),
            "access_policy_revision_id": scope.policy.access_policy_revision_id,
            "requester_role": role,
            "requester_permission_keys": tuple(sorted(p.value for p in permissions)),
            "requested_by": request.actor_id,
            "target_item_revision_id": None,
        }
        digest = content_sha256(body)
        query = CreateEvidenceBundleCommand.model_validate(
            {**body, "submission_sha256": digest, "idempotency_key": "chat-read:" + digest[7:]}
        )
        selection = self.retrieval.retrieve_read_only(session, query)
        candidates = self._bounded_candidates(selection.candidates, context, query.evidence_budget)
        if not candidates:
            return ChatRagCatalogReply(status="EMPTY", scope=scope, context=None, error_code=None)
        materialized = self.analyses.resolve_accepted_analyses(
            session, tuple(candidate.analysis_run_id for candidate in candidates)
        )
        references = self._references(
            session,
            scope,
            tuple((materialized[c.analysis_run_id], c.node_ids, c.anchor_ids) for c in candidates),
        )
        sources = list(() if context is None else context.sources)
        titles = self._titles(session, tuple(materialized.values()))
        for candidate in candidates:
            analysis = materialized[candidate.analysis_run_id]
            if analysis.analysis.source != candidate.source:
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            reference = references[candidate.analysis_run_id]
            sources.append(
                ChatRagSource(
                    key=f"R{len(sources) + 1}",
                    reference=reference,
                    display_name=titles[candidate.analysis_run_id],
                    location=self._location(reference),
                    text=analysis_excerpt(
                        analysis.analysis.proposal.normalized_markdown,
                        max_bytes=self._source_text_budget(policy),
                    ),
                )
            )
        limitations = tuple(
            dict.fromkeys(
                (
                    *(() if context is None else context.limitations),
                    ANALYSIS_LIMITATION,
                    TEXT_LIMITATION,
                )
            )
        )
        result = chat_rag_context(scope=scope, sources=tuple(sources), limitations=limitations)
        return ChatRagCatalogReply(status="SUCCEEDED", scope=scope, context=result, error_code=None)

    def _authority(
        self, session: Session, actor_id: str, pin: ChatRagPolicy
    ) -> tuple[EducationRetrievalAccessPolicy, RequesterRole, frozenset[PermissionKey]]:
        actor = session.get(OperatorRecord, actor_id)
        permissions = effective_permissions(session, actor_id)
        if (
            actor is None
            or actor.status != "ACTIVE"
            or actor.deleted_at is not None
            or actor.must_change_password
            or not {
                PermissionKey.GENERAL_CHAT_READ,
                PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
                PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            }.issubset(permissions)
        ):
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
        policy = self.retrieval.resolve_access_policy(
            session, pin.access_policy_revision_id, sha256=pin.sha256
        )
        roles = {role.role_key for _assignment, role in active_role_assignments(session, actor_id)}
        role = next(
            (
                r
                for r in ("ADMIN", "EDITOR", "REVIEWER")
                if r in roles and r in policy.allowed_requester_roles
            ),
            None,
        )
        if role is None or "ITEM_PREPARATION" not in policy.allowed_query_kinds:
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
        return policy, cast(RequesterRole, role), permissions

    @staticmethod
    def _source_authority(
        classes: tuple[str, ...],
        permissions: frozenset[PermissionKey],
        policy: EducationRetrievalAccessPolicy,
    ) -> None:
        required = {PermissionKey.ITEM_READ for c in classes if c != "TEXTBOOK"}
        if set(classes).intersection({"TEXTBOOK", "PAST_EXAM"}):
            required.add(PermissionKey.CONTENT_INTAKE_READ)
        if not set(classes).issubset(policy.allowed_source_classes) or not required.issubset(
            permissions
        ):
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")

    def _scope(self, session: Session, scope: ChatRagScope) -> KnowledgeGraphSnapshotPointer:
        pointer = self.retrieval.resolve_snapshot_pointer(
            session, scope.snapshot.graph_snapshot_revision_id
        )
        row = session.get(KnowledgeGraphSnapshotRecord, scope.snapshot.graph_snapshot_revision_id)
        if row is None or row.snapshot_sha256 != scope.snapshot.sha256:
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
        member = pointer.manifest_artifact
        raw = self.retrieval.artifacts.read_member(
            artifact_id=member.artifact_id,
            revision_id=member.artifact_revision_id,
            member_path=member.member_path,
            sha256=member.sha256,
            media_type=member.media_type,
            schema_ref=member.schema_ref,
            max_bytes=32 * 1024 * 1024,
        )
        document = json.loads(raw)
        version = member.schema_ref.rsplit("/", 1)[-1].removesuffix(".0")
        validate_contract(f"knowledge-graph-snapshot-manifest-v{version}", document)
        if (
            document.get("graph_snapshot_revision_id") != scope.snapshot.graph_snapshot_revision_id
            or document.get("graph_id") != pointer.graph_id
            or document.get("snapshot_sha256") != scope.snapshot.sha256
        ):
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")

        return pointer

    @staticmethod
    def _bounded_candidates(
        candidates: tuple[KnowledgeRetrievalCandidate, ...],
        previous: ChatRagContext | None,
        budget: EvidenceBudget,
    ) -> tuple[KnowledgeRetrievalCandidate, ...]:
        prior = () if previous is None else previous.sources
        run_ids = {s.reference.analysis_run_id for s in prior}
        nodes = {n for s in prior for n in s.reference.graph_node_ids}
        documents = {
            s.reference.source
            for s in prior
            if s.reference.source.source_kind != "APPROVED_ITEM_REVISION"
        }
        items = {
            s.reference.source
            for s in prior
            if s.reference.source.source_kind == "APPROVED_ITEM_REVISION"
        }
        selected: list[KnowledgeRetrievalCandidate] = []
        document_count, item_count = len(documents), len(items)
        sources = {s.reference.source for s in prior}
        for candidate in candidates:
            if len(prior) + len(selected) >= min(3, budget.max_claims):
                break
            source = candidate.source
            # Small immutable source values retain the original page range. They
            # are not deduplicated merely by the original PDF's shared bytes.
            identity = source_reference(source)
            if (
                candidate.analysis_run_id in run_ids
                or len(nodes | set(candidate.node_ids)) > budget.max_graph_nodes
            ):
                continue
            if identity in sources:
                continue
            if isinstance(source, ApprovedItemKnowledgeSourceV2):
                if item_count >= budget.max_item_revisions:
                    continue
            elif document_count >= budget.max_documents:
                continue
            selected.append(candidate)
            sources.add(identity)
            run_ids.add(candidate.analysis_run_id)
            nodes.update(candidate.node_ids)
            if isinstance(source, ApprovedItemKnowledgeSourceV2):
                item_count += 1
            else:
                document_count += 1
        return tuple(selected)

    @staticmethod
    def _references(
        session: Session,
        scope: ChatRagScope,
        values: tuple[tuple[MaterializedAcceptedAnalysis, tuple[str, ...], tuple[str, ...]], ...],
    ) -> dict[str, ChatRagReference]:
        run_ids = tuple(value.analysis.analysis_run_id for value, _nodes, _anchors in values)
        associations = tuple(
            session.scalars(
                select(KnowledgeSnapshotAnalysisRecord).where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                    == scope.snapshot.graph_snapshot_revision_id,
                    KnowledgeSnapshotAnalysisRecord.analysis_run_id.in_(run_ids),
                )
            )
        )
        by_run = {row.analysis_run_id: row for row in associations}
        if len(by_run) != len(associations) or set(by_run) != set(run_ids):
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
        pointer = KnowledgeNodeSourcePointerRecord
        rows = tuple(
            session.scalars(
                select(pointer)
                .where(
                    pointer.graph_snapshot_revision_id == scope.snapshot.graph_snapshot_revision_id,
                    or_(
                        *(
                            and_(
                                pointer.analysis_run_id == value.analysis.analysis_run_id,
                                pointer.node_id.in_(nodes),
                                pointer.anchor_id.in_(anchors),
                            )
                            for value, nodes, anchors in values
                        )
                    ),
                )
                .limit(3073)
            )
        )
        if len(rows) > 3072:
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
        pointers_by_run: dict[str, list[KnowledgeNodeSourcePointerRecord]] = {}
        for row in rows:
            pointers_by_run.setdefault(row.analysis_run_id, []).append(row)
        resolved = {}
        for value, node_ids, anchor_ids in values:
            analysis = value.analysis
            association = by_run[analysis.analysis_run_id]
            source = source_reference(analysis.source)
            source_revision = (
                source.document_revision_id
                if isinstance(source, ChatRagDocumentReference)
                else source.item_revision_id
                if isinstance(source, ChatRagItemReference)
                else source.source_file_id
            )
            if (
                association.source_kind != source.source_kind
                or association.source_revision_id != source_revision
                or association.source_artifact_id != source.artifact_member.artifact_id
                or association.source_artifact_revision_id
                != source.artifact_member.artifact_revision_id
                or association.source_sha256 != source.artifact_member.sha256
                or (
                    association.accepted_result_artifact_id,
                    association.accepted_result_artifact_revision_id,
                    association.accepted_result_sha256,
                )
                != (
                    analysis.accepted_result.artifact_id,
                    analysis.accepted_result.artifact_revision_id,
                    analysis.accepted_result.sha256,
                )
            ):
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            anchors = {a.anchor_id: a for a in analysis.proposal.anchors}
            members = {
                (
                    analysis.source.artifact_member.artifact_revision_id,
                    analysis.source.artifact_member.member_path,
                ): (
                    analysis.source.artifact_member.artifact_id,
                    analysis.source.artifact_member.sha256,
                )
            }
            if isinstance(analysis.source, ApprovedPastExamItemKnowledgeSourceV3):
                members.update(
                    {
                        (p.image.artifact_revision_id, p.image.member_path): (
                            p.image.artifact_id,
                            p.image.sha256,
                        )
                        for p in analysis.source.page_inputs
                    }
                )
            if not set(anchor_ids).issubset(anchors):
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            rows_for_run = pointers_by_run.get(analysis.analysis_run_id, [])
            if (
                {r.node_id for r in rows_for_run} != set(node_ids)
                or {r.anchor_id for r in rows_for_run} != set(anchor_ids)
                or any(
                    (r.artifact_revision_id, r.member_path, r.excerpt_sha256)
                    != (
                        anchors[r.anchor_id].artifact_revision_id,
                        anchors[r.anchor_id].member_path,
                        anchors[r.anchor_id].excerpt_sha256,
                    )
                    or r.source_class != source.source_class
                    or r.source_revision_id != source_revision
                    or (r.artifact_revision_id, r.member_path) not in members
                    or r.source_artifact_id != members[(r.artifact_revision_id, r.member_path)][0]
                    or r.source_sha256 != members[(r.artifact_revision_id, r.member_path)][1]
                    for r in rows_for_run
                )
            ):
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            resolved[analysis.analysis_run_id] = ChatRagReference(
                source=source,
                analysis_run_id=analysis.analysis_run_id,
                accepted_result=ArtifactMemberPointer.model_validate(
                    analysis.accepted_result.model_dump(
                        mode="json", include=set(ArtifactMemberPointer.model_fields)
                    )
                ),
                analysis_member=value.markdown_member,
                anchors=tuple(
                    ChatRagAnchor.model_validate(
                        anchors[a].model_dump(mode="json", include=set(ChatRagAnchor.model_fields))
                    )
                    for a in anchor_ids
                ),
                graph_node_ids=node_ids,
            )
        return resolved

    def _authorize_context(
        self,
        session: Session,
        context: ChatRagContext,
        permissions: frozenset[PermissionKey],
        policy: EducationRetrievalAccessPolicy,
        role: RequesterRole,
    ) -> None:
        if not {ANALYSIS_LIMITATION, TEXT_LIMITATION}.issubset(context.limitations):
            raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
        self._source_authority(
            tuple({s.reference.source.source_class for s in context.sources}), permissions, policy
        )
        materialized = self.analyses.resolve_accepted_analyses(
            session, tuple(s.reference.analysis_run_id for s in context.sources)
        )
        references = self._references(
            session,
            context.scope,
            tuple(
                (
                    materialized[s.reference.analysis_run_id],
                    s.reference.graph_node_ids,
                    tuple(a.anchor_id for a in s.reference.anchors),
                )
                for s in context.sources
            ),
        )
        titles = self._titles(session, tuple(materialized.values()))
        if role not in policy.answer_bearing_roles:
            restricted = session.scalar(
                select(KnowledgeNodeRecord.node_id)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == context.scope.snapshot.graph_snapshot_revision_id,
                    KnowledgeNodeRecord.node_id.in_(
                        {n for s in context.sources for n in s.reference.graph_node_ids}
                    ),
                    KnowledgeNodeRecord.answer_bearing.is_(True),
                )
                .limit(1)
            )
            if restricted is not None:
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
        for source in context.sources:
            value = materialized[source.reference.analysis_run_id]
            reference = references[source.reference.analysis_run_id]
            if (
                reference != source.reference
                or analysis_excerpt(
                    value.analysis.proposal.normalized_markdown,
                    max_bytes=self._source_text_budget(policy),
                )
                != source.text
                or titles[source.reference.analysis_run_id] != source.display_name
                or self._location(reference) != source.location
            ):
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")

    @staticmethod
    def _source_text_budget(policy: EducationRetrievalAccessPolicy) -> int:
        # Reserve an equal bounded share for all three sources. The authoring
        # estimator counts at most two UTF-8 bytes per estimated context token.
        return min(SOURCE_TEXT_BYTES, policy.maximum_budget.max_context_tokens * 2 // 3)

    @staticmethod
    def _location(reference: ChatRagReference) -> str:
        source = reference.source
        if isinstance(source, ChatRagDocumentReference):
            pages = f"PDF {source.first_physical_page}-{source.last_physical_page}쪽"
            return f"{pages} · {reference.anchors[0].locator}"[:256]
        return reference.anchors[0].locator[:256]

    @staticmethod
    def _titles(
        session: Session, analyses: tuple[MaterializedAcceptedAnalysis, ...]
    ) -> dict[str, str]:
        references = {
            a.analysis.analysis_run_id: source_reference(a.analysis.source) for a in analyses
        }
        document_ids = {
            s.document_revision_id
            for s in references.values()
            if isinstance(s, ChatRagDocumentReference)
        }
        file_ids = {
            s.source_file_id for s in references.values() if isinstance(s, ChatRagIntakeReference)
        }
        item_ids = {s.item_id for s in references.values() if isinstance(s, ChatRagItemReference)}
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
        items = (
            {
                r.item_id: r
                for r in session.scalars(select(ItemRecord).where(ItemRecord.item_id.in_(item_ids)))
            }
            if item_ids
            else {}
        )
        titles = {}
        for run_id, source in references.items():
            if isinstance(source, ChatRagDocumentReference):
                title = documents.get(source.document_revision_id)
            elif isinstance(source, ChatRagIntakeReference):
                title = files.get(source.source_file_id)
            else:
                item = items.get(source.item_id)
                title = (
                    "승인된 기출 문항" if source.source_class == "PAST_EXAM" else "승인된 제작 문항"
                )
                if item is None or item.lifecycle_state != "ACTIVE":
                    raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            if not title:
                raise ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID")
            titles[run_id] = title[:256]
        return titles
