"""Small presentation DTOs; no worker/storage dependency in the Web runtime."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from eom_web_gui.chat_knowledge_contracts import ChatItemReference
from eom_web_gui.contracts import UtcDatetime, WebModel
from eom_web_gui.general_chat_contracts import ChatSubmission


class ChatPinnedGraph(WebModel):
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ChatPinnedSelection(WebModel):
    references: tuple[ChatItemReference, ...] = Field(min_length=1, max_length=3)
    snapshot: ChatPinnedGraph | None

    @model_validator(mode="after")
    def unique(self) -> ChatPinnedSelection:
        if len({r.item_revision_id for r in self.references}) != len(self.references):
            raise ValueError("duplicate selected revision")
        return self


class ChatGroundedTurnSubmission(ChatSubmission):
    schema_version: Literal["general-chat-grounded-submission/1.0"] = (
        "general-chat-grounded-submission/1.0"
    )
    selection: ChatPinnedSelection | None
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class ChatGroundingSubmission(WebModel):
    turn_ids: tuple[Annotated[str, Field(pattern=r"^chatturn_[0-9a-f]{32}$")], ...] = Field(
        min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def unique(self) -> ChatGroundingSubmission:
        if len(set(self.turn_ids)) != len(self.turn_ids):
            raise ValueError("duplicate chat turn")
        return self


class ChatSourceCard(WebModel):
    key: str = Field(pattern=r"^S[1-9]$")
    item: ChatItemReference
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["REGISTRY_DIRECT", "GRAPH_ANALYSIS", "SOLUTION_REPORT"]
    approval: Literal["APPROVED", "PENDING"]
    location: str = Field(min_length=1, max_length=256)


class ChatCitationReceipt(WebModel):
    schema_version: Literal["chat-knowledge-citation-receipt/1.0"]
    request_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    used_source_keys: tuple[str, ...] = Field(max_length=9)
    verified_references: tuple[ChatItemReference, ...] = Field(max_length=3)
    meaning: Literal["CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"]


class ChatTurnGrounding(WebModel):
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    sources: tuple[ChatSourceCard, ...] = Field(max_length=9)
    receipt: ChatCitationReceipt | None
    observed_at: UtcDatetime | None


class ChatGroundingViews(WebModel):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    values: tuple[ChatTurnGrounding, ...] = Field(max_length=50)
