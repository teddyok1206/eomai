"""Typed publication values for variable canonical Items at the local Builder boundary."""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from eom_hwpx_contracts.models import StrictModel, _valid_xml_text

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
BlockId = Annotated[str, Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=20000), AfterValidator(_valid_xml_text)]
Label = Annotated[str, Field(min_length=1, max_length=16), AfterValidator(_valid_xml_text)]
Cell = Annotated[str, Field(max_length=1000), AfterValidator(_valid_xml_text)]
NATIVE_ITEM_TEMPLATE_SHA256: Final = (
    "sha256:22ded5c8de95a8c9659544749fd21a109f40a1c7b5963e123887c0d9ca51a687"
)


class NativeItemParagraph(StrictModel):
    type: Literal["paragraph"] = "paragraph"
    block_id: BlockId
    purpose: Literal["stem", "prompt", "context"]
    text: Text


class NativeItemEquation(StrictModel):
    type: Literal["equation"] = "equation"
    block_id: BlockId
    notation: Literal["latex", "hancom-equation-script"]
    source: Annotated[str, Field(min_length=1, max_length=4000), AfterValidator(_valid_xml_text)]


class NativeItemTable(StrictModel):
    type: Literal["table"] = "table"
    block_id: BlockId
    caption: Annotated[str, Field(max_length=500), AfterValidator(_valid_xml_text)] | None
    headers: tuple[Annotated[str, Field(max_length=500), AfterValidator(_valid_xml_text)], ...] = (
        Field(min_length=1, max_length=20)
    )
    rows: tuple[Annotated[tuple[Cell, ...], Field(min_length=1, max_length=20)], ...] = Field(
        min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("native publication table must remain rectangular")
        return self


class NativeItemImage(StrictModel):
    type: Literal["image"] = "image"
    block_id: BlockId
    ordinal: int = Field(strict=True, ge=1, le=100)
    local_file: str = Field(pattern=r"^images/[0-9a-f]{64}\.(png|jpg)$")
    sha256: Sha256
    media_type: Literal["image/png", "image/jpeg"]
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)

    @model_validator(mode="after")
    def content_addressed_image(self) -> Self:
        suffix = "png" if self.media_type == "image/png" else "jpg"
        if self.local_file != f"images/{self.sha256.removeprefix('sha256:')}.{suffix}":
            raise ValueError("native publication image filename differs from its pinned bytes")
        return self


class NativeItemStatement(StrictModel):
    statement_id: str = Field(pattern=r"^statement_[a-z][a-z0-9_]{0,31}$")
    label: Label
    text: Text


class NativeItemStatements(StrictModel):
    type: Literal["statement_set"] = "statement_set"
    block_id: BlockId
    statements: tuple[NativeItemStatement, ...] = Field(min_length=2, max_length=10)


class NativeItemChoice(StrictModel):
    choice_id: str = Field(pattern=r"^choice_[a-z0-9][a-z0-9_]{0,31}$")
    label: Label
    text: Text


NativeItemBlock = Annotated[
    NativeItemParagraph
    | NativeItemEquation
    | NativeItemTable
    | NativeItemImage
    | NativeItemStatements,
    Field(discriminator="type"),
]


class NativeItemRenderRequest(StrictModel):
    schema_version: Literal["native-item-render-request/1.0"] = "native-item-render-request/1.0"
    profile: Literal["CANONICAL_ITEM_NATIVE_V1"] = "CANONICAL_ITEM_NATIVE_V1"
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_sha256: Sha256
    effective_content_sha256: Sha256
    template_sha256: Literal[
        "sha256:22ded5c8de95a8c9659544749fd21a109f40a1c7b5963e123887c0d9ca51a687"
    ] = NATIVE_ITEM_TEMPLATE_SHA256
    item_number: int = Field(strict=True, ge=1, le=200)
    title: Text
    points: int = Field(strict=True, ge=0, le=100)
    body: tuple[NativeItemBlock, ...] = Field(min_length=1, max_length=100)
    choices: tuple[NativeItemChoice, ...] = Field(max_length=10)
    accepted_answers: tuple[Text, ...] = Field(max_length=20)
    correct_choice_id: str | None = Field(pattern=r"^choice_[a-z0-9][a-z0-9_]{0,31}$")
    authoring_intent: Text
    explanation: Text
    statement_explanations: tuple[NativeItemStatement, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def exact_publication_references(self) -> Self:
        ids = [block.block_id for block in self.body]
        if len(ids) != len(set(ids)):
            raise ValueError("native publication repeats a block identity")
        images = tuple(block for block in self.body if isinstance(block, NativeItemImage))
        if tuple(image.ordinal for image in images) != tuple(range(1, len(images) + 1)):
            raise ValueError("native publication image uses are not ordered")
        by_file: dict[str, tuple[str, int, int]] = {}
        for image in images:
            identity = (image.media_type, image.width_px, image.height_px)
            if by_file.setdefault(image.local_file, identity) != identity:
                raise ValueError("native publication repeated image metadata differs")
        choices = {choice.choice_id for choice in self.choices}
        if len(choices) != len(self.choices):
            raise ValueError("native publication repeats a choice identity")
        if self.choices:
            if (
                len(self.choices) < 2
                or self.correct_choice_id not in choices
                or self.accepted_answers
            ):
                raise ValueError("native publication answer does not resolve")
        elif self.correct_choice_id is not None or not self.accepted_answers:
            raise ValueError("native constructed response has no accepted answer")
        if len(self.accepted_answers) != len(set(self.accepted_answers)):
            raise ValueError("native publication repeats an accepted answer")
        statements = [
            row
            for block in self.body
            if isinstance(block, NativeItemStatements)
            for row in block.statements
        ]
        statement_ids = {row.statement_id for row in statements}
        labels = {row.statement_id: row.label for row in statements}
        if len(statements) != len(statement_ids) or len(self.statement_explanations) != len(
            statement_ids
        ):
            raise ValueError("native publication statement explanation count differs")
        if {row.statement_id for row in self.statement_explanations} != statement_ids or any(
            labels.get(row.statement_id) != row.label for row in self.statement_explanations
        ):
            raise ValueError("native publication statement explanations do not resolve")
        return self


class NativeItemRenderResult(StrictModel):
    schema_version: Literal["native-item-render-result/1.0"] = "native-item-render-result/1.0"
    profile: Literal["CANONICAL_ITEM_NATIVE_V1"] = "CANONICAL_ITEM_NATIVE_V1"
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    request_sha256: Sha256
    source_sha256: Sha256
    effective_content_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    output_sha256: Sha256 | None
    output_size_bytes: int | None = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    native_equation_count: int = Field(strict=True, ge=0, le=10000)
    content_table_count: int = Field(strict=True, ge=0, le=100)
    image_count: int = Field(strict=True, ge=0, le=100)
    failure_code: (
        Literal[
            "HWPX_NATIVE_ITEM_INPUT_INVALID",
            "HWPX_NATIVE_ITEM_RENDER_FAILED",
            "HWPX_NATIVE_ITEM_PRESERVATION_FAILED",
        ]
        | None
    )

    @model_validator(mode="after")
    def complete_terminal_evidence(self) -> Self:
        if self.status == "SUCCEEDED":
            if (
                self.output_sha256 is None
                or self.output_size_bytes is None
                or self.failure_code is not None
            ):
                raise ValueError("native Item success requires an exact output")
        elif (
            self.output_sha256 is not None
            or self.output_size_bytes is not None
            or self.failure_code is None
            or self.native_equation_count
            or self.content_table_count
            or self.image_count
        ):
            raise ValueError("failed native Item cannot advertise an output")
        return self
