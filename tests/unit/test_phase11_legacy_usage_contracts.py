from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    AssessmentAssemblyManifestV1,
    LegacyUsageMappingContractRevision,
    LegacyUsageRowProposal,
    LegacyUsageSourcePointer,
    ProductUsageGraphProjectionV1,
    catalog_schema_inventory,
    validate_contract,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 24, 8, 30, tzinfo=UTC)
SHA = "sha256:" + "1" * 64


def _mapping() -> dict[str, object]:
    fields = (
        "source_row_key",
        "deliverable_id",
        "deliverable_revision_id",
        "assessment_form_id",
        "assessment_form_revision_id",
        "assessment_form_revision_number",
        "assessment_form_key",
        "assessment_form_ordinal",
        "assessment_form_label",
        "item_id",
        "item_revision_id",
        "item_manifest_sha256",
        "section_key",
        "section_ordinal",
        "position",
        "display_number",
        "points_milli",
        "usage_role",
        "publication_id",
        "publication_revision_id",
        "publication_revision_number",
        "publication_key",
        "publication_date",
    )
    return {
        "schema_version": "legacy-usage-mapping-contract/1.0",
        "mapping_contract_id": "legacymap_" + "1" * 32,
        "mapping_contract_revision_id": "legacymaprev_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "workbook_media_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "worksheet_name": "placements",
        "header_row": 1,
        "first_data_row": 2,
        "maximum_rows": 1000,
        "columns": {field: field for field in fields},
        "normalization_policy": "legacy-usage-normalization/1.0",
        "contract_sha256": SHA,
        "released_at": NOW.isoformat(),
        "released_by": "operator_" + "3" * 32,
    }


def _resolved_row() -> dict[str, object]:
    return {
        "schema_version": "legacy-usage-row-proposal/1.0",
        "legacy_usage_row_id": "legacyrow_" + "4" * 32,
        "legacy_usage_import_id": "legacyimport_" + "5" * 32,
        "source_row_key": "row-001",
        "source_row_number": 2,
        "normalized_row_sha256": SHA,
        "proposal_state": "RESOLVED",
        "resolved": {
            "deliverable_id": "deliverable_" + "6" * 32,
            "deliverable_revision_id": "delivrev_" + "7" * 32,
            "assessment_form_id": "form_" + "8" * 32,
            "assessment_form_revision_id": "formrev_" + "9" * 32,
            "publication_id": "publication_" + "c" * 32,
            "publication_revision_id": "publicationrev_" + "d" * 32,
            "item_id": "item_" + "a" * 32,
            "item_revision_id": "itemrev_" + "b" * 32,
            "item_manifest_sha256": SHA,
        },
        "form": {
            "form_key": "form-01",
            "revision_number": 1,
            "ordinal": 1,
            "display_label": "1회",
        },
        "placement": {
            "section_key": "main",
            "section_ordinal": 1,
            "position": 12,
            "display_number": "12",
            "points_milli": 3000,
            "usage_role": "PRIMARY",
        },
        "publication": {
            "publication_key": "2026-release",
            "revision_number": 1,
            "publication_date": "2026-08-24",
        },
        "candidate_revision_ids": [],
        "reason_codes": [],
        "review_decision": "PENDING",
        "reviewed_at": None,
        "reviewed_by": None,
    }


def test_phase11_schemas_are_canonical_packaged_and_valid() -> None:
    resources = dict(catalog_schema_inventory())
    for key in (
        "assessment-assembly-manifest",
        "legacy-usage-import-manifest",
        "legacy-usage-mapping-contract",
        "legacy-usage-row-proposal",
        "product-usage-graph-projection",
    ):
        resource = resources[key]
        canonical = ROOT / resource.canonical_path
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


def test_mapping_contract_is_schema_valid_and_rejects_duplicate_columns() -> None:
    value = _mapping()
    validate_contract("legacy-usage-mapping-contract", value)
    assert LegacyUsageMappingContractRevision.model_validate(value).first_data_row == 2
    duplicate = dict(value)
    duplicate["columns"] = dict(value["columns"]) | {"item_id": "item_revision_id"}  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="columns must be unique"):
        LegacyUsageMappingContractRevision.model_validate(duplicate)


def test_source_pointer_pins_the_workbook_schema() -> None:
    value = {
        "intake_batch_id": "intake_" + "1" * 32,
        "source_file_id": "sourcefile_" + "2" * 32,
        "artifact_id": "artifact_" + "3" * 32,
        "artifact_revision_id": "rev_" + "4" * 32,
        "member_path": "source/usage.xlsx",
        "schema_ref": "eom://schemas/legacy-usage/workbook/1.0",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "sha256": SHA,
    }
    assert LegacyUsageSourcePointer.model_validate(value).schema_ref.endswith("/1.0")
    with pytest.raises(ValueError):
        LegacyUsageSourcePointer.model_validate(value | {"schema_ref": "unknown"})


def test_row_proposal_fails_closed_without_exact_resolved_pointers() -> None:
    value = _resolved_row()
    validate_contract("legacy-usage-row-proposal", value)
    assert LegacyUsageRowProposal.model_validate(value).proposal_state == "RESOLVED"
    with pytest.raises(ValueError, match="only resolved rows"):
        LegacyUsageRowProposal.model_validate(value | {"proposal_state": "CONFLICT"})
    with pytest.raises(ValueError, match="only resolved rows can be approved"):
        LegacyUsageRowProposal.model_validate(
            value
            | {
                "proposal_state": "UNRESOLVED",
                "resolved": None,
                "form": None,
                "placement": None,
                "publication": None,
                "reason_codes": ["POINTER_NOT_FOUND"],
                "review_decision": "APPROVE",
                "reviewed_at": NOW,
                "reviewed_by": "operator_" + "3" * 32,
            }
        )


def test_assembly_rejects_duplicate_positions_and_wrong_points() -> None:
    placement = {
        "placement_id": "placement_" + "1" * 32,
        "section_key": "main",
        "section_ordinal": 1,
        "position": 1,
        "display_number": "1",
        "item_id": "item_" + "2" * 32,
        "item_revision_id": "itemrev_" + "3" * 32,
        "item_manifest_sha256": SHA,
        "points_milli": 2000,
        "usage_role": "PRIMARY",
        "source_usage_plan_id": None,
    }
    value = {
        "schema_version": "assessment-assembly-manifest/1.0",
        "assessment_assembly_revision_id": "assemblyrev_" + "4" * 32,
        "assessment_assembly_id": "assembly_" + "5" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "assessment_form_id": "form_" + "6" * 32,
        "placements": [placement],
        "total_points_milli": 2000,
        "revision_state": "RELEASED",
        "manifest_sha256": SHA,
        "created_at": NOW.isoformat(),
        "created_by": "operator_" + "7" * 32,
    }
    validate_contract("assessment-assembly-manifest", value)
    assert AssessmentAssemblyManifestV1.model_validate(value).total_points_milli == 2000
    with pytest.raises(ValueError, match="total points"):
        AssessmentAssemblyManifestV1.model_validate(value | {"total_points_milli": 1999})
    duplicate = dict(placement) | {"placement_id": "placement_" + "8" * 32}
    with pytest.raises(ValueError, match="duplicate section position"):
        AssessmentAssemblyManifestV1.model_validate(
            value | {"placements": [placement, duplicate], "total_points_milli": 4000}
        )


def test_product_usage_projection_rejects_dangling_edges() -> None:
    value = {
        "schema_version": "product-usage-graph-projection/1.0",
        "nodes": [
            {
                "node_id": "pnode_" + "1" * 32,
                "node_type": "ITEM_REVISION",
                "logical_id": "item_" + "2" * 32,
                "revision_id": "itemrev_" + "3" * 32,
                "source_sha256": SHA,
            }
        ],
        "edges": [
            {
                "edge_id": "pedge_" + "4" * 32,
                "edge_type": "USAGE_RECORDS_ITEM",
                "from_node_id": "pnode_" + "5" * 32,
                "to_node_id": "pnode_" + "1" * 32,
                "source_record_id": "usagerecord_" + "6" * 32,
                "source_sha256": SHA,
            }
        ],
        "projection_sha256": SHA,
        "created_at": NOW.isoformat(),
    }
    validate_contract("product-usage-graph-projection", value)
    with pytest.raises(ValueError, match="dangling edge"):
        ProductUsageGraphProjectionV1.model_validate(value)
