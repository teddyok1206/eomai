"""Presentation-neutral immutable assessment item content contract."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text

ChoiceId = Annotated[str, Field(pattern=r"^choice_[a-z0-9][a-z0-9_]{0,31}$")]
StatementId = Annotated[str, Field(pattern=r"^statement_[a-z][a-z0-9_]{0,31}$")]
BoundedAnswer = Annotated[str, Field(min_length=1, max_length=20_000)]

ASSESSMENT_ITEM_CONTENT_FILE_NAME: Final = "assessment-item-content.json"
ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE: Final = "application/json"
ASSESSMENT_ITEM_CONTENT_SCHEMA_REF: Final = "eom.assessment.item-content/1.0"


class MediaArtifactPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_member: str = Field(min_length=1, max_length=256)
    sha256: Sha256
    media_type: Literal["image/png", "image/jpeg"]

    @field_validator("artifact_member")
    @classmethod
    def safe_artifact_member(cls, value: str) -> str:
        member = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or member.as_posix() != value
        ):
            raise ValueError("artifact member must be a safe relative POSIX path")
        return value


class ParagraphBlock(FrozenModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["paragraph"] = "paragraph"
    purpose: Literal["stem", "prompt", "context"]
    text: str = Field(min_length=1, max_length=20_000)

    _text = field_validator("text")(_safe_text)


class EquationBlock(FrozenModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["equation"] = "equation"
    purpose: Literal["stimulus", "stem"]
    notation: Literal["latex", "hancom-equation-script"]
    source: str = Field(min_length=1, max_length=4000)

    _text = field_validator("source")(_safe_text)


class TableBlock(FrozenModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["table"] = "table"
    purpose: Literal["stimulus", "data", "reference"]
    caption: str | None = Field(default=None, max_length=500)
    headers: tuple[str, ...] = Field(min_length=1, max_length=20)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def rectangular_and_safe(self) -> TableBlock:
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("table rows must match the header width")
        if any(len(value) > 500 for value in self.headers):
            raise ValueError("table header exceeds the bounded content size")
        for value in (cell for row in self.rows for cell in row):
            if len(value) > 1000:
                raise ValueError("table cell exceeds the bounded content size")
        for value in (*self.headers, *(cell for row in self.rows for cell in row)):
            _safe_text(value)
        if self.caption is not None:
            _safe_text(self.caption)
        return self


class ImageBlock(FrozenModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["image"] = "image"
    purpose: Literal["stimulus", "reference"]
    artifact: MediaArtifactPointer
    alt_text: str = Field(min_length=1, max_length=1000)
    width_px: int = Field(ge=1, le=10_000)
    height_px: int = Field(ge=1, le=10_000)

    _text = field_validator("alt_text")(_safe_text)


class Statement(FrozenModel):
    statement_id: StatementId
    label: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=20_000)

    _text = field_validator("label", "text")(_safe_text)


class StatementSetBlock(FrozenModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["statement_set"] = "statement_set"
    purpose: Literal["claims"] = "claims"
    statements: tuple[Statement, ...] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def unique_statement_ids(self) -> StatementSetBlock:
        identifiers = [value.statement_id for value in self.statements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("statement IDs must be unique")
        return self


ContentBlock = Annotated[
    ParagraphBlock | EquationBlock | TableBlock | ImageBlock | StatementSetBlock,
    Field(discriminator="type"),
]


class Choice(FrozenModel):
    choice_id: ChoiceId
    label: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=20_000)

    _text = field_validator("label", "text")(_safe_text)


class SingleChoiceInteraction(FrozenModel):
    type: Literal["single_choice"] = "single_choice"
    choices: tuple[Choice, ...] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def unique_choice_ids(self) -> SingleChoiceInteraction:
        identifiers = [value.choice_id for value in self.choices]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("choice IDs must be unique")
        return self


class ConstructedResponseInteraction(FrozenModel):
    type: Literal["constructed_response"] = "constructed_response"
    response_format: Literal["short_text", "long_text", "numeric"]


Interaction = Annotated[
    SingleChoiceInteraction | ConstructedResponseInteraction,
    Field(discriminator="type"),
]


class StatementExplanation(FrozenModel):
    statement_id: StatementId
    text: str = Field(min_length=1, max_length=20_000)

    _text = field_validator("text")(_safe_text)


class ItemSolution(FrozenModel):
    correct_choice_ids: tuple[ChoiceId, ...] = Field(default=(), max_length=10)
    accepted_answers: tuple[BoundedAnswer, ...] = Field(default=(), max_length=20)
    explanation: str = Field(min_length=1, max_length=20_000)
    authoring_intent: str = Field(min_length=1, max_length=20_000)
    statement_explanations: tuple[StatementExplanation, ...] = Field(default=(), max_length=10)

    _text = field_validator("explanation", "authoring_intent")(_safe_text)

    @model_validator(mode="after")
    def unique_solution_references(self) -> ItemSolution:
        if len(self.correct_choice_ids) != len(set(self.correct_choice_ids)):
            raise ValueError("correct choice IDs must be unique")
        if len(self.accepted_answers) != len(set(self.accepted_answers)):
            raise ValueError("accepted answers must be unique")
        identifiers = [value.statement_id for value in self.statement_explanations]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("statement explanation IDs must be unique")
        for value in (*self.correct_choice_ids, *self.accepted_answers):
            _safe_text(value)
        return self


class ItemScore(FrozenModel):
    points: int = Field(ge=0, le=100)


class AssessmentItemContent(FrozenModel):
    """Canonical small value artifact pinned by an Item Revision component."""

    schema_version: Literal["1.0"] = "1.0"
    locale: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    title: str = Field(min_length=1, max_length=20_000)
    body: tuple[ContentBlock, ...] = Field(min_length=1, max_length=100)
    interaction: Interaction
    solution: ItemSolution
    score: ItemScore

    _text = field_validator("title")(_safe_text)

    @model_validator(mode="after")
    def consistent_references(self) -> AssessmentItemContent:
        validate_item_reference_contract(
            block_ids=tuple(block.block_id for block in self.body),
            statement_ids=tuple(
                statement.statement_id
                for block in self.body
                if isinstance(block, StatementSetBlock)
                for statement in block.statements
            ),
            interaction=self.interaction,
            solution=self.solution,
        )
        return self


def validate_item_reference_contract(
    *,
    block_ids: tuple[str, ...],
    statement_ids: tuple[str, ...],
    interaction: Interaction,
    solution: ItemSolution,
) -> None:
    """Validate canonical references shared by complete items and staged authoring drafts."""

    if len(block_ids) != len(set(block_ids)):
        raise ValueError("block IDs must be unique")
    explanation_ids = {value.statement_id for value in solution.statement_explanations}
    if explanation_ids != set(statement_ids):
        raise ValueError("statement explanations must exactly cover statement IDs")
    if isinstance(interaction, SingleChoiceInteraction):
        choices = {choice.choice_id for choice in interaction.choices}
        if len(solution.correct_choice_ids) != 1:
            raise ValueError("single-choice content requires exactly one correct choice")
        if not set(solution.correct_choice_ids).issubset(choices):
            raise ValueError("correct choice pointer does not resolve")
        if solution.accepted_answers:
            raise ValueError("single-choice content cannot declare accepted text answers")
        return
    if solution.correct_choice_ids:
        raise ValueError("constructed response cannot declare choice pointers")
    if not solution.accepted_answers:
        raise ValueError("constructed response requires at least one accepted answer")


def validate_eom_question_template_content(
    content: AssessmentItemContent,
) -> AssessmentItemContent:
    """Validate the delivery-neutral content against the fixed EOM template profile."""

    if content.locale != "ko-KR":
        raise ValueError("question template requires ko-KR content")
    by_position: dict[tuple[str, str], list[ContentBlock]] = {}
    for block in content.body:
        by_position.setdefault((block.type, block.purpose), []).append(block)

    def exactly_one(block_type: str, purpose: str) -> ContentBlock:
        values = by_position.get((block_type, purpose), [])
        if len(values) != 1:
            raise ValueError(f"question template requires one {purpose} {block_type} block")
        return values[0]

    exactly_one("paragraph", "stem")
    table = exactly_one("table", "data")
    image = exactly_one("image", "stimulus")
    equation = exactly_one("equation", "stimulus")
    exactly_one("paragraph", "prompt")
    statements = exactly_one("statement_set", "claims")
    if len(content.body) != 6:
        raise ValueError("question template requires exactly six supported content blocks")
    if not isinstance(table, TableBlock) or len(table.headers) != 3 or len(table.rows) != 1:
        raise ValueError("question template requires one data row of width three")
    if not isinstance(image, ImageBlock) or (
        image.artifact.media_type,
        image.width_px,
        image.height_px,
    ) != ("image/png", 800, 500):
        raise ValueError("question template requires one pinned 800x500 PNG")
    if (
        not isinstance(equation, EquationBlock)
        or equation.notation != "hancom-equation-script"
        or re.fullmatch(r"[A-Za-z0-9+\-*/=() ._^]+", equation.source) is None
    ):
        raise ValueError("question template equation is outside the bounded Hancom grammar")
    if not isinstance(statements, StatementSetBlock) or [
        value.label for value in statements.statements
    ] != ["ㄱ", "ㄴ", "ㄷ"]:
        raise ValueError("question template requires the ordered ㄱ/ㄴ/ㄷ statement set")
    if (
        not isinstance(content.interaction, SingleChoiceInteraction)
        or len(content.interaction.choices) != 5
    ):
        raise ValueError("question template requires exactly five single-choice choices")
    if content.score.points not in {2, 3}:
        raise ValueError("question template supports a score of two or three points")
    return content
