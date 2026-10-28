"""Catalog-owned, read-only actor authorization and pinned chat materialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import (
    ChatAgentState,
    ChatKnowledgeCatalogReply,
    ChatKnowledgeCatalogRequest,
    ChatKnowledgeSource,
    ChatWorkflowCount,
    GroundingError,
    chat_knowledge_context,
    read_grounding,
)
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Engine, func, select, text

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_registered_report import load_registered_creative_report
from eom_catalog_service.item_content_contract import ITEM_CONTENT_SCHEMAS, read_item_content
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.solution_evidence_resolution import resolve_solution_evidence_by_base_run


class ChatKnowledgeResolutionError(ValueError):
    def __init__(self, code: GroundingError) -> None:
        self.code = code
        super().__init__(code)


class ChatKnowledgeResolutionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine)
        self.retrieval = KnowledgeRetrievalApplicationService(engine)

    def resolve(self, request: ChatKnowledgeCatalogRequest) -> ChatKnowledgeCatalogReply:
        request = read_grounding(
            "CatalogRequest", request.model_dump(mode="json"), ChatKnowledgeCatalogRequest
        )
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            actor = session.get(OperatorRecord, request.actor_id)
            permissions = effective_permissions(session, request.actor_id)
            if (
                actor is None
                or actor.status != "ACTIVE"
                or actor.deleted_at is not None
                or actor.must_change_password
                or PermissionKey.GENERAL_CHAT_READ not in permissions
            ):
                raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
            if request.selection is not None and PermissionKey.ITEM_READ not in permissions:
                raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_FORBIDDEN")
            item_count = (
                session.scalar(
                    select(func.count())
                    .select_from(ItemRecord)
                    .join(
                        ItemRevisionRecord,
                        ItemRecord.current_revision_id == ItemRevisionRecord.item_revision_id,
                    )
                    .where(
                        ItemRecord.lifecycle_state == "ACTIVE",
                        ItemRevisionRecord.revision_state.in_(("APPROVED", "IN_REVIEW")),
                    )
                )
                if PermissionKey.ITEM_READ in permissions
                else None
            )
            corpus = (
                session.scalar(
                    select(KnowledgeCorpusRecord).where(
                        KnowledgeCorpusRecord.corpus_key == "integrated-science-textbooks",
                        KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
                    )
                )
                if PermissionKey.ITEM_READ in permissions
                else None
            )
            current = (
                session.get(KnowledgeGraphSnapshotRecord, corpus.current_graph_snapshot_revision_id)
                if corpus is not None and corpus.current_graph_snapshot_revision_id
                else None
            )
            counts: dict[str, int] = (
                {
                    status: count
                    for status, count in session.execute(
                        select(WorkflowInstanceRecord.state, func.count())
                        .where(
                            WorkflowInstanceRecord.created_actor_type == "human",
                            WorkflowInstanceRecord.created_actor_id == request.actor_id,
                        )
                        .group_by(WorkflowInstanceRecord.state)
                    ).tuples()
                }
                if PermissionKey.WORKFLOW_READ in permissions
                else {}
            )
            state = ChatAgentState(
                observed_at=datetime.now(UTC),
                permissions=tuple(
                    sorted(
                        p.value
                        for p in permissions
                        if p.value.startswith(
                            (
                                "general_chat:",
                                "item:",
                                "workflow:",
                                "document_review:",
                                "hwpx:",
                                "operator:",
                            )
                        )
                    )
                )[:32],
                item_count=item_count,
                graph_node_count=None if current is None else current.node_count,
                workflow_counts=tuple(
                    ChatWorkflowCount.model_validate({"state": status, "count": count})
                    for status, count in sorted(counts.items())
                ),
            )
            if request.selection is None:
                return ChatKnowledgeCatalogReply(
                    status="SUCCEEDED", context=None, agent_state=state, error_code=None
                )
            selection = request.selection
            ids = tuple(r.item_revision_id for r in selection.references)
            rows = tuple(
                session.execute(
                    select(
                        ItemRecord, ItemRevisionRecord, ItemComponentRecord, ArtifactRevisionRecord
                    )
                    .join(ItemRevisionRecord, ItemRevisionRecord.item_id == ItemRecord.item_id)
                    .join(
                        ItemComponentRecord,
                        (
                            ItemComponentRecord.item_revision_id
                            == ItemRevisionRecord.item_revision_id
                        )
                        & (ItemComponentRecord.component_type == "ITEM_CONTENT")
                        & (ItemComponentRecord.ordinal == 0),
                    )
                    .join(
                        ArtifactRevisionRecord,
                        ArtifactRevisionRecord.revision_id
                        == ItemComponentRecord.artifact_revision_id,
                    )
                    .where(ItemRevisionRecord.item_revision_id.in_(ids))
                ).tuples()
            )
            by_id = {
                revision.item_revision_id: (item, revision, component, artifact)
                for item, revision, component, artifact in rows
            }
            if set(by_id) != set(ids) or len(rows) != len(ids):
                raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_NOT_FOUND")
            manifests = {
                artifact.revision_id: (logical, artifact)
                for logical, artifact in session.execute(
                    select(ArtifactRecord, ArtifactRevisionRecord)
                    .join(
                        ArtifactRevisionRecord,
                        ArtifactRevisionRecord.logical_artifact_id
                        == ArtifactRecord.logical_artifact_id,
                    )
                    .where(
                        ArtifactRevisionRecord.revision_id.in_(
                            tuple(row[1].manifest_artifact_revision_id for row in by_id.values())
                        )
                    )
                ).tuples()
            }
            pointers = []
            for ref in selection.references:
                item, revision, component, artifact = by_id[ref.item_revision_id]
                if item.item_id != ref.item_id or revision.manifest_sha256 != ref.manifest_sha256:
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_HASH_MISMATCH")
                if item.lifecycle_state != "ACTIVE" or revision.revision_state not in {
                    "APPROVED",
                    "IN_REVIEW",
                }:
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_STALE")
                manifest = manifests.get(revision.manifest_artifact_revision_id)
                if manifest is None or (
                    not manifest[0].approved
                    or not manifest[1].approved
                    or manifest[0].artifact_type != "item-revision-manifest"
                    or manifest[1].logical_artifact_id != revision.manifest_artifact_id
                    or manifest[1].content_hash != ref.manifest_sha256
                ):
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_HASH_MISMATCH")
                if (
                    component.schema_ref not in ITEM_CONTENT_SCHEMAS
                    or component.media_type != "application/json"
                    or artifact.logical_artifact_id != component.artifact_id
                    or artifact.content_hash != component.sha256
                    or not artifact.approved
                ):
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_SOURCE_UNSUPPORTED")
                pointers.append(
                    ArtifactMemberPointer(
                        artifact_id=component.artifact_id,
                        artifact_revision_id=component.artifact_revision_id,
                        member_path=artifact.manifest["primary_file"],
                        schema_ref=component.schema_ref,
                        media_type="application/json",
                        sha256=component.sha256,
                    )
                )
            snapshot = None
            if selection.snapshot is not None:
                snapshot = session.get(
                    KnowledgeGraphSnapshotRecord, selection.snapshot.graph_snapshot_revision_id
                )
                if snapshot is None or snapshot.snapshot_sha256 != selection.snapshot.sha256:
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_HASH_MISMATCH")
                # Reuse retrieval's approved Artifact/schema checks, not an implicit latest Graph.
                self.retrieval.resolve_snapshot_pointer(
                    session, snapshot.graph_snapshot_revision_id
                )
            if request.purpose == "AUTHORIZE":
                return ChatKnowledgeCatalogReply(
                    status="SUCCEEDED", context=None, agent_state=state, error_code=None
                )
            # Metadata first; one bounded batch performs safe descriptor/hash/file reads.
            payloads = resolve_control_artifact_members(
                self.engine,
                tuple(
                    BoundedControlArtifactRead(pointer=p, maximum_bytes=256000) for p in pointers
                ),
            )
            sources: list[ChatKnowledgeSource] = []
            limitations = ["현재 대화에는 그림 픽셀이 아닌 문항의 구조화된 텍스트만 제공됩니다."]
            for ref, pointer, payload in zip(selection.references, pointers, payloads, strict=True):
                content = read_item_content(pointer.schema_ref, json.loads(payload))
                text_value = canonical_json_bytes(content.model_dump(mode="json")).decode()
                if len(text_value) > 24000:
                    raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_CONTEXT_TOO_LARGE")
                revision = by_id[ref.item_revision_id][1]
                sources.append(
                    ChatKnowledgeSource(
                        key=f"S{len(sources) + 1}",
                        item=ref,
                        display_name=str(
                            revision.metadata_json.get("title") or revision.item_type_key
                        )[:256],
                        kind="REGISTRY_DIRECT",
                        approval="APPROVED"
                        if revision.revision_state == "APPROVED"
                        and revision.approved_at is not None
                        else "PENDING",
                        pointer=pointer,
                        location="정본 문항 콘텐츠",
                        text=text_value,
                        graph_node_ids=(),
                    )
                )
            if snapshot is not None:
                associations = tuple(
                    session.scalars(
                        select(KnowledgeSnapshotAnalysisRecord).where(
                            KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                            == snapshot.graph_snapshot_revision_id,
                            KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
                            KnowledgeSnapshotAnalysisRecord.source_revision_id.in_(ids),
                        )
                    )
                )
                indexed = {a.analysis_run_id: a for a in associations}
                solutions = resolve_solution_evidence_by_base_run(
                    session, self.artifacts, base_analysis_run_ids=tuple(indexed)
                )
                reported = set()
                references = {ref.item_revision_id: ref for ref in selection.references}
                direct_sources = {source.item.item_revision_id: source for source in sources}
                for base_id, evidence in solutions.items():
                    base = indexed[base_id]
                    ref = references[base.source_revision_id]
                    component = by_id[ref.item_revision_id][2]
                    direct = direct_sources[ref.item_revision_id]
                    source_member = evidence.source.artifact_member
                    base_result = evidence.base_accepted_result
                    # V10 is an accepted additive report of the snapshot's exact V9
                    # base, not a replacement Graph member. Pin its validated member.
                    if (
                        (
                            base.source_artifact_id,
                            base.source_artifact_revision_id,
                            base.source_sha256,
                        )
                        != (component.artifact_id, component.artifact_revision_id, component.sha256)
                        or evidence.pointer.base_analysis_run_id != base_id
                        or evidence.source.item_id != ref.item_id
                        or evidence.source.item_revision_id != ref.item_revision_id
                        or (
                            source_member.artifact_id,
                            source_member.artifact_revision_id,
                            source_member.sha256,
                            source_member.schema_ref,
                            source_member.member_path,
                        )
                        != (
                            direct.pointer.artifact_id,
                            direct.pointer.artifact_revision_id,
                            direct.pointer.sha256,
                            direct.pointer.schema_ref,
                            direct.pointer.member_path,
                        )
                        or (
                            base.accepted_result_artifact_id,
                            base.accepted_result_artifact_revision_id,
                            base.accepted_result_sha256,
                        )
                        != (
                            base_result.artifact_id,
                            base_result.artifact_revision_id,
                            base_result.sha256,
                        )
                    ):
                        raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_HASH_MISMATCH")
                    if ref.item_revision_id in reported:
                        raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_STALE")
                    if direct.approval != "APPROVED":
                        continue
                    report = evidence.report
                    report_text = canonical_json_bytes(
                        {
                            "solution_summary": report.solution_summary,
                            "final_answer_summary": report.final_answer_summary,
                            "assessment_design_summary": report.assessment_design_summary,
                            "unresolved_issues": [
                                issue.model_dump(mode="json") for issue in report.unresolved_issues
                            ],
                            "official_explanation_comparison": (
                                report.official_explanation_comparison.model_dump(mode="json")
                            ),
                        }
                    ).decode()
                    if len(report_text) > 24000:
                        raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_CONTEXT_TOO_LARGE")
                    pointer_value = evidence.pointer.solution_report.model_dump(
                        mode="json", exclude={"logical_name"}
                    )
                    sources.append(
                        ChatKnowledgeSource(
                            key=f"S{len(sources) + 1}",
                            item=ref,
                            display_name=direct.display_name + " 풀이보고서",
                            kind="SOLUTION_REPORT",
                            approval="APPROVED",
                            pointer=ArtifactMemberPointer.model_validate(pointer_value),
                            location="고정 Graph 기초분석에 연결된 승인 풀이보고서 요약",
                            text=report_text,
                            graph_node_ids=(),
                        )
                    )
                    reported.add(ref.item_revision_id)
                by_revision = {entry.source_revision_id: entry for entry in associations}
                for ref in selection.references:
                    revision = by_id[ref.item_revision_id][1]
                    if revision.metadata_json.get("source_kind") != "CREATIVE":
                        continue
                    direct = direct_sources[ref.item_revision_id]
                    creative_base = by_revision.get(ref.item_revision_id)
                    if creative_base is None or direct.approval != "APPROVED":
                        continue
                    if ref.item_revision_id in reported or (
                        creative_base.source_artifact_id,
                        creative_base.source_artifact_revision_id,
                        creative_base.source_sha256,
                    ) != (
                        direct.pointer.artifact_id,
                        direct.pointer.artifact_revision_id,
                        direct.pointer.sha256,
                    ):
                        raise ChatKnowledgeResolutionError("CHAT_KNOWLEDGE_HASH_MISMATCH")
                    creative = load_registered_creative_report(session, self.artifacts, revision)
                    sources.append(
                        ChatKnowledgeSource(
                            key=f"S{len(sources) + 1}",
                            item=ref,
                            display_name=direct.display_name,
                            kind="SOLUTION_REPORT",
                            approval="APPROVED",
                            pointer=creative.lineage.role_result,
                            location="창작 원문에 연결된 독립 풀이·불일치 기록 (정확성 승인 아님)",
                            text=creative.context_text(),
                            graph_node_ids=(),
                        )
                    )
                    reported.add(ref.item_revision_id)
                if len(reported) < len(ids):
                    limitations.append(
                        "일부 선택 문항은 이 Graph 버전에 연결된 승인 풀이보고서가 없습니다."
                    )
            else:
                limitations.append("Graph 버전이 지정되지 않아 정본 문항만 참고합니다.")
            context = chat_knowledge_context(
                selection=selection, sources=tuple(sources), limitations=tuple(limitations)
            )
            return ChatKnowledgeCatalogReply(
                status="SUCCEEDED",
                context=context,
                agent_state=state,
                error_code=None,
            )
