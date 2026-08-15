"""Strict HWPX POC request and result models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
