"""Independent workbook import wire DTOs; Catalog owns parsing and DB resolution."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from eom_web_gui.content_planning_contracts import (
    ArtifactMember,
    Composition,
    ContentType,
    Label,
    Note,
    RevisionId,
    Sha,
    SourceTarget,
    Year,
)
from eom_web_gui.contracts import WebModel

WORKBOOK_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORKBOOK_MAX_BYTES = 8 * 1024 * 1024
WorkbookFilename = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
]
WorkbookLabel = Annotated[str, Field(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")]


class WorkbookMetadata(WebModel):
    content_title: Label
    content_type: ContentType
    edition_label: Label
    academic_year: Year | None
    print_status: Literal["PRINTED", "NOT_PRINTED", "UNKNOWN"]
    printed_on: date | None


class WorkbookRow(WebModel):
    row_number: int = Field(strict=True, ge=2, le=1048576)
    group_label: WorkbookLabel
    section_label: WorkbookLabel
    display_number: Annotated[str, Field(min_length=1, max_length=32)] | None
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    points_milli: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None
    note: Note


class WorkbookResolution(WebModel):
    row_number: int = Field(strict=True, ge=2, le=1048576)
    status: Literal["MATCHED", "MISSING", "AMBIGUOUS", "UNAVAILABLE"]
    title: Label | None
    target: SourceTarget | None


class WorkbookPreviewRow(WebModel):
    row: WorkbookRow
    resolution: WorkbookResolution


class WorkbookPreview(WebModel):
    schema_version: Literal["content-workbook-preview/1.0"]
    proposal: ArtifactMember
    original_filename: WorkbookFilename
    workbook_sha256: Sha
    metadata: WorkbookMetadata
    total_rows: int = Field(strict=True, ge=1, le=10000)
    matched_rows: int = Field(strict=True, ge=0, le=10000)
    unresolved_rows: int = Field(strict=True, ge=0, le=10000)
    duplicate_uses: int = Field(strict=True, ge=0, le=9999)
    can_commit: bool
    offset: int = Field(strict=True, ge=0, le=10000)
    rows: tuple[WorkbookPreviewRow, ...] = Field(max_length=100)
    next_offset: int | None = Field(strict=True, ge=1, le=10000)


class WorkbookQuery(WebModel):
    proposal: ArtifactMember
    offset: int = Field(default=0, strict=True, ge=0, le=10000)
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class WorkbookCommit(WebModel):
    proposal: ArtifactMember


class WorkbookImportResult(WebModel):
    schema_version: Literal["content-workbook-import-result/1.0"]
    disposition: Literal["IMPORTED", "ALREADY_IMPORTED"]
    replayed: bool
    composition: Composition
    current_revision_id: RevisionId
    print_record_id: str | None = Field(pattern=r"^print_[0-9a-f]{32}$")
