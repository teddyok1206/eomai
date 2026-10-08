"""Explicit bounded Item discovery, separate from model/evidence execution."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from eom_web_gui.contracts import ItemPreviewApproval, UtcDatetime, WebModel


class ChatItemApproval(ItemPreviewApproval):
    schema_version: Literal["item-approval-view/1.0"] = "item-approval-view/1.0"
    approved_by: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ChatGraphSnapshot(WebModel):
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ChatItemReference(WebModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ChatRecentQuery(WebModel):
    kind: Literal["RECENT"]
    source: Literal["ALL", "GENERATED"] = "ALL"


class ChatExactQuery(WebModel):
    kind: Literal["EXACT"]
    references: tuple[ChatItemReference, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_revisions(self) -> ChatExactQuery:
        if len({ref.item_revision_id for ref in self.references}) != len(self.references):
            raise ValueError("duplicate pinned revision")
        return self


class ChatExamQuery(WebModel):
    kind: Literal["EXAM"]
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    item_number: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def valid_school_grade(self) -> ChatExamQuery:
        if self.target_school_level != "ELEMENTARY" and self.target_grade > 3:
            raise ValueError("invalid secondary school grade")
        return self


class ChatTopicQuery(WebModel):
    kind: Literal["TOPIC"]
    terms: tuple[
        Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z0-9가-힣_]+$")], ...
    ] = Field(min_length=1, max_length=8)
    source: Literal["ALL", "PAST_EXAM", "GENERATED"] = "ALL"

    @model_validator(mode="after")
    def unique_terms(self) -> ChatTopicQuery:
        if len(set(self.terms)) != len(self.terms):
            raise ValueError("duplicate search term")
        return self


ChatQuery = Annotated[
    ChatRecentQuery | ChatExactQuery | ChatExamQuery | ChatTopicQuery,
    Field(discriminator="kind"),
]


class ChatKnowledgeRequest(WebModel):
    schema_version: Literal["chat-knowledge-query/1.0"] = "chat-knowledge-query/1.0"
    query: ChatQuery
    snapshot: ChatGraphSnapshot | None = None
    limit: int = Field(default=20, ge=1, le=20)


class ChatExamPlacement(WebModel):
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    display_label: str = Field(min_length=1, max_length=512)
    item_number: int = Field(ge=1, le=200)


class ChatItemCard(ChatItemReference):
    revision_number: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=512)
    created_at: UtcDatetime
    approval: ChatItemApproval
    source_kind: Literal["PAST_EXAM", "GENERATED", "UNCLASSIFIED"]
    graph_membership: Literal["INDEXED", "NOT_INDEXED", "UNAVAILABLE"]
    exam: ChatExamPlacement | None

    @model_validator(mode="after")
    def discoverable_card(self) -> ChatItemCard:
        if self.approval.status not in {"PENDING", "APPROVED"}:
            raise ValueError("ineligible Item cannot be a discovery candidate")
        if self.exam is not None and self.source_kind != "PAST_EXAM":
            raise ValueError("only past exams carry a placement")
        return self


class ChatKnowledgeSelection(WebModel):
    schema_version: Literal["chat-knowledge-selection/1.0"] = "chat-knowledge-selection/1.0"
    values: tuple[ChatItemCard, ...] = Field(max_length=20)
    snapshot: ChatGraphSnapshot | None
    truncated: bool
    model_calls: Literal[0] = 0

    @model_validator(mode="after")
    def unique_cards_and_honest_graph(self) -> ChatKnowledgeSelection:
        keys = {
            (
                card.item_revision_id,
                card.exam.assessment_occurrence_revision_id if card.exam else None,
                card.exam.item_number if card.exam else None,
            )
            for card in self.values
        }
        if len(keys) != len(self.values):
            raise ValueError("duplicate discovery cards")
        if any(
            (card.graph_membership == "UNAVAILABLE") != (self.snapshot is None)
            for card in self.values
        ):
            raise ValueError("graph membership must name its snapshot or be unavailable")
        return self
