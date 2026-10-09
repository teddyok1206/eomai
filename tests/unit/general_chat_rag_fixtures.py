"""Synthetic bounded textbook references; no production file or credential access."""

from __future__ import annotations

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatContextMessage
from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagAnchor,
    ChatRagContext,
    ChatRagDocumentReference,
    ChatRagOriginalPointer,
    ChatRagPolicy,
    ChatRagReference,
    ChatRagScope,
    ChatRagSource,
    chat_rag_context,
)
from eom_protocol.general_chat_rag_turn import (
    RagChatAnswer,
    RagChatAnswerSection,
    RagChatTurnInput,
    RagChatTurnResult,
    rag_knowledge_hash,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket

HASH = "sha256:" + "a" * 64


def scope() -> ChatRagScope:
    return ChatRagScope(
        snapshot=ChatKnowledgeSnapshot(
            graph_snapshot_revision_id="graphrev_" + "1" * 32, sha256=HASH
        ),
        policy=ChatRagPolicy(access_policy_revision_id="accessrev_" + "2" * 32, sha256=HASH),
    )


def source(
    number: int = 1, *, key: str | None = None, text: str = "합성 승인 분석."
) -> ChatRagSource:
    original = ChatRagOriginalPointer(
        artifact_id=f"artifact_{number:032x}",
        artifact_revision_id=f"rev_{number:032x}",
        member_path="source/original.pdf",
        schema_ref="eom://schemas/educational-document/pdf-source/1.0",
        media_type="application/pdf",
        sha256=HASH,
        bytes=123,
    )
    reference = ChatRagReference(
        source=ChatRagDocumentReference(
            document_id=f"edudoc_{number:032x}",
            document_revision_id=f"edudocrev_{number:032x}",
            artifact_member=original,
            first_physical_page=10,
            last_physical_page=11,
        ),
        analysis_run_id=f"analysisrun_{number:032x}",
        accepted_result=ArtifactMemberPointer(
            artifact_id=f"artifact_{number + 100:032x}",
            artifact_revision_id=f"rev_{number + 100:032x}",
            member_path="evidence/accepted-result.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/8.0",
            media_type="application/json",
            sha256=HASH,
        ),
        analysis_member=ArtifactMemberPointer(
            artifact_id=f"artifact_{number + 200:032x}",
            artifact_revision_id=f"rev_{number + 200:032x}",
            member_path="proposal/normalized.md",
            schema_ref="eom://schemas/knowledge/normalized-markdown/1.0",
            media_type="text/markdown",
            sha256=HASH,
        ),
        anchors=(
            ChatRagAnchor(
                anchor_id=f"anchor_{number}",
                artifact_revision_id=original.artifact_revision_id,
                member_path=original.member_path,
                locator="PDF physical pages 10-11",
                excerpt_sha256=HASH,
            ),
        ),
        graph_node_ids=(f"concept_{number}",),
    )
    return ChatRagSource(
        key=key or f"R{number}",
        reference=reference,
        display_name="합성 교과서",
        location="PDF 10-11쪽",
        text=text,
    )


def context(*sources: ChatRagSource) -> ChatRagContext:
    return chat_rag_context(
        scope=scope(),
        sources=sources or (source(),),
        limitations=("승인 분석 텍스트이며 원문 인용 또는 이미지 관찰이 아닙니다.",),
    )


def request(*, knowledge: ChatRagContext | None = None) -> RagChatTurnInput:
    messages = (ChatContextMessage(role="user", text="교과서 근거를 찾아 설명해 주세요."),)
    return RagChatTurnInput(
        conversation_id="chat_" + "1" * 32,
        turn_id="chatturn_" + "2" * 32,
        claim_id="chatclaim_" + "3" * 32,
        messages=messages,
        context_sha256=sha256_bytes(canonical_json_bytes([m.model_dump() for m in messages])),
        knowledge=None,
        rag_scope=scope(),
        rag_knowledge=knowledge,
    )


def result(prepared: RagChatTurnInput) -> RagChatTurnResult:
    return RagChatTurnResult(
        conversation_id=prepared.conversation_id,
        turn_id=prepared.turn_id,
        claim_id=prepared.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(prepared.model_dump(mode="json"))),
        knowledge_sha256=rag_knowledge_hash(prepared.knowledge, prepared.rag_knowledge),
        agent_state_sha256=sha256_bytes(canonical_json_bytes(None)),
        status="SUCCEEDED",
        answer=RagChatAnswer(
            answer_sections=(
                RagChatAnswerSection(
                    section_id="section_1",
                    markdown="합성 분석에 근거한 답변.",
                    support_kind="SOURCE_SUPPORTED",
                    citation_keys=("R1",),
                ),
            ),
            limitations=(),
        ),
        failure_code=None,
        tool_records=(),
    )


def ticket() -> ChatWorkerTicket:
    prepared = request()
    return ChatWorkerTicket(
        conversation_id=prepared.conversation_id,
        turn_id=prepared.turn_id,
        claim_id=prepared.claim_id,
        policy_sha256=HASH,
        request_sha256=sha256_bytes(canonical_json_bytes(prepared.model_dump(mode="json"))),
    )
