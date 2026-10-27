"""The external archive mapping preserves the original A:AF column meaning."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    EXTERNAL_ITEM_COLUMNS,
    EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA,
    EXTERNAL_ITEM_WORKBOOK_MAPPING_SCHEMA,
    ExternalItemRowObservation,
    ExternalItemWorkbookMapping,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError


def _mapping() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "external-item-workbook-mapping/1.0",
        "mapping_id": "extitemmap_" + "1" * 32,
        "mapping_revision_id": "extitemmaprev_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "source_namespace": "notion-integrated-science",
        "worksheet_name": "통합과학 DB",
        "header_row": 1,
        "first_data_row": 2,
        "maximum_rows": 100000,
        "column_headers": [
            {"column": column, "label": f"source {column}"} for column in EXTERNAL_ITEM_COLUMNS
        ],
        "external_number_column": "U",
        "edition_columns": {"draft": "L", "second": "M", "third": "N"},
        "rejection_column": "X",
        "normalization_policy": "external-item-notion-link/1.0",
        "released_at": "2026-10-27T00:00:00Z",
        "released_by": "guiadmin",
    }
    body["mapping_sha256"] = content_sha256(body)
    return body


def test_external_item_mapping_has_exact_ordered_columns_and_schema() -> None:
    body = _mapping()
    validate_contract(EXTERNAL_ITEM_WORKBOOK_MAPPING_SCHEMA, body)
    actual = ExternalItemWorkbookMapping.model_validate(body)
    assert actual.column_headers[20].column == "U"
    assert actual.edition_columns.third == "N"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(revision_number=True),
        lambda body: body.update(first_data_row=1),
        lambda body: body.update(external_number_column="V"),
        lambda body: body["column_headers"].__setitem__(20, {"column": "T", "label": "source U"}),
        lambda body: body["column_headers"].__setitem__(20, {"column": "U", "label": "source T"}),
        lambda body: body.update(mapping_sha256="sha256:" + "0" * 64),
    ],
)
def test_external_item_mapping_rejects_changed_meaning(mutate) -> None:
    body = deepcopy(_mapping())
    mutate(body)
    with pytest.raises(ValidationError):
        ExternalItemWorkbookMapping.model_validate(body)


def test_external_item_mapping_schema_rejects_unpinned_fields() -> None:
    body = _mapping()
    body["extra"] = "unreviewed"
    with pytest.raises(SchemaValidationError):
        validate_contract(EXTERNAL_ITEM_WORKBOOK_MAPPING_SCHEMA, body)


def test_external_item_mapping_is_immutable() -> None:
    actual = ExternalItemWorkbookMapping.model_validate(_mapping())
    with pytest.raises(ValidationError):
        actual.source_namespace = "other"  # type: ignore[misc]


def _row_observation() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "external-item-row-observation/1.0",
        "workbook_artifact_id": "artifact_" + "1" * 32,
        "workbook_artifact_revision_id": "rev_" + "2" * 32,
        "workbook_sha256": "sha256:" + "3" * 64,
        "mapping_revision_id": "extitemmaprev_" + "4" * 32,
        "mapping_sha256": "sha256:" + "5" * 64,
        "source_namespace": "notion-integrated-science",
        "worksheet_name": "통합과학 DB",
        "row_number": 2,
        "external_number": "00042",
        "cells": [
            {
                "column": column,
                "present": column == "U",
                "cell_type": "s" if column == "U" else None,
                "raw_text": "00042" if column == "U" else "",
                "style_id": 0 if column == "U" else None,
                "formula_text": None,
            }
            for column in EXTERNAL_ITEM_COLUMNS
        ],
    }
    body["observation_sha256"] = content_sha256(body)
    return body


def test_row_observation_preserves_exact_cells_and_pointer() -> None:
    body = _row_observation()
    validate_contract(EXTERNAL_ITEM_ROW_OBSERVATION_SCHEMA, body)
    actual = ExternalItemRowObservation.model_validate(body)
    assert actual.external_number == "00042"
    assert actual.cells[20].raw_text == "00042"


@pytest.mark.parametrize("changed", ["cell_order", "number_formula", "number_mismatch", "hash"])
def test_row_observation_rejects_ambiguous_identity(changed: str) -> None:
    body = deepcopy(_row_observation())
    cells = body["cells"]
    assert isinstance(cells, list)
    if changed == "cell_order":
        cells[0], cells[1] = cells[1], cells[0]
    elif changed == "number_formula":
        cells[20]["formula_text"] = 'TEXT(42,"00000")'
    elif changed == "number_mismatch":
        body["external_number"] = "00043"
    else:
        body["observation_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        ExternalItemRowObservation.model_validate(body)


def test_row_observation_rejects_large_database_snapshot() -> None:
    body = _row_observation()
    cells = body["cells"]
    assert isinstance(cells, list)
    for cell in cells[:5]:
        cell.update(present=True, cell_type="s", raw_text="한" * 32767)
    body["observation_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "observation_sha256"}
    )
    with pytest.raises(ValidationError):
        ExternalItemRowObservation.model_validate(body)
