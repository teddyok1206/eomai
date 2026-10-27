"""Bind decoded archive rows to validated, pinned workbook observations."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts import (
    EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA,
    ExternalItemCellObservation,
    ExternalItemRowObservation,
    ExternalItemWorkbookMapping,
    validate_contract,
)
from eom_identifiers import content_sha256

from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow


@dataclass(frozen=True)
class ExternalItemWorkbookPointer:
    artifact_id: str
    artifact_revision_id: str
    sha256: str


@dataclass(frozen=True)
class ExternalItemSearchFacets:
    major_unit: str | None
    minor_unit: str | None
    field: str | None
    grade: str | None
    author: str | None


type ExternalCreativeOriginKind = Literal["PAST_EXAM_VARIATION", "FREE_AUTHORING"]


def external_creative_origin_kind(
    row: ExternalItemRowObservation,
) -> ExternalCreativeOriginKind | None:
    """Classify this archive from its Y cell, never its incomplete W flag."""

    return external_creative_origin_kind_from_cells(row.cells)


def external_creative_origin_kind_from_cells(
    cells: tuple[ExternalItemCellObservation, ...],
) -> ExternalCreativeOriginKind | None:
    if len(cells) != 32 or cells[24].column != "Y":
        raise ValueError("external creative classification cells are not A:AF")
    observed = unicodedata.normalize("NFC", cells[24].raw_text).strip()
    if observed == "기출변형":
        return "PAST_EXAM_VARIATION"
    if observed == "자유출제":
        return "FREE_AUTHORING"
    return None


def bind_external_item_observation(
    row: DecodedExternalItemRow,
    *,
    mapping: ExternalItemWorkbookMapping,
    workbook: ExternalItemWorkbookPointer,
) -> ExternalItemRowObservation:
    """Pin a lossless row to exact Artifact and mapping revisions."""

    if row.row_number < mapping.first_data_row:
        raise ValueError("external Item row precedes the mapped data range")
    body = {
        "schema_version": "external-item-row-observation/1.0",
        "workbook_artifact_id": workbook.artifact_id,
        "workbook_artifact_revision_id": workbook.artifact_revision_id,
        "workbook_sha256": workbook.sha256,
        "mapping_revision_id": mapping.mapping_revision_id,
        "mapping_sha256": mapping.mapping_sha256,
        "source_namespace": mapping.source_namespace,
        "worksheet_name": mapping.worksheet_name,
        "row_number": row.row_number,
        "external_number": row.external_number,
        "cells": [cell.model_dump(mode="json") for cell in row.cells],
    }
    body["observation_sha256"] = content_sha256(body)
    validate_contract(EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA, body)
    return ExternalItemRowObservation.model_validate(body)


def external_item_search_facets(row: ExternalItemRowObservation) -> ExternalItemSearchFacets:
    """Derive small index values from immutable A:AF text, never rewriting it."""

    def text_at(index: int) -> str | None:
        raw = row.cells[index].raw_text
        normalized = unicodedata.normalize("NFC", raw).strip()
        return normalized[:255] or None

    return ExternalItemSearchFacets(
        major_unit=text_at(16),  # Q
        minor_unit=text_at(17),  # R
        field=text_at(25),  # Z
        grade=text_at(14),  # O
        author=text_at(29),  # AD
    )
