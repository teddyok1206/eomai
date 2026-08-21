"""Strict HWPX POC request and result models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

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
