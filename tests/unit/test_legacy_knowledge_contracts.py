from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    CATALOG_SCHEMA_RESOURCES,
    LegacyKnowledgeContractErrorCode,
    LegacySourceInventory,
    LegacySourceRelationManifest,
    LegacySourceRightsReview,
    LegacySourceSelection,
    PdfPageRangeMaterializationManifest,
    catalog_schema_inventory,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, ValidationError
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parents[2]
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
NOW = "2026-08-24T15:30:00Z"


def _self_hash(value: dict[str, object], field: str) -> dict[str, object]:
    result = deepcopy(value)
    result[field] = content_sha256({key: item for key, item in result.items() if key != field})
    return result


def _artifact_pointer(
    suffix: str,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str,
    sha256: str = SHA_A,
) -> dict[str, object]:
    return {
        "pointer_type": "ARTIFACT_MEMBER",
        "artifact_id": "artifact_" + suffix * 32,
        "artifact_revision_id": "rev_" + suffix * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": sha256,
    }


def _inventory() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-source-inventory/1.0",
        "inventory_id": "legacyinventory_" + "1" * 32,
        "observed_at": NOW,
        "scanner_version": "1.0.0",
        "scanner_policy_revision_id": "legacyinventorypolicyrev_" + "2" * 32,
        "scanner_policy_sha256": SHA_A,
        "root_alias": "EOMIS_LEGACY_SOURCE",
        "root_configuration_sha256": SHA_B,
        "entries": [
            {
                "entry_key": "legacyentry_" + "1" * 32,
                "relative_path": "corpus/textbook.pdf",
                "file_observation": "REGULAR",
                "size_bytes": 1000,
                "media_type": "application/pdf",
                "content_sha256": SHA_A,
                "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
                "source_family": "TEXTBOOK",
                "canonicality": "ORIGINAL",
                "rights_state": "UNREVIEWED",
                "relation_group_key": "textbook-01",
                "exclusion_reasons": [],
            },
            {
                "entry_key": "legacyentry_" + "2" * 32,
                "relative_path": "derived/textbook.json",
                "file_observation": "REGULAR",
                "size_bytes": 50,
                "media_type": "application/json",
                "content_sha256": SHA_B,
                "preliminary_class": "DERIVED_MIGRATION_EVIDENCE",
                "source_family": "DERIVED_EVIDENCE",
                "canonicality": "DERIVED",
                "rights_state": "UNREVIEWED",
                "relation_group_key": "textbook-01",
                "exclusion_reasons": [],
            },
            {
                "entry_key": "legacyentry_" + "3" * 32,
                "relative_path": "runtime/.env",
                "file_observation": "REGULAR",
                "size_bytes": 20,
                "media_type": None,
                "content_sha256": None,
                "preliminary_class": "EXCLUDED_RUNTIME_STATE",
                "source_family": "EXCLUDED",
                "canonicality": "UNKNOWN",
                "rights_state": "UNREVIEWED",
                "relation_group_key": None,
                "exclusion_reasons": ["SECRET_OR_CREDENTIAL"],
            },
        ],
        "summary": {
            "original_source_candidates": {"file_count": 1, "byte_count": 1000},
            "derived_migration_evidence": {"file_count": 1, "byte_count": 50},
            "excluded_runtime_state": {"file_count": 1, "byte_count": 20},
            "total_file_count": 3,
            "total_byte_count": 1070,
        },
        "inventory_sha256": SHA_C,
    }
    return _self_hash(value, "inventory_sha256")


def _selection() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-source-selection/1.0",
        "selection_id": "legacyselection_" + "4" * 32,
        "inventory_id": "legacyinventory_" + "1" * 32,
        "inventory_sha256": _inventory()["inventory_sha256"],
        "selected_sources": [
            {
                "entry_key": "legacyentry_" + "1" * 32,
                "content_sha256": SHA_A,
                "canonicality": "ORIGINAL",
                "reviewed_source_family": "TEXTBOOK",
                "declared_intake_role": "REFERENCE",
                "intended_corpus_key": "integrated-science.textbook.restricted",
                "source_owner_reference": "organization_eom",
                "rights_state": "RESTRICTED",
                "rights_review": _artifact_pointer(
                    "4",
                    member_path="rights/review.json",
                    schema_ref="eom://schemas/legacy-knowledge/rights-review/1.0",
                    media_type="application/json",
                    sha256=SHA_C,
                ),
            }
        ],
        "comparison_evidence": [
            {
                "entry_key": "legacyentry_" + "2" * 32,
                "content_sha256": SHA_B,
                "canonicality": "DERIVED",
            }
        ],
        "reviewed_at": NOW,
        "reviewed_by": "operator_" + "5" * 32,
        "selection_sha256": SHA_C,
    }
    return _self_hash(value, "selection_sha256")


def _rights_review() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-source-rights-review/1.0",
        "rights_review_id": "rightsreview_" + "4" * 32,
        "rights_review_revision_id": "rightsreviewrev_" + "5" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source_owner_reference": "organization_eom",
        "document_type": "TEXTBOOK",
        "rights_state": "RESTRICTED",
        "allowed_internal_processing": True,
        "allowed_model_exposure": True,
        "allowed_roles": ["ADMIN", "DATA_ANALYST_WORKER", "RIGHTS_REVIEWER"],
        "allowed_excerpt_materialization": True,
        "allowed_page_image_materialization": True,
        "allowed_item_grounding": False,
        "answer_bearing": False,
        "retention_policy_key": "legacy-source.restricted-pilot",
        "withdrawal_behavior": "RETIRE_FROM_NEW_RETRIEVAL",
        "evidence": [
            _artifact_pointer(
                "5",
                member_path="rights/source-evidence.json",
                schema_ref="eom://schemas/legacy-knowledge/rights-evidence/1.0",
                media_type="application/json",
                sha256=SHA_B,
            )
        ],
        "reviewed_at": NOW,
        "reviewed_by": "operator_" + "5" * 32,
        "rights_review_sha256": SHA_C,
    }
    return _self_hash(value, "rights_review_sha256")


def _relation_manifest() -> dict[str, object]:
    inventory = _inventory()
    value: dict[str, object] = {
        "schema_version": "legacy-source-relation-manifest/1.0",
        "relation_manifest_id": "legacyrelationmanifest_" + "6" * 32,
        "inventory_id": inventory["inventory_id"],
        "inventory_sha256": inventory["inventory_sha256"],
        "relations": [
            {
                "relation_id": "legacyrelation_" + "7" * 32,
                "relation_kind": "DERIVED_FROM",
                "original": {
                    "pointer_type": "INVENTORY_ENTRY",
                    "inventory_id": inventory["inventory_id"],
                    "inventory_sha256": inventory["inventory_sha256"],
                    "entry_key": "legacyentry_" + "1" * 32,
                    "content_sha256": SHA_A,
                },
                "derived": {
                    "pointer_type": "INVENTORY_ENTRY",
                    "inventory_id": inventory["inventory_id"],
                    "inventory_sha256": inventory["inventory_sha256"],
                    "entry_key": "legacyentry_" + "2" * 32,
                    "content_sha256": SHA_B,
                },
                "transformation": {
                    "implementation": "legacy-codex-analysis",
                    "version": "unknown-reviewed",
                    "options_sha256": SHA_C,
                },
                "source_page_range": None,
                "confidence_milli": 700,
                "review_state": "CONFIRMED",
            }
        ],
        "reviewed_at": NOW,
        "reviewed_by": "operator_" + "5" * 32,
        "manifest_sha256": SHA_C,
    }
    return _self_hash(value, "manifest_sha256")


def _pdf_manifest() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "pdf-page-range-materialization-manifest/1.0",
        "materialization_id": "pdfmaterialization_" + "8" * 32,
        "original": _artifact_pointer(
            "8",
            member_path="source/textbook.pdf",
            schema_ref="eom://schemas/legacy-knowledge/original-pdf/1.0",
            media_type="application/pdf",
            sha256=SHA_A,
        ),
        "original_size_bytes": 150 * 1024 * 1024,
        "source_page_count": 100,
        "renderer_implementation": "eom-pdf-page-range",
        "renderer_version": "1.0.0",
        "rendering_options_sha256": SHA_B,
        "page_ranges": [
            {
                "first_page": 1,
                "last_page": 50,
                "child": _artifact_pointer(
                    "9",
                    member_path="derived/pages-000001-000050.pdf",
                    schema_ref="eom://schemas/legacy-knowledge/pdf-page-range/1.0",
                    media_type="application/pdf",
                    sha256=SHA_B,
                ),
                "size_bytes": 75 * 1024 * 1024,
            },
            {
                "first_page": 51,
                "last_page": 100,
                "child": _artifact_pointer(
                    "a",
                    member_path="derived/pages-000051-000100.pdf",
                    schema_ref="eom://schemas/legacy-knowledge/pdf-page-range/1.0",
                    media_type="application/pdf",
                    sha256=SHA_C,
                ),
                "size_bytes": 75 * 1024 * 1024,
            },
        ],
        "created_at": NOW,
        "created_by": "operator_" + "5" * 32,
        "manifest_sha256": SHA_C,
    }
    return _self_hash(value, "manifest_sha256")


def test_legacy_knowledge_schemas_are_canonical_packaged_and_valid() -> None:
    inventory = dict(catalog_schema_inventory())
    for key in (
        "legacy-source-inventory",
        "legacy-source-relation-manifest",
        "legacy-source-rights-review",
        "legacy-source-rights-review-v2",
        "legacy-source-selection",
        "legacy-source-selection-v2",
        "pdf-page-range-materialization-manifest",
    ):
        resource = inventory[key]
        canonical = ROOT / resource.canonical_path
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


def test_historical_knowledge_contract_hashes_remain_pinned() -> None:
    expected = {
        "legacy-source-rights-review": (
            "sha256:0ab0b051ca3bb4830fbc0d8c35af38bd809e617e6edc3e270e8103e23487c7c7"
        ),
        "legacy-source-selection": (
            "sha256:89acd96ec4f08ec7aa11da34370db02666fdccb289e0574b5c21065f43940111"
        ),
        "legacy-source-rights-review-v2": (
            "sha256:de8a98565ffb8b6d326cd716ff8245778a0ea11702838bf6dd5475b7fecef3f5"
        ),
        "legacy-source-selection-v2": (
            "sha256:0c25bfa3c8732f85306b7077199e0f222aab65203c468a8ecb813f6092407775"
        ),
        "knowledge-analysis-request-v2": (
            "sha256:bf77196f281dc8c2c22e850e576a9137acb7bc1fea3681400f8855dc1f63414f"
        ),
        "knowledge-analysis-result-v2": (
            "sha256:e017752dc52ca32cb18d5e671525d1415c76ce19df023ac33fd3a43e811c3d48"
        ),
        "knowledge-graph-snapshot-manifest-v2": (
            "sha256:2fe24ad351ca7dcd10a9ba7909bf0fe0fe6fb2bf7715ca3dac02d1697cf60d09"
        ),
        "evidence-bundle-manifest-v2": (
            "sha256:a908f3dffd665292e5b171d799e8e1e95faa0ed5a4df3cfdc426c8f4f4bfcdaa"
        ),
    }
    assert {key: CATALOG_SCHEMA_RESOURCES[key].sha256 for key in expected} == expected


def test_inventory_is_schema_valid_typed_frozen_and_canonically_hashed() -> None:
    value = _inventory()
    validate_contract("legacy-source-inventory", value)
    parsed = LegacySourceInventory.model_validate(value)
    assert parsed.inventory_sha256 == content_sha256(
        parsed.model_dump(mode="json", exclude={"inventory_sha256"})
    )
    with pytest.raises(PydanticValidationError, match="frozen"):
        parsed.root_alias = "EOM_AI_SERVER_LEGACY_SOURCE"  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("entries", 0, "canonicality", "DERIVED"), "classification is inconsistent"),
        (("entries", 0, "media_type", "application/json"), "originals must be PDF"),
        (("entries", 0, "relative_path", "../textbook.pdf"), "safe and relative"),
        (("entries", 1, "source_family", "TEXTBOOK"), "classification is inconsistent"),
        (("entries", 2, "exclusion_reasons", []), "classification is inconsistent"),
    ],
)
def test_inventory_rejects_invalid_path_and_classification(
    mutation: tuple[str, int, str, object], message: str
) -> None:
    value = _inventory()
    _, index, key, replacement = mutation
    entries = value["entries"]
    assert isinstance(entries, list)
    entry = entries[index]
    assert isinstance(entry, dict)
    entry[key] = replacement
    value = _self_hash(value, "inventory_sha256")
    with pytest.raises(PydanticValidationError, match=message):
        LegacySourceInventory.model_validate(value)


def test_inventory_rejects_path_collisions_summary_drift_and_hash_drift() -> None:
    collision = _inventory()
    entries = collision["entries"]
    assert isinstance(entries, list)
    entry = deepcopy(entries[0])
    assert isinstance(entry, dict)
    entry["entry_key"] = "legacyentry_" + "4" * 32
    entry["relative_path"] = "CORPUS/TEXTBOOK.PDF"
    entries.insert(0, entry)
    collision = _self_hash(collision, "inventory_sha256")
    with pytest.raises(PydanticValidationError, match="path collisions"):
        LegacySourceInventory.model_validate(collision)

    summary_drift = _inventory()
    summary = summary_drift["summary"]
    assert isinstance(summary, dict)
    summary["total_byte_count"] = 1071
    summary_drift = _self_hash(summary_drift, "inventory_sha256")
    with pytest.raises(PydanticValidationError, match="total summary"):
        LegacySourceInventory.model_validate(summary_drift)

    with pytest.raises(PydanticValidationError, match="inventory_sha256"):
        LegacySourceInventory.model_validate(_inventory() | {"inventory_sha256": SHA_A})


def test_inventory_schema_rejects_non_pdf_textbook_original() -> None:
    value = _inventory()
    entries = value["entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0]["media_type"] = "application/json"
    value = _self_hash(value, "inventory_sha256")
    with pytest.raises(ValidationError):
        validate_contract("legacy-source-inventory", value)


def test_selection_accepts_originals_and_keeps_derived_values_comparison_only() -> None:
    value = _selection()
    validate_contract("legacy-source-selection", value)
    assert (
        LegacySourceSelection.model_validate(value).selected_sources[0].canonicality == "ORIGINAL"
    )

    wrong_class = deepcopy(value)
    selected = wrong_class["selected_sources"]
    assert isinstance(selected, list) and isinstance(selected[0], dict)
    selected[0]["canonicality"] = "DERIVED"
    wrong_class = _self_hash(wrong_class, "selection_sha256")
    with pytest.raises(ValidationError):
        validate_contract("legacy-source-selection", wrong_class)

    overlap = deepcopy(value)
    evidence = overlap["comparison_evidence"]
    assert isinstance(evidence, list) and isinstance(evidence[0], dict)
    evidence[0]["entry_key"] = "legacyentry_" + "1" * 32
    overlap = _self_hash(overlap, "selection_sha256")
    with pytest.raises(PydanticValidationError, match="cannot overlap"):
        LegacySourceSelection.model_validate(overlap)


def test_source_rights_review_is_pinned_and_fails_closed() -> None:
    value = _rights_review()
    validate_contract("legacy-source-rights-review", value)
    parsed = LegacySourceRightsReview.model_validate(value)
    assert parsed.rights_review_sha256 == content_sha256(
        parsed.model_dump(mode="json", exclude={"rights_review_sha256"})
    )

    missing_worker_role = deepcopy(value)
    missing_worker_role["allowed_roles"] = ["ADMIN", "RIGHTS_REVIEWER"]
    missing_worker_role = _self_hash(missing_worker_role, "rights_review_sha256")
    with pytest.raises(PydanticValidationError, match="model exposure"):
        LegacySourceRightsReview.model_validate(missing_worker_role)

    rejected_with_access = deepcopy(value)
    rejected_with_access["rights_state"] = "REJECTED"
    rejected_with_access = _self_hash(rejected_with_access, "rights_review_sha256")
    with pytest.raises(ValidationError):
        validate_contract("legacy-source-rights-review", rejected_with_access)


def test_relation_manifest_rejects_self_reference_and_invalid_rendered_page() -> None:
    value = _relation_manifest()
    validate_contract("legacy-source-relation-manifest", value)
    assert (
        LegacySourceRelationManifest.model_validate(value).relations[0].review_state == "CONFIRMED"
    )

    self_reference = deepcopy(value)
    relations = self_reference["relations"]
    assert isinstance(relations, list) and isinstance(relations[0], dict)
    relations[0]["derived"] = deepcopy(relations[0]["original"])
    self_reference = _self_hash(self_reference, "manifest_sha256")
    with pytest.raises(PydanticValidationError, match="cannot point to itself"):
        LegacySourceRelationManifest.model_validate(self_reference)

    rendered = deepcopy(value)
    relations = rendered["relations"]
    assert isinstance(relations, list) and isinstance(relations[0], dict)
    relations[0]["relation_kind"] = "RENDERS_PAGE_FROM"
    relations[0]["source_page_range"] = {"first_page": 1, "last_page": 2}
    rendered = _self_hash(rendered, "manifest_sha256")
    with pytest.raises(PydanticValidationError, match="exactly one source page"):
        LegacySourceRelationManifest.model_validate(rendered)


def test_pdf_page_ranges_require_complete_bounded_nonoverlapping_coverage() -> None:
    value = _pdf_manifest()
    validate_contract("pdf-page-range-materialization-manifest", value)
    parsed = PdfPageRangeMaterializationManifest.model_validate(value)
    assert parsed.original_size_bytes > 100 * 1024 * 1024
    assert all(page_range.size_bytes <= 100 * 1024 * 1024 for page_range in parsed.page_ranges)

    gap = deepcopy(value)
    ranges = gap["page_ranges"]
    assert isinstance(ranges, list) and isinstance(ranges[1], dict)
    ranges[1]["first_page"] = 52
    gap = _self_hash(gap, "manifest_sha256")
    with pytest.raises(PydanticValidationError, match="contiguous and ordered"):
        PdfPageRangeMaterializationManifest.model_validate(gap)

    too_large = deepcopy(value)
    ranges = too_large["page_ranges"]
    assert isinstance(ranges, list) and isinstance(ranges[0], dict)
    ranges[0]["size_bytes"] = 100 * 1024 * 1024 + 1
    too_large = _self_hash(too_large, "manifest_sha256")
    with pytest.raises(ValidationError):
        validate_contract("pdf-page-range-materialization-manifest", too_large)


def test_stable_legacy_knowledge_error_codes_are_closed() -> None:
    assert tuple(code.value for code in LegacyKnowledgeContractErrorCode) == (
        "LEGACY_KNOWLEDGE_CONTRACT_INVALID",
        "LEGACY_KNOWLEDGE_UNSAFE_PATH",
        "LEGACY_KNOWLEDGE_HASH_MISMATCH",
        "LEGACY_KNOWLEDGE_DUPLICATE_ENTRY",
        "LEGACY_KNOWLEDGE_INVENTORY_STALE",
        "LEGACY_KNOWLEDGE_POINTER_STALE",
        "LEGACY_KNOWLEDGE_CLASS_INVALID",
        "LEGACY_KNOWLEDGE_RIGHTS_INVALID",
        "LEGACY_KNOWLEDGE_RELATION_INVALID",
        "LEGACY_KNOWLEDGE_PAGE_RANGE_INVALID",
        "LEGACY_KNOWLEDGE_CONFIGURATION_INVALID",
        "LEGACY_KNOWLEDGE_POLICY_INVALID",
        "LEGACY_KNOWLEDGE_ROOT_INVALID",
        "LEGACY_KNOWLEDGE_CAPACITY_EXCEEDED",
        "LEGACY_KNOWLEDGE_ROOT_CHANGED",
        "LEGACY_KNOWLEDGE_FILE_CHANGED",
        "LEGACY_KNOWLEDGE_MEDIA_INVALID",
        "LEGACY_KNOWLEDGE_OUTPUT_INVALID",
    )
