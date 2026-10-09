"""Bounded presentation mirrors of RAG source cards; no retrieval or authority rules."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from eom_web_gui.chat_grounding_contracts import ChatCitationReceipt, ChatSourceCard
from eom_web_gui.chat_knowledge_contracts import ChatItemReference
from eom_web_gui.contracts import UtcDatetime, WebModel

type Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
type ArtifactId = Annotated[str, Field(pattern=r"^artifact_[0-9a-f]{32}$")]
type RevisionId = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{32}$")]


def _relative_member(value: str) -> str:
    if (
        value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(p in {"", ".", ".."} for p in value.split("/"))
    ):
        raise ValueError("invalid relative member")
    return value


class _ChatRagMemberIdentity(WebModel):
    artifact_id: ArtifactId
    artifact_revision_id: RevisionId
    member_path: str = Field(min_length=1, max_length=512)
    sha256: Hash
    _member = field_validator("member_path")(_relative_member)


class ChatRagMember(_ChatRagMemberIdentity):
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)


class ChatRagOriginalMember(_ChatRagMemberIdentity):
    schema_ref: str | None = Field(min_length=1, max_length=256)
    media_type: Literal["application/pdf", "application/json"]
    bytes: int = Field(ge=1, le=1073741824)


class ChatRagDocument(WebModel):
    source_kind: Literal["DOCUMENT_REVISION"]
    source_class: Literal["TEXTBOOK"]
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalMember
    first_physical_page: int = Field(ge=1, le=100000)
    last_physical_page: int = Field(ge=1, le=100000)


class ChatRagIntake(WebModel):
    source_kind: Literal["CONTENT_INTAKE_FILE"]
    source_class: Literal["TEXTBOOK", "PAST_EXAM"]
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalMember


class ChatRagItem(WebModel):
    source_kind: Literal["APPROVED_ITEM_REVISION"]
    source_class: Literal["PAST_EXAM", "APPROVED_ITEM"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalMember


class ChatRagAnchor(WebModel):
    anchor_id: str = Field(min_length=1, max_length=96)
    artifact_revision_id: RevisionId
    member_path: str = Field(min_length=1, max_length=512)
    locator: str = Field(min_length=1, max_length=256)
    excerpt_sha256: Hash

    _member = field_validator("member_path")(_relative_member)


class ChatRagReference(WebModel):
    source: Annotated[
        ChatRagDocument | ChatRagIntake | ChatRagItem, Field(discriminator="source_kind")
    ]
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    accepted_result: ChatRagMember
    analysis_member: ChatRagMember
    anchors: tuple[ChatRagAnchor, ...] = Field(min_length=1, max_length=32)
    graph_node_ids: tuple[Annotated[str, Field(min_length=1, max_length=72)], ...] = Field(
        min_length=1, max_length=32
    )


class ChatRagSourceCard(WebModel):
    key: str = Field(pattern=r"^R[1-3]$")
    reference: ChatRagReference
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["RAG_ANALYSIS"]
    approval: Literal["APPROVED"]
    location: str = Field(min_length=1, max_length=256)
    text_kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"]


class ChatRagCitationReceipt(WebModel):
    schema_version: Literal["chat-knowledge-citation-receipt/2.0"]
    request_sha256: Hash
    result_sha256: Hash
    context_sha256: Hash
    used_source_keys: tuple[str, ...] = Field(max_length=12)
    verified_references: tuple[ChatItemReference, ...] = Field(max_length=3)
    verified_rag_references: tuple[ChatRagReference, ...] = Field(max_length=3)
    meaning: Literal["CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"]


class ChatTurnGroundingV2(WebModel):
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    sources: tuple[
        Annotated[ChatSourceCard | ChatRagSourceCard, Field(discriminator="kind")], ...
    ] = Field(max_length=12)
    # V2 views can include older turns without rewriting their receipt bytes.
    receipt: ChatRagCitationReceipt | ChatCitationReceipt | None
    observed_at: UtcDatetime | None


class ChatGroundingViewsV2(WebModel):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    values: tuple[ChatTurnGroundingV2, ...] = Field(max_length=50)
