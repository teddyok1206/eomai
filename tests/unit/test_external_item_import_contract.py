"""Schema and typed import manifest agree on immutable source-only identity."""

from __future__ import annotations

import copy

import pytest
from eom_catalog_contracts import (
    EXTERNAL_ITEM_COLUMNS,
    EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA,
    ExternalItemImportManifest,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError


def _manifest() -> dict[str, object]:
    mapping: dict[str, object] = {
        "schema_version": "external-item-workbook-mapping/1.0",
        "mapping_id": "extitemmap_" + "1" * 32,
        "mapping_revision_id": "extitemmaprev_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "source_namespace": "notion-integrated-science",
        "worksheet_name": "통합과학 DB",
        "header_row": 1,
        "first_data_row": 2,
        "maximum_rows": 1297,
        "column_headers": [
            {"column": column, "label": f"원본 {column}"} for column in EXTERNAL_ITEM_COLUMNS
        ],
        "external_number_column": "U",
        "edition_columns": {"draft": "L", "second": "M", "third": "N"},
        "rejection_column": "X",
        "normalization_policy": "external-item-notion-link/1.0",
        "released_at": "2026-10-27T00:00:00Z",
        "released_by": "guiadmin",
    }
    mapping["mapping_sha256"] = content_sha256(mapping)
    observation: dict[str, object] = {
        "schema_version": "external-item-row-observation/1.0",
        "workbook_artifact_id": "artifact_" + "3" * 32,
        "workbook_artifact_revision_id": "rev_" + "4" * 32,
        "workbook_sha256": "sha256:" + "5" * 64,
        "mapping_revision_id": mapping["mapping_revision_id"],
        "mapping_sha256": mapping["mapping_sha256"],
        "source_namespace": mapping["source_namespace"],
        "worksheet_name": mapping["worksheet_name"],
        "row_number": 2,
        "external_number": "00042",
        "cells": [
            {
                "column": column,
                "present": column in {"N", "U"},
                "cell_type": "s" if column in {"N", "U"} else None,
                "raw_text": (
                    "00042" if column == "U" else "문항_00042.hwp" if column == "N" else ""
                ),
                "style_id": None,
                "formula_text": None,
            }
            for column in EXTERNAL_ITEM_COLUMNS
        ],
    }
    observation["observation_sha256"] = content_sha256(observation)
    manifest: dict[str, object] = {
        "schema_version": "external-item-import-manifest/1.0",
        "source_namespace": mapping["source_namespace"],
        "actor_id": "guiadmin",
        "mapping": mapping,
        "workbook_source_file_id": "sourcefile_" + "6" * 32,
        "workbook_artifact_id": observation["workbook_artifact_id"],
        "workbook_artifact_revision_id": observation["workbook_artifact_revision_id"],
        "workbook_sha256": observation["workbook_sha256"],
        "archive_sha256": "sha256:" + "7" * 64,
        "rows": [
            {
                "observation": observation,
                "match_status": "MATCHED_DETECTED_HWPX",
                "selected_source_file_id": "sourcefile_" + "8" * 32,
                "selected_document_sha256": "sha256:" + "9" * 64,
                "edition_links": [
                    {
                        "edition": 3,
                        "match_status": "MATCHED_DETECTED_HWPX",
                        "selected_source_file_id": "sourcefile_" + "8" * 32,
                        "selected_document_sha256": "sha256:" + "9" * 64,
                    }
                ],
            }
        ],
    }
    manifest["request_sha256"] = content_sha256(manifest)
    return manifest


def test_import_manifest_is_schema_and_model_validated() -> None:
    raw = _manifest()
    validate_contract(EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA, raw)
    parsed = ExternalItemImportManifest.model_validate(raw)
    assert parsed.rows[0].observation.external_number == "00042"
    assert parsed.rows[0].selected_source_file_id == "sourcefile_" + "8" * 32


def test_import_manifest_rejects_unpinned_or_forged_row() -> None:
    raw = _manifest()
    forged = copy.deepcopy(raw)
    forged["rows"][0]["selected_source_file_id"] = None  # type: ignore[index]
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA, forged)
    forged = copy.deepcopy(raw)
    forged["rows"][0]["observation"]["external_number"] = "00043"  # type: ignore[index]
    with pytest.raises(ValueError):
        ExternalItemImportManifest.model_validate(forged)
