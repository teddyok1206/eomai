"""Read-only Studio views for legacy source records, never canonical Item revisions."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel


class ExternalItemDbEntryView(ApiModel):
    schema_version: Literal["external-item-db-entry/1.0"] = "external-item-db-entry/1.0"
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    observation_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    major_unit: str | None = Field(default=None, max_length=255)
    minor_unit: str | None = Field(default=None, max_length=255)
    field_label: str | None = Field(default=None, max_length=255)
    grade_label: str | None = Field(default=None, max_length=255)
    author_label: str | None = Field(default=None, max_length=255)
    match_status: Literal[
        "MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES",
        "REJECTED", "REJECTION_AMBIGUOUS", "DRAFT_ONLY", "LINK_UNSUPPORTED",
        "DOCUMENT_MISSING", "NAME_MISMATCH", "CONTENT_CONFLICT", "FORMAT_MISMATCH",
    ]
    selected_filename: str | None = Field(default=None, max_length=512)
    graph_state: Literal["NOT_PUBLISHED"] = "NOT_PUBLISHED"
    similarity_state: Literal["NOT_INDEXED"] = "NOT_INDEXED"


class ExternalItemDbCellView(ApiModel):
    column: str = Field(pattern=r"^(?:[A-Z]|A[A-F])$")
    present: bool
    cell_type: str | None = Field(default=None, max_length=32)
    raw_text: str = Field(max_length=32767)
    style_id: int | None = Field(default=None, ge=0)
    formula_text: str | None = Field(default=None, max_length=32767)


class ExternalItemDbEditionView(ApiModel):
    edition: int = Field(ge=1, le=3)
    match_status: str = Field(min_length=1, max_length=32)
    filename: str | None = Field(default=None, max_length=512)
    media_type: str | None = Field(default=None, max_length=127)
    available: bool


class ExternalItemDbDetailView(ApiModel):
    schema_version: Literal["external-item-db-detail/1.0"] = "external-item-db-detail/1.0"
    entry: ExternalItemDbEntryView
    worksheet_name: str = Field(min_length=1, max_length=128)
    row_number: int = Field(ge=2)
    cells: tuple[ExternalItemDbCellView, ...] = Field(min_length=32, max_length=32)
    editions: tuple[ExternalItemDbEditionView, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def ordered_source_observation(self) -> Self:
        columns = tuple(cell.column for cell in self.cells)
        expected = tuple(chr(ord("A") + index) for index in range(26)) + tuple(
            "A" + chr(ord("A") + index) for index in range(6)
        )
        if columns != expected or tuple(edition.edition for edition in self.editions) != tuple(
            sorted({edition.edition for edition in self.editions})
        ):
            raise ValueError("source columns or editions are not in canonical order")
        return self


ExternalItemDbFilterField = Literal[
    "MATCH_STATUS", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
    "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "AA", "AB", "AC", "AD", "AE", "AF",
]
ExternalItemDbFilterOperator = Literal["EQ", "NE", "CONTAINS", "IS_EMPTY", "IS_NOT_EMPTY"]


class ExternalItemDbFilterCondition(ApiModel):
    field: ExternalItemDbFilterField
    operator: ExternalItemDbFilterOperator
    value: str | None = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def applicable_value(self) -> Self:
        has_value = self.operator in ("EQ", "NE", "CONTAINS")
        if has_value != (self.value is not None):
            raise ValueError("filter operator and value disagree")
        if self.field == "MATCH_STATUS" and self.operator not in ("EQ", "NE"):
            raise ValueError("match status requires an equality operator")
        if self.field == "U" and self.operator in ("EQ", "NE") and (
            self.value is None or len(self.value) != 5 or not self.value.isascii()
            or not self.value.isdecimal()
        ):
            raise ValueError("external number equality requires five ASCII digits")
        return self


class ExternalItemDbFilterRequest(ApiModel):
    schema_version: Literal["external-item-db-filter/1.0"]
    match_mode: Literal["ALL", "ANY"]
    conditions: tuple[ExternalItemDbFilterCondition, ...] = Field(max_length=8)
    limit: int = Field(ge=1, le=100)
    cursor: str | None = Field(min_length=1, max_length=1024)
