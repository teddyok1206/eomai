"""Versioned workbook proposals and pinned content imports; no workbook execution."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from eom_catalog_contracts.content_planning import (
    AcademicYear,
    ContentEditionCompositionV1,
    ContentLabel,
    ContentType,
    DeliverableRevisionId,
)
from eom_catalog_contracts.curated_document_slots import DisplayNumber, ExternalSlotTarget
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

CONTENT_WORKBOOK_MAX_BYTES = 8 * 1024 * 1024
CONTENT_WORKBOOK_MAX_ROWS = 10000
CONTENT_WORKBOOK_PROPOSAL_SCHEMA = "eom://schemas/content-planning/workbook-proposal/1.0"
CONTENT_WORKBOOK_OPERATIONS = frozenset(
    {"PREPARE_CONTENT_WORKBOOK", "READ_CONTENT_WORKBOOK", "COMMIT_CONTENT_WORKBOOK"}
)
WorkbookLabel = Annotated[str, Field(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")]
WorkbookFilename = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
]
WorkbookNote = Annotated[
    str, Field(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")
]


class ContentWorkbookMetadata(FrozenModel):
    content_title: ContentLabel
    content_type: ContentType
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    print_status: Literal["PRINTED", "NOT_PRINTED", "UNKNOWN"]
    printed_on: date | None

    @field_validator("printed_on", mode="before")
    @classmethod
    def exact_date(cls, value: object) -> object:
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("print date must be an exact calendar date")
        return value

    @model_validator(mode="after")
    def coherent_metadata(self) -> Self:
        if any(value != value.strip() for value in (self.content_title, self.edition_label)):
            raise ValueError("workbook labels must be stripped")
        if self.print_status != "PRINTED" and self.printed_on is not None:
            raise ValueError("an unconfirmed print cannot have a print date")
        return self


class ContentWorkbookRow(FrozenModel):
    row_number: int = Field(strict=True, ge=2, le=1048576)
    group_label: WorkbookLabel
    section_label: WorkbookLabel
    display_number: DisplayNumber | None
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    points_milli: int | None = Field(strict=True, ge=0, le=1000000)
    note: WorkbookNote

    @model_validator(mode="after")
    def canonical_labels(self) -> Self:
        values: tuple[str, ...] = (self.group_label, self.section_label)
        if self.display_number is not None:
            values += (self.display_number,)
        if any(value != value.strip() for value in values):
            raise ValueError("workbook row labels must be stripped")
        return self


class ContentWorkbookDocument(FrozenModel):
    schema_version: Literal["content-workbook-document/1.0"] = "content-workbook-document/1.0"
    template_version: Literal["1.0"] = "1.0"
    metadata: ContentWorkbookMetadata
    rows: tuple[ContentWorkbookRow, ...] = Field(min_length=1, max_length=CONTENT_WORKBOOK_MAX_ROWS)

    @model_validator(mode="after")
    def preserve_order(self) -> Self:
        previous_row = 1
        current_group: str | None = None
        current_section: tuple[str, str] | None = None
        seen_groups: set[str] = set()
        seen_sections: set[tuple[str, str]] = set()
        for row in self.rows:
            if row.row_number <= previous_row:
                raise ValueError("workbook rows must retain their unique source order")
            group, section = row.group_label, (row.group_label, row.section_label)
            if group != current_group and group in seen_groups:
                raise ValueError("workbook groups must be contiguous")
            if section != current_section and section in seen_sections:
                raise ValueError("workbook sections must be contiguous")
            seen_groups.add(group)
            seen_sections.add(section)
            previous_row, current_group, current_section = row.row_number, group, section
        return self


class ContentWorkbookResolution(FrozenModel):
    row_number: int = Field(strict=True, ge=2, le=1048576)
    status: Literal["MATCHED", "MISSING", "AMBIGUOUS", "UNAVAILABLE"]
    title: ContentLabel | None
    target: ExternalSlotTarget | None

    @model_validator(mode="after")
    def exact_branch(self) -> Self:
        if self.status == "MATCHED":
            if self.title is None or self.target is None:
                raise ValueError("matched workbook row needs its exact target and title")
        elif self.title is not None or self.target is not None:
            raise ValueError("unresolved workbook row must not expose a target")
        return self


class ContentWorkbookProposal(FrozenModel):
    schema_version: Literal["content-workbook-proposal/1.0"] = "content-workbook-proposal/1.0"
    uploaded_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    original_filename: WorkbookFilename
    workbook_sha256: Sha256
    workbook_bytes: int = Field(strict=True, ge=8, le=CONTENT_WORKBOOK_MAX_BYTES)
    document: ContentWorkbookDocument
    resolutions: tuple[ContentWorkbookResolution, ...] = Field(
        min_length=1, max_length=CONTENT_WORKBOOK_MAX_ROWS
    )

    @model_validator(mode="after")
    def exact_rows(self) -> Self:
        if tuple(row.row_number for row in self.document.rows) != tuple(
            result.row_number for result in self.resolutions
        ):
            raise ValueError("proposal resolutions must match source rows exactly")
        return self


class ContentWorkbookPreviewRow(FrozenModel):
    row: ContentWorkbookRow
    resolution: ContentWorkbookResolution

    @model_validator(mode="after")
    def same_row(self) -> Self:
        if self.row.row_number != self.resolution.row_number:
            raise ValueError("preview row and target differ")
        return self


class ContentWorkbookPreview(FrozenModel):
    schema_version: Literal["content-workbook-preview/1.0"] = "content-workbook-preview/1.0"
    proposal: OriginArtifactMemberPointer
    original_filename: WorkbookFilename
    workbook_sha256: Sha256
    metadata: ContentWorkbookMetadata
    total_rows: int = Field(strict=True, ge=1, le=CONTENT_WORKBOOK_MAX_ROWS)
    matched_rows: int = Field(strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS)
    unresolved_rows: int = Field(strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS)
    duplicate_uses: int = Field(strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS - 1)
    can_commit: bool
    offset: int = Field(strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS)
    rows: tuple[ContentWorkbookPreviewRow, ...] = Field(max_length=100)
    next_offset: int | None = Field(strict=True, ge=1, le=CONTENT_WORKBOOK_MAX_ROWS)

    @model_validator(mode="after")
    def exact_page(self) -> Self:
        end = self.offset + len(self.rows)
        if (
            self.proposal.schema_ref != CONTENT_WORKBOOK_PROPOSAL_SCHEMA
            or self.proposal.media_type != "application/json"
            or self.matched_rows + self.unresolved_rows != self.total_rows
            or self.duplicate_uses >= self.total_rows
            or self.can_commit != (self.unresolved_rows == 0)
            or end > self.total_rows
            or (self.next_offset != (end if end < self.total_rows else None))
            or (end < self.total_rows and not self.rows)
        ):
            raise ValueError("workbook preview counts, pointer or page differ")
        return self


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime


class PrepareContentWorkbookRequest(_ApiIdentity):
    operation: Literal["PREPARE_CONTENT_WORKBOOK"] = "PREPARE_CONTENT_WORKBOOK"
    original_filename: WorkbookFilename
    content_length: int = Field(strict=True, ge=8, le=CONTENT_WORKBOOK_MAX_BYTES)
    sha256: Sha256
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")


class ReadContentWorkbookRequest(_ApiIdentity):
    operation: Literal["READ_CONTENT_WORKBOOK"] = "READ_CONTENT_WORKBOOK"
    proposal: OriginArtifactMemberPointer
    offset: int = Field(default=0, strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS)
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class CommitContentWorkbookRequest(_ApiIdentity):
    operation: Literal["COMMIT_CONTENT_WORKBOOK"] = "COMMIT_CONTENT_WORKBOOK"
    proposal: OriginArtifactMemberPointer
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")


type ContentWorkbookRequest = Annotated[
    PrepareContentWorkbookRequest | ReadContentWorkbookRequest | CommitContentWorkbookRequest,
    Field(discriminator="operation"),
]
_REQUEST: TypeAdapter[ContentWorkbookRequest] = TypeAdapter(ContentWorkbookRequest)


class ContentWorkbookImportResult(FrozenModel):
    schema_version: Literal["content-workbook-import-result/1.0"] = (
        "content-workbook-import-result/1.0"
    )
    disposition: Literal["IMPORTED", "ALREADY_IMPORTED"]
    replayed: bool
    composition: ContentEditionCompositionV1
    current_revision_id: DeliverableRevisionId
    print_record_id: str | None = Field(pattern=r"^print_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def replay_disposition(self) -> Self:
        if self.replayed != (self.disposition == "ALREADY_IMPORTED"):
            raise ValueError("workbook import replay disposition differs")
        return self


class ContentWorkbookError(FrozenModel):
    schema_version: Literal["content-workbook-error/1.0"] = "content-workbook-error/1.0"
    error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")


type ContentWorkbookReply = Annotated[
    ContentWorkbookPreview | ContentWorkbookImportResult | ContentWorkbookError,
    Field(discriminator="schema_version"),
]
_REPLY: TypeAdapter[ContentWorkbookReply] = TypeAdapter(ContentWorkbookReply)


def parse_content_workbook_request(value: dict[str, object]) -> ContentWorkbookRequest:
    validate_contract("content-workbook-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_content_workbook_reply(value: dict[str, object]) -> ContentWorkbookReply:
    validate_contract("content-workbook-reply-v1", value)
    return _REPLY.validate_python(value)


def check_content_workbook_reply(
    request: ContentWorkbookRequest, reply: ContentWorkbookReply
) -> None:
    if isinstance(reply, ContentWorkbookError):
        return
    if isinstance(request, CommitContentWorkbookRequest):
        if not isinstance(reply, ContentWorkbookImportResult):
            raise ValueError("workbook commit requires an import result")
        return
    if not isinstance(reply, ContentWorkbookPreview):
        raise ValueError("workbook preparation/read requires a preview")
    if isinstance(request, PrepareContentWorkbookRequest):
        if (
            reply.original_filename != request.original_filename
            or reply.workbook_sha256 != request.sha256
            or reply.offset != 0
        ):
            raise ValueError("workbook preparation reply differs from its upload")
    elif (
        reply.proposal != request.proposal
        or reply.offset != request.offset
        or len(reply.rows) > request.limit
    ):
        raise ValueError("workbook preview reply differs from the requested page")
