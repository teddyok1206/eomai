"""Strict HWPX POC request and result models."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _valid_xml_text(value: str) -> str:
    for character in value:
        codepoint = ord(character)
        if not (
            codepoint in {0x9, 0xA, 0xD}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            raise ValueError("text contains a code point forbidden by XML 1.0")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentTeamTable(StrictModel):
    """Semantic Markdown table consumed by the reviewed content-team renderer."""

    kind: Literal["TABLE"] = "TABLE"
    label: Literal["", "(가)", "(나)"] = ""
    headers: tuple[str, ...] = Field(min_length=2, max_length=5)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=100)
    alignments: tuple[Literal["default", "left", "right", "center"], ...]

    @model_validator(mode="after")
    def rectangular_xml_safe_table(self) -> ContentTeamTable:
        width = len(self.headers)
        if len(self.alignments) != width or any(len(row) != width for row in self.rows):
            raise ValueError("content-team table rows and alignments must match header width")
        for cell in (*self.headers, *(cell for row in self.rows for cell in row)):
            if not cell or len(cell) > 2000:
                raise ValueError("content-team table cell length is invalid")
            _valid_xml_text(cell)
        return self


class ContentTeamImageSlot(StrictModel):
    """An empty image slot; image bytes remain a separately pinned artifact."""

    kind: Literal["IMAGE"] = "IMAGE"
    label: Literal["", "(가)", "(나)"] = ""


class ContentTeamLabeledBlock(StrictModel):
    """Prototype-backed 자료/조건 content, independent of subject matter."""

    kind: Literal["DATA", "CONDITION"]
    content: str = Field(min_length=1, max_length=12000)

    @field_validator("content")
    @classmethod
    def labeled_block_xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


ContentTeamVisual = Annotated[
    ContentTeamTable | ContentTeamImageSlot,
    Field(discriminator="kind"),
]


class ContentTeamInquiry(StrictModel):
    kind: Literal["탐구", "실험"]
    goal: str | None = Field(default=None, min_length=1, max_length=4000)
    procedure: str = Field(min_length=1, max_length=12000)
    result: str = Field(min_length=1, max_length=12000)

    @field_validator("goal", "procedure", "result")
    @classmethod
    def inquiry_xml_text(cls, value: str | None) -> str | None:
        return None if value is None else _valid_xml_text(value)

    @model_validator(mode="after")
    def ordered_procedure_steps(self) -> ContentTeamInquiry:
        labels = tuple(
            match.group(1) for match in re.finditer(r"(?m)^\s*\(([가-아])\)\s+", self.procedure)
        )
        expected = tuple("가나다라마바사아")[: len(labels)]
        if len(labels) < 3 or labels != expected:
            raise ValueError("content-team inquiry procedure requires three ordered steps")
        return self


class ContentTeamStatement(StrictModel):
    label: Literal["ㄱ", "ㄴ", "ㄷ"]
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def statement_xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class ContentTeamChoice(StrictModel):
    number: Literal["①", "②", "③", "④", "⑤"]
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def choice_xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class ContentTeamAnswerBase(StrictModel):
    number: Literal["①", "②", "③", "④", "⑤"]
    answer_content: str = Field(min_length=1, max_length=2000, pattern=r"^[^\r\n]+$")
    raw_line: str = Field(
        min_length=9,
        max_length=2020,
        pattern=r"^정답 : [①②③④⑤] \([^\r\n]+\)$",
    )

    @model_validator(mode="after")
    def exact_answer_line(self) -> ContentTeamAnswerBase:
        if self.raw_line != f"정답 : {self.number} ({self.answer_content})":
            raise ValueError("content-team answer line and answer content differ")
        return self


class ContentTeamCombinationAnswer(ContentTeamAnswerBase):
    answer_kind: Literal["STATEMENT_COMBINATION"] = "STATEMENT_COMBINATION"
    statement_labels: tuple[Literal["ㄱ", "ㄴ", "ㄷ"], ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def exact_statement_combination(self) -> ContentTeamCombinationAnswer:
        if tuple(dict.fromkeys(self.statement_labels)) != self.statement_labels:
            raise ValueError("content-team answer statement labels must be unique")
        if self.answer_content != ", ".join(self.statement_labels):
            raise ValueError("content-team answer line and statement combination differ")
        return self


class ContentTeamDirectChoiceAnswer(ContentTeamAnswerBase):
    answer_kind: Literal["DIRECT_CHOICE"] = "DIRECT_CHOICE"
    statement_labels: tuple[Literal["ㄱ", "ㄴ", "ㄷ"], ...] = Field(max_length=0)


type ContentTeamAnswer = Annotated[
    ContentTeamCombinationAnswer | ContentTeamDirectChoiceAnswer,
    Field(discriminator="answer_kind"),
]


class ContentTeamExplanationSections(StrictModel):
    authoring_intent: str = Field(min_length=1, max_length=12000)
    concept_source: str = Field(min_length=1, max_length=12000)
    correct_answer: str = Field(min_length=1, max_length=24000)
    wrong_answer: str = Field(max_length=24000)

    @field_validator("authoring_intent", "concept_source", "correct_answer", "wrong_answer")
    @classmethod
    def explanation_xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class ContentTeamEditorialDraft(StrictModel):
    """Subject-neutral authoring data retained by the content-team editor profile."""

    renderer_profile: Literal["content-team-hwp-question-editor-v1"] = (
        "content-team-hwp-question-editor-v1"
    )
    authoring_prompt_sha256: Literal[
        "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    ] = "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    handoff_archive_sha256: Literal[
        "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    ] = "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    item_number: int = Field(ge=1, le=999)
    score_display: Literal["2", "2.5", "3"]
    stem: str = Field(min_length=1, max_length=24000)
    bottom_stem: str = Field(min_length=1, max_length=4000)
    inquiry: ContentTeamInquiry | None = None
    labeled_blocks: tuple[ContentTeamLabeledBlock, ...] = Field(max_length=2)
    visuals: tuple[ContentTeamVisual, ...] = Field(max_length=2)
    visual_layout: Literal[
        "NONE",
        "IMAGE_ONLY",
        "TABLE_ONLY",
        "IMAGE_TABLE",
        "TABLE_IMAGE",
        "IMAGE_IMAGE",
        "TABLE_TABLE",
        "INQUIRY_BOX",
    ]
    statements: tuple[()] | tuple[ContentTeamStatement, ContentTeamStatement, ContentTeamStatement]
    choices: tuple[ContentTeamChoice, ...] = Field(min_length=5, max_length=5)
    answer: ContentTeamAnswer
    explanations: ContentTeamExplanationSections
    equation_sources: tuple[str, ...] = Field(max_length=128)

    @field_validator("stem", "bottom_stem", "equation_sources")
    @classmethod
    def editorial_xml_text(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        if isinstance(value, tuple):
            if any(not source or len(source) > 500 for source in value):
                raise ValueError("content-team equation source length is invalid")
            return tuple(_valid_xml_text(source) for source in value)
        return _valid_xml_text(value)

    @model_validator(mode="after")
    def exact_order_and_visual_layout(self) -> ContentTeamEditorialDraft:
        statement_labels = tuple(value.label for value in self.statements)
        if statement_labels not in ((), ("ㄱ", "ㄴ", "ㄷ")):
            raise ValueError("content-team statements must be absent or preserve ㄱ/ㄴ/ㄷ order")
        if tuple(value.number for value in self.choices) != ("①", "②", "③", "④", "⑤"):
            raise ValueError("content-team choices must preserve ① through ⑤ order")
        if bool(self.statements) != (self.answer.answer_kind == "STATEMENT_COMBINATION"):
            raise ValueError("content-team statement and answer forms differ")
        if self.answer.answer_kind == "STATEMENT_COMBINATION":
            selected = self.choices[("①", "②", "③", "④", "⑤").index(self.answer.number)].text
            normalized = tuple(label for label in ("ㄱ", "ㄴ", "ㄷ") if label in selected)
            if normalized != self.answer.statement_labels:
                raise ValueError("content-team answer combination differs from the selected choice")
        explanation_labels = {
            name: tuple(
                match.group(1)
                for match in re.finditer(r"(?m)^([ㄱㄴㄷ])\.\s+", getattr(self.explanations, name))
            )
            for name in ("correct_answer", "wrong_answer")
        }
        if any(len(labels) != len(set(labels)) for labels in explanation_labels.values()):
            raise ValueError("content-team explanation labels must be unique")
        if self.answer.answer_kind == "STATEMENT_COMBINATION":
            correct_labels = self.answer.statement_labels
            wrong_labels = tuple(
                label for label in ("ㄱ", "ㄴ", "ㄷ") if label not in correct_labels
            )
            if explanation_labels != {
                "correct_answer": correct_labels,
                "wrong_answer": wrong_labels,
            }:
                raise ValueError(
                    "content-team explanation labels must partition the answer statements"
                )
            if not wrong_labels and self.explanations.wrong_answer:
                raise ValueError("an all-correct item must keep the wrong-answer section empty")
        labeled_kinds = tuple(value.kind for value in self.labeled_blocks)
        if labeled_kinds not in ((), ("DATA",), ("CONDITION",), ("DATA", "CONDITION")):
            raise ValueError(
                "content-team labeled blocks must be unique and DATA precedes CONDITION"
            )
        if self.inquiry is not None:
            if self.visuals or self.visual_layout != "INQUIRY_BOX":
                raise ValueError("inquiry content cannot use the general visual-slot layout")
            return self
        kinds = tuple(value.kind for value in self.visuals)
        labels = tuple(value.label for value in self.visuals)
        expected = {
            (): ("NONE", ()),
            ("IMAGE",): ("IMAGE_ONLY", ("",)),
            ("TABLE",): ("TABLE_ONLY", ("",)),
            ("IMAGE", "TABLE"): ("IMAGE_TABLE", ("", "")),
            ("TABLE", "IMAGE"): ("TABLE_IMAGE", ("", "")),
            ("IMAGE", "IMAGE"): ("IMAGE_IMAGE", ("(가)", "(나)")),
            ("TABLE", "TABLE"): ("TABLE_TABLE", ("(가)", "(나)")),
        }.get(kinds)
        if expected != (self.visual_layout, labels):
            raise ValueError("content-team visual items do not match a canonical layout")
        return self


class ContentTeamEditorialQuestion(ContentTeamEditorialDraft):
    """A draft bound to the exact Markdown materialization that produced it."""

    schema_version: Literal["1.0"] = "1.0"
    source_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class ContentTeamItemSource(StrictModel):
    """Pinned JSON and Markdown members of one canonical Catalog artifact revision."""

    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    schema_ref: Literal["eom.assessment.item-content/2.0"] = "eom.assessment.item-content/2.0"
    json_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    json_file: Literal["input/item-content.json"] = "input/item-content.json"
    markdown_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    markdown_file: Literal["input/content-team-item.md"] = "input/content-team-item.md"


class ContentTeamHandoffMember(StrictModel):
    purpose: Literal[
        "automation-template",
        "equation-prototypes",
        "visual-slots-left-right",
        "visual-slots-two-tables",
        "labeled-data-condition",
        "table-2-column",
        "table-3-column",
        "table-3-column-long-equation",
        "table-4-column",
        "inquiry-experiment-box",
    ]
    sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    size: int = Field(ge=1, le=25 * 1024 * 1024)


CONTENT_TEAM_HANDOFF_MEMBERS: tuple[tuple[str, str, int], ...] = (
    (
        "automation-template",
        "sha256:22ded5c8de95a8c9659544749fd21a109f40a1c7b5963e123887c0d9ca51a687",
        77187,
    ),
    (
        "equation-prototypes",
        "sha256:2a493d5e90f1d80cb28805f2f9fecf9c18853cbc0521d7acc7a64cc249c1c45a",
        32507,
    ),
    (
        "visual-slots-left-right",
        "sha256:65674a863762e29230bab2010b6a38e52a1f44d50cb6b0509c1205ce44c4c593",
        76918,
    ),
    (
        "visual-slots-two-tables",
        "sha256:3d5f54f3915d071d978f05037dffc03cec7385a87cb5a16fa460414f43cbbb13",
        77215,
    ),
    (
        "labeled-data-condition",
        "sha256:cf517788ed36fe388e2580a1455dc5e343fcb68aeca5e007194180aafbf91e76",
        79483,
    ),
    (
        "table-2-column",
        "sha256:d29e2891481554869540dfd3c62f5217cd589b3bb3197f89b3126ced9f8332eb",
        79032,
    ),
    (
        "table-3-column",
        "sha256:9812ab156524e34f51d10123a0a8bb7991947cba95e960da1a03b5fdb5d5d3b9",
        79257,
    ),
    (
        "table-3-column-long-equation",
        "sha256:5521c89d0772e59a963994db09c946e6407ca2664c51de7e738033645e192335",
        87409,
    ),
    (
        "table-4-column",
        "sha256:dae3a87c48c36bc3fdaf4efd3e746f7a9d00f70217876a700e320cafc110e9d9",
        79649,
    ),
    (
        "inquiry-experiment-box",
        "sha256:b11841cbc812f6d0179d8ce59fb2d0d4c60706445b12e03726d5819e35f70d6f",
        58238,
    ),
)


class ContentTeamHandoffSnapshot(StrictModel):
    """Immutable source/archive identity used by every renderer attempt."""

    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    archive_sha256: Literal[
        "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    ] = "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    archive_file: Literal["input/handoff.zip"] = "input/handoff.zip"
    entry_count: Literal[606] = 606
    uncompressed_bytes: Literal[49280719] = 49280719
    profile_sha256: Literal[
        "sha256:ce08671ad433026ec51e68ddfc6a4d7ffe33ae8a792c1791dfa26b9b62e78863"
    ] = "sha256:ce08671ad433026ec51e68ddfc6a4d7ffe33ae8a792c1791dfa26b9b62e78863"
    members: tuple[ContentTeamHandoffMember, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def exact_reviewed_members(self) -> ContentTeamHandoffSnapshot:
        actual = tuple((member.purpose, member.sha256, member.size) for member in self.members)
        if actual != CONTENT_TEAM_HANDOFF_MEMBERS:
            raise ValueError("content-team handoff member profile is not the reviewed snapshot")
        return self


class ContentTeamRenderRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    renderer_profile: Literal["content-team-hwp-question-editor-v1"] = (
        "content-team-hwp-question-editor-v1"
    )
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    source: ContentTeamItemSource
    handoff: ContentTeamHandoffSnapshot
    output_directory: Literal["output"] = "output"


class ContentTeamImageSource(StrictModel):
    visual_ordinal: int = Field(ge=0, le=1)
    label: Literal["", "(가)", "(나)"]
    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    artifact_member: Literal["generated-stimulus.png"] = "generated-stimulus.png"
    sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    schema_ref: Literal["eom://schemas/generated-item/stimulus-png/3.0"] = (
        "eom://schemas/generated-item/stimulus-png/3.0"
    )
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    alt_text: str = Field(min_length=1, max_length=1000)
    file_name: str = Field(pattern=r"^input/visual-[01]\.png$")

    @model_validator(mode="after")
    def file_matches_ordinal(self) -> ContentTeamImageSource:
        if self.file_name != f"input/visual-{self.visual_ordinal}.png":
            raise ValueError("content-team image file does not match its visual ordinal")
        return self


class ContentTeamRenderRequestV2(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    renderer_profile: Literal["content-team-hwp-question-editor-v2"] = (
        "content-team-hwp-question-editor-v2"
    )
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    source: ContentTeamItemSource
    handoff: ContentTeamHandoffSnapshot
    images: tuple[ContentTeamImageSource, ...] = Field(max_length=2)
    output_directory: Literal["output"] = "output"

    @model_validator(mode="after")
    def ordered_unique_images(self) -> ContentTeamRenderRequestV2:
        ordinals = tuple(image.visual_ordinal for image in self.images)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("content-team images must be unique and ordered")
        return self


class ContentTeamBuildResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    renderer_profile: Literal["content-team-hwp-question-editor-v1"] = (
        "content-team-hwp-question-editor-v1"
    )
    renderer_version: Literal["1.0.0"] = "1.0.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    source_json_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_markdown_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    handoff_archive_sha256: Literal[
        "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    ] = "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    status: Literal["SUCCEEDED", "FAILED"]
    output_file: Literal["output/content-team-item.hwpx"] | None
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    package_manifest_file: Literal["output/package-manifest.json"] | None
    renderer_report_file: Literal["output/content-team-validation.json"] | None
    equation_count: int = Field(ge=0, le=128)
    table_count: int = Field(ge=0, le=20)
    visual_count: int = Field(ge=0, le=2)
    labeled_block_count: int = Field(ge=0, le=2)
    warnings: tuple[str, ...] = Field(max_length=20)
    errors: tuple[str, ...] = Field(max_length=20)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def terminal_files_match_status(self) -> ContentTeamBuildResult:
        materialized = (
            self.output_file,
            self.output_sha256,
            self.package_manifest_file,
            self.renderer_report_file,
        )
        if self.status == "SUCCEEDED":
            if any(value is None for value in materialized) or self.errors:
                raise ValueError("successful content-team build requires validated output")
        elif any(value is not None for value in materialized) or not self.errors:
            raise ValueError("failed content-team build cannot expose output")
        if self.completed_at < self.started_at:
            raise ValueError("content-team build completion precedes its start")
        return self


class ContentTeamBuildResultV2(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    renderer_profile: Literal["content-team-hwp-question-editor-v2"] = (
        "content-team-hwp-question-editor-v2"
    )
    renderer_version: Literal["2.0.0"] = "2.0.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    source_json_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_markdown_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    handoff_archive_sha256: Literal[
        "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    ] = "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    status: Literal["SUCCEEDED", "FAILED"]
    output_file: Literal["output/content-team-item.hwpx"] | None
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    package_manifest_file: Literal["output/package-manifest.json"] | None
    renderer_report_file: Literal["output/content-team-validation.json"] | None
    equation_count: int = Field(ge=0, le=128)
    table_count: int = Field(ge=0, le=20)
    visual_count: int = Field(ge=0, le=2)
    labeled_block_count: int = Field(ge=0, le=2)
    warnings: tuple[str, ...] = Field(max_length=20)
    errors: tuple[str, ...] = Field(max_length=20)
    started_at: datetime
    completed_at: datetime
    image_set_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    embedded_image_count: int = Field(ge=0, le=2)

    @model_validator(mode="after")
    def terminal_files_match_status(self) -> ContentTeamBuildResultV2:
        materialized = (
            self.output_file,
            self.output_sha256,
            self.package_manifest_file,
            self.renderer_report_file,
        )
        if self.status == "SUCCEEDED":
            if any(value is None for value in materialized) or self.errors:
                raise ValueError("successful content-team build requires validated output")
        elif any(value is not None for value in materialized) or not self.errors:
            raise ValueError("failed content-team build cannot expose output")
        if self.completed_at < self.started_at:
            raise ValueError("content-team build completion precedes its start")
        return self


class TableData(StrictModel):
    rows: tuple[tuple[str, str, str], tuple[str, str, str]]

    @field_validator("rows")
    @classmethod
    def validate_rows(
        cls, value: tuple[tuple[str, str, str], tuple[str, str, str]]
    ) -> tuple[tuple[str, str, str], tuple[str, str, str]]:
        for row in value:
            for cell in row:
                if not cell or len(cell) > 300:
                    raise ValueError("table cell length is invalid")
                _valid_xml_text(cell)
        return value


class ImageInput(StrictModel):
    source_path: Literal["eom-placeholder-image-output.png"]
    media_type: Literal["image/png"]
    sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_width_px: Literal[800]
    expected_height_px: Literal[500]

    @field_validator("source_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise ValueError("image path must be the fixed workspace file name")
        return value


class EquationInput(StrictModel):
    source_format: Literal["hancom-equation-script"]
    source: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9+\-*/=() ._^]+$")


class StatementSet(StrictModel):
    giyeok: str = Field(min_length=1, max_length=2000)
    nieun: str = Field(min_length=1, max_length=2000)
    digeut: str = Field(min_length=1, max_length=2000)

    @field_validator("giyeok", "nieun", "digeut")
    @classmethod
    def xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class ItemInput(StrictModel):
    item_number: str = Field(pattern=r"^[1-9][0-9]{0,2}$")
    upper_stem: str = Field(min_length=1, max_length=2000)
    lower_stem: str = Field(min_length=1, max_length=2000)
    table: TableData
    image: ImageInput
    equation: EquationInput
    statements: StatementSet
    choices: tuple[str, str, str, str, str]
    points: Literal["2", "3"]

    @field_validator("upper_stem", "lower_stem")
    @classmethod
    def xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)

    @field_validator("choices")
    @classmethod
    def choices_are_xml_text(
        cls, value: tuple[str, str, str, str, str]
    ) -> tuple[str, str, str, str, str]:
        if any(not choice or len(choice) > 500 for choice in value):
            raise ValueError("choice length is invalid")
        for choice in value:
            _valid_xml_text(choice)
        return value


class SolutionInput(StrictModel):
    answer: Literal["1", "2", "3", "4", "5"]
    authoring_intent: str = Field(min_length=1, max_length=2000)
    overview: str = Field(min_length=1, max_length=2000)
    statement_explanations: StatementSet

    @field_validator("authoring_intent", "overview")
    @classmethod
    def xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class HwpxItemDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(pattern=r"^placeholder-[a-z0-9-]{1,48}$")
    document_title: str = Field(min_length=1, max_length=200)
    item: ItemInput
    solution: SolutionInput

    @field_validator("document_title")
    @classmethod
    def title_is_xml_text(cls, value: str) -> str:
        return _valid_xml_text(value)


class BuildResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PENDING_REFERENCE_TEMPLATE = "PENDING_REFERENCE_TEMPLATE"
    PENDING_MANUAL_HANCOM_VALIDATION = "PENDING_MANUAL_HANCOM_VALIDATION"


class HwpxBuildResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    template_id: str = Field(pattern=r"^hwpxtpl_[a-f0-9]{32}$")
    template_revision_id: str = Field(pattern=r"^hwpxrev_[a-f0-9]{32}$")
    input_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    renderer_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    status: BuildResultStatus
    output_file: Literal["output/placeholder_item_combined.hwpx"] | None
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    package_manifest_file: Literal["output/package-manifest.json"] | None
    validation_report_file: Literal["output/structural-validation.json"] | None
    semantic_report_file: Literal["output/semantic-validation.json"] | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime


class KordocSourcePointer(StrictModel):
    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    schema_id: Literal["eom.hwpx.markdown-document"] = "eom.hwpx.markdown-document"
    schema_version: Literal["1.0"] = "1.0"
    media_type: Literal["text/markdown; charset=utf-8"] = "text/markdown; charset=utf-8"
    sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    file: Literal["input/document.md"] = "input/document.md"


class KordocRendererDependency(StrictModel):
    package: Literal["kordoc"] = "kordoc"
    version: Literal["4.9.0"] = "4.9.0"
    npm_integrity: Literal[
        "sha512-MPgHDYjuePA1p0yei0Sx8obWdbrGYc5tzMWposRVa9P9fWZ8yW0sNVh0"
        "YjffPbmZdi7xHoQJn60iTLVG+SI2Iw=="
    ] = (
        "sha512-MPgHDYjuePA1p0yei0Sx8obWdbrGYc5tzMWposRVa9P9fWZ8yW0sNVh0"
        "YjffPbmZdi7xHoQJn60iTLVG+SI2Iw=="
    )


class KordocRenderOptions(StrictModel):
    offline: Literal[True] = True
    gongmun_preset: Literal[
        "official", "report", "plan", "notice", "minutes", "gaejosik", "press"
    ] = "report"


class KordocExpectedStructure(StrictModel):
    display_equation_count: int = Field(ge=0, le=32)
    table_count: int = Field(ge=0, le=20)


class KordocRenderRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    renderer_profile: Literal["kordoc-markdown-v1"] = "kordoc-markdown-v1"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    source: KordocSourcePointer
    renderer_dependency: KordocRendererDependency = Field(default_factory=KordocRendererDependency)
    options: KordocRenderOptions = Field(default_factory=KordocRenderOptions)
    expected_structure: KordocExpectedStructure
    output_directory: Literal["output"] = "output"


class KordocBuildResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    renderer_profile: Literal["kordoc-markdown-v1"] = "kordoc-markdown-v1"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    renderer_version: Literal["0.1.0"] = "0.1.0"
    kordoc_version: Literal["4.9.0"] = "4.9.0"
    status: Literal["FAILED", "PENDING_MANUAL_HANCOM_VALIDATION"]
    output_file: Literal["output/kordoc_document.hwpx"] | None
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    package_manifest_file: Literal["output/package-manifest.json"] | None
    validation_report_file: Literal["output/structural-validation.json"] | None
    renderer_report_file: Literal["output/kordoc-validation.json"] | None
    native_equation_count: int = Field(ge=0, le=32)
    native_table_count: int = Field(ge=0, le=20)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def status_matches_materialized_files(self) -> KordocBuildResult:
        materialized = (
            self.output_file,
            self.output_sha256,
            self.package_manifest_file,
            self.validation_report_file,
            self.renderer_report_file,
        )
        if self.status == "FAILED":
            if any(value is not None for value in materialized) or not self.errors:
                raise ValueError("failed Kordoc results cannot reference materialized output")
        elif any(value is None for value in materialized) or self.errors:
            raise ValueError("successful Kordoc results require validated materialized output")
        if self.completed_at < self.started_at:
            raise ValueError("Kordoc result completion precedes its start")
        return self


class HwpxManagerDownloadRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    operation: Literal["download"] = "download"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")


class HwpxManagerDownloadResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["OK", "ERROR"]
    filename: str | None = Field(default=None, min_length=6, max_length=150)
    content_length: int | None = Field(default=None, ge=1, le=64 * 1024 * 1024)
    sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")

    @model_validator(mode="after")
    def status_matches_header(self) -> HwpxManagerDownloadResponse:
        success = (self.filename, self.content_length, self.sha256)
        if self.status == "OK":
            if any(value is None for value in success) or self.error_code is not None:
                raise ValueError("successful download header requires immutable file evidence")
            assert self.filename is not None
            if (
                not self.filename.isascii()
                or not self.filename.endswith(".hwpx")
                or any(
                    character
                    not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
                    for character in self.filename
                )
            ):
                raise ValueError("download filename is outside the safe ASCII contract")
        elif any(value is not None for value in success) or self.error_code is None:
            raise ValueError("failed download header contains file evidence")
        return self
