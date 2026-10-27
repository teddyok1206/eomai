"""Pinned source-only import manifest; never an approved Item admission."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_workbook import (
    ExternalItemRowObservation,
    ExternalItemWorkbookMapping,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA = "external-item-import-manifest-v1"
EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA_REF = "eom://schemas/external-item/import-manifest/1.0"

type ExternalItemMatchStatusValue = Literal[
    "MATCHED",
    "MATCHED_DETECTED_HWPX",
    "MATCHED_IDENTICAL_COPIES",
    "REJECTED",
    "REJECTION_AMBIGUOUS",
    "DRAFT_ONLY",
    "LINK_UNSUPPORTED",
    "DOCUMENT_MISSING",
    "NAME_MISMATCH",
    "CONTENT_CONFLICT",
    "FORMAT_MISMATCH",
]
_MATCHED = frozenset({"MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES"})


class ExternalItemEditionLink(FrozenModel):
    edition: int = Field(strict=True, ge=1, le=3)
    match_status: Literal[
        "MATCHED",
        "MATCHED_DETECTED_HWPX",
        "MATCHED_IDENTICAL_COPIES",
        "LINK_UNSUPPORTED",
        "DOCUMENT_MISSING",
        "NAME_MISMATCH",
        "CONTENT_CONFLICT",
        "FORMAT_MISMATCH",
    ]
    selected_source_file_id: str | None = Field(default=None, pattern=r"^sourcefile_[0-9a-f]{32}$")
    selected_document_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def matched_file_is_pinned(self) -> ExternalItemEditionLink:
        has_file = self.selected_source_file_id is not None
        if has_file != (self.match_status in _MATCHED) or has_file != (
            self.selected_document_sha256 is not None
        ):
            raise ValueError("editorial link file must be pinned exactly when matched")
        return self


class ExternalItemImportRow(FrozenModel):
    observation: ExternalItemRowObservation
    match_status: ExternalItemMatchStatusValue
    selected_source_file_id: str | None = Field(default=None, pattern=r"^sourcefile_[0-9a-f]{32}$")
    selected_document_sha256: Sha256 | None = None
    edition_links: tuple[ExternalItemEditionLink, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def selected_file_is_exactly_matched(self) -> ExternalItemImportRow:
        has_file = self.selected_source_file_id is not None
        if has_file != (self.match_status in _MATCHED) or has_file != (
            self.selected_document_sha256 is not None
        ):
            raise ValueError("matched external Item must have exactly one pinned file")
        observed_editions = {
            edition
            for edition, index in ((1, 11), (2, 12), (3, 13))
            if self.observation.cells[index].raw_text
        }
        supplied_editions = tuple(link.edition for link in self.edition_links)
        if supplied_editions != tuple(sorted(observed_editions)):
            raise ValueError("editorial links must exactly match nonempty L/M/N cells")
        final_edition = (
            3
            if self.observation.cells[13].raw_text
            else 2
            if self.observation.cells[12].raw_text
            else None
        )
        if self.match_status in {"REJECTED", "REJECTION_AMBIGUOUS"}:
            return self
        if final_edition is None:
            if self.match_status != "DRAFT_ONLY":
                raise ValueError("non-final row cannot claim a final link")
            return self
        final_link = next(link for link in self.edition_links if link.edition == final_edition)
        if (
            final_link.match_status != self.match_status
            or final_link.selected_source_file_id != self.selected_source_file_id
            or final_link.selected_document_sha256 != self.selected_document_sha256
        ):
            raise ValueError("final editorial link differs from selected source")
        return self


class ExternalItemImportManifest(FrozenModel):
    schema_version: Literal["external-item-import-manifest/1.0"] = (
        "external-item-import-manifest/1.0"
    )
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    actor_id: str = Field(min_length=1, max_length=128)
    mapping: ExternalItemWorkbookMapping
    workbook_source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    workbook_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    workbook_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    workbook_sha256: Sha256
    archive_sha256: Sha256
    rows: tuple[ExternalItemImportRow, ...] = Field(min_length=1, max_length=100000)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_source_and_hash(self) -> ExternalItemImportManifest:
        if self.source_namespace != self.mapping.source_namespace:
            raise ValueError("external Item import namespace differs from mapping")
        if len(self.rows) > self.mapping.maximum_rows:
            raise ValueError("external Item import exceeds mapping row limit")
        prior_row = 0
        numbers: set[str] = set()
        for entry in self.rows:
            row = entry.observation
            if (
                row.source_namespace != self.source_namespace
                or row.worksheet_name != self.mapping.worksheet_name
                or row.mapping_revision_id != self.mapping.mapping_revision_id
                or row.mapping_sha256 != self.mapping.mapping_sha256
                or row.workbook_artifact_id != self.workbook_artifact_id
                or row.workbook_artifact_revision_id != self.workbook_artifact_revision_id
                or row.workbook_sha256 != self.workbook_sha256
                or row.row_number <= prior_row
                or row.external_number in numbers
            ):
                raise ValueError("external Item import row identity differs or repeats")
            prior_row = row.row_number
            numbers.add(row.external_number)
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("external Item import request hash differs")
        return self
