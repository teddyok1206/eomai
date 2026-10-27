"""Released, immutable mapping for one external Item workbook family.

The mapping names source columns; it does not validate source files, grant access,
register Items, or turn a historical editorial iteration into an Item revision.
"""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

EXTERNAL_ITEM_WORKBOOK_MAPPING_SCHEMA = "external-item-workbook-mapping-v1"
EXTERNAL_ITEM_WORKBOOK_MAPPING_SCHEMA_REF = "eom://schemas/external-item/workbook-mapping/1.0"
EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA = "external-item-row-observation-v1"
EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA_REF = "eom://schemas/external-item/row-observation/1.0"
EXTERNAL_ITEM_COLUMNS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1)) + tuple(
    f"A{chr(code)}" for code in range(ord("A"), ord("F") + 1)
)


class ExternalItemColumnHeader(FrozenModel):
    column: str = Field(pattern=r"^(?:[A-Z]|A[A-F])$")
    label: str = Field(min_length=1, max_length=200)


class ExternalItemEditionColumns(FrozenModel):
    draft: Literal["L"] = "L"
    second: Literal["M"] = "M"
    third: Literal["N"] = "N"


class ExternalItemWorkbookMapping(FrozenModel):
    """Pin raw A:AF meaning and the editorial-selection inputs, not a decision."""

    schema_version: Literal["external-item-workbook-mapping/1.0"] = (
        "external-item-workbook-mapping/1.0"
    )
    mapping_id: str = Field(pattern=r"^extitemmap_[0-9a-f]{32}$")
    mapping_revision_id: str = Field(pattern=r"^extitemmaprev_[0-9a-f]{32}$")
    revision_number: int = Field(strict=True, ge=1, le=100000)
    state: Literal["RELEASED"] = "RELEASED"
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    worksheet_name: str = Field(min_length=1, max_length=128)
    header_row: int = Field(strict=True, ge=1, le=1000)
    first_data_row: int = Field(strict=True, ge=2, le=1001)
    maximum_rows: int = Field(strict=True, ge=1, le=100000)
    column_headers: tuple[ExternalItemColumnHeader, ...] = Field(min_length=32, max_length=32)
    external_number_column: Literal["U"] = "U"
    edition_columns: ExternalItemEditionColumns = ExternalItemEditionColumns()
    rejection_column: Literal["X"] = "X"
    normalization_policy: Literal["external-item-notion-link/1.0"] = "external-item-notion-link/1.0"
    mapping_sha256: Sha256
    released_at: UtcDatetime
    released_by: ActorId

    @model_validator(mode="after")
    def exact_column_meaning(self) -> ExternalItemWorkbookMapping:
        if self.first_data_row <= self.header_row:
            raise ValueError("external Item data row must follow the header")
        if tuple(value.column for value in self.column_headers) != EXTERNAL_ITEM_COLUMNS:
            raise ValueError("external Item columns must be exactly A:AF in order")
        labels = tuple(value.label for value in self.column_headers)
        if len(labels) != len(set(labels)):
            raise ValueError("external Item workbook headers must be unique")
        if any(
            any(ord(character) < 32 for character in value)
            for value in (self.worksheet_name, *labels)
        ):
            raise ValueError("external Item workbook header contains control text")
        if self.mapping_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"mapping_sha256"})
        ):
            raise ValueError("external Item mapping hash differs")
        return self


class ExternalItemCellObservation(FrozenModel):
    """Decoded cell text as written, without display/search normalization."""

    column: str = Field(pattern=r"^(?:[A-Z]|A[A-F])$")
    present: bool
    cell_type: str | None = Field(default=None, max_length=32)
    raw_text: str = Field(max_length=32767)
    style_id: int | None = Field(default=None, strict=True, ge=0, le=1000000)
    formula_text: str | None = Field(default=None, max_length=32767)

    @model_validator(mode="after")
    def missing_cell_is_empty(self) -> ExternalItemCellObservation:
        if not self.present and (
            self.cell_type is not None
            or self.raw_text
            or self.style_id is not None
            or self.formula_text is not None
        ):
            raise ValueError("missing cell cannot have content")
        return self


class ExternalItemRowObservation(FrozenModel):
    """Immutable source row, pinned to the exact workbook and mapping revisions."""

    schema_version: Literal["external-item-row-observation/1.0"] = (
        "external-item-row-observation/1.0"
    )
    workbook_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    workbook_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    workbook_sha256: Sha256
    mapping_revision_id: str = Field(pattern=r"^extitemmaprev_[0-9a-f]{32}$")
    mapping_sha256: Sha256
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    worksheet_name: str = Field(min_length=1, max_length=128)
    row_number: int = Field(strict=True, ge=2, le=1000000)
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    cells: tuple[ExternalItemCellObservation, ...] = Field(min_length=32, max_length=32)
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_row_meaning(self) -> ExternalItemRowObservation:
        if tuple(cell.column for cell in self.cells) != EXTERNAL_ITEM_COLUMNS:
            raise ValueError("external Item row must observe A:AF exactly once in order")
        if (
            sum(
                len(cell.raw_text.encode("utf-8")) + len((cell.formula_text or "").encode("utf-8"))
                for cell in self.cells
            )
            > 128 * 1024
        ):
            raise ValueError("external Item row snapshot exceeds the bounded DB value")
        number_cell = self.cells[20]
        if (
            not number_cell.present
            or number_cell.formula_text is not None
            or number_cell.raw_text != self.external_number
        ):
            raise ValueError("external Item number must be the literal U cell")
        if self.observation_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"observation_sha256"})
        ):
            raise ValueError("external Item row observation hash differs")
        return self
