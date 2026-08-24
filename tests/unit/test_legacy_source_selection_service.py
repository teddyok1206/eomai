from __future__ import annotations

import copy
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import (
    LegacyKnowledgeContractErrorCode,
    LegacyRootAlias,
    LegacySourceInventoryPolicy,
    LegacySourceRightsReviewV2,
    LegacySourceSelectionV2,
    validate_contract,
)
from eom_catalog_service.intake_service import IntakeSourceDeclaration
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryScanner,
    LegacySourceRootConfiguration,
)
from eom_catalog_service.legacy_source_selection_boundary import (
    LegacyContentIntakeReceipt,
    LegacySelectionArtifactReceipt,
    LegacySourceSelectionError,
)
from eom_catalog_service.legacy_source_selection_service import (
    LegacySourceSelectionService,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eomctl.cli import app
from jsonschema import ValidationError as JsonSchemaValidationError
from typer.testing import CliRunner

REVIEWED_AT = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)


def _self_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = content_sha256({key: item for key, item in value.items() if key != field})
    return value


def _policy() -> LegacySourceInventoryPolicy:
    exclusions = [
        {"match_kind": "BASENAME", "value": ".env", "reason": "SECRET_OR_CREDENTIAL"},
        {
            "match_kind": "PATH_SEGMENT",
            "value": ".git",
            "reason": "VERSION_CONTROL_METADATA",
        },
        {"match_kind": "SUFFIX", "value": ".ckpt", "reason": "MODEL_OR_CHECKPOINT"},
        {"match_kind": "SUFFIX", "value": ".key", "reason": "SECRET_OR_CREDENTIAL"},
        {"match_kind": "SUFFIX", "value": ".lock", "reason": "CACHE_TEMP_OR_LOCK"},
        {"match_kind": "SUFFIX", "value": ".pem", "reason": "SECRET_OR_CREDENTIAL"},
        {
            "match_kind": "SUFFIX",
            "value": ".safetensors",
            "reason": "MODEL_OR_CHECKPOINT",
        },
        {
            "match_kind": "SUFFIX",
            "value": ".sqlite",
            "reason": "RUNTIME_DATABASE_OR_INDEX",
        },
        {
            "match_kind": "SUFFIX",
            "value": ".sqlite-shm",
            "reason": "RUNTIME_DATABASE_OR_INDEX",
        },
        {
            "match_kind": "SUFFIX",
            "value": ".sqlite-wal",
            "reason": "RUNTIME_DATABASE_OR_INDEX",
        },
    ]
    value: dict[str, Any] = {
        "schema_version": "legacy-source-inventory-policy/1.0",
        "policy_revision_id": "legacyinventorypolicyrev_" + "1" * 32,
        "scanner_version": "1.0.0",
        "limits": {
            "max_observations": 100,
            "max_candidate_bytes": 100 * 1024 * 1024,
            "max_file_bytes": 100 * 1024 * 1024,
            "max_depth": 8,
            "max_path_length": 500,
            "signature_scan_bytes": 64 * 1024,
        },
        "classification_rules": [
            {
                "rule_id": "legacyinventoryrule_" + "2" * 32,
                "root_alias": "EOMIS_LEGACY_SOURCE",
                "relative_prefix": "legacy/derived",
                "preliminary_class": "DERIVED_MIGRATION_EVIDENCE",
                "source_family": "DERIVED_EVIDENCE",
                "allowed_suffixes": [".json"],
            },
            {
                "rule_id": "legacyinventoryrule_" + "3" * 32,
                "root_alias": "EOMIS_LEGACY_SOURCE",
                "relative_prefix": "legacy/originals",
                "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
                "source_family": "CURRICULUM",
                "allowed_suffixes": [".pdf"],
            },
        ],
        "exclusion_rules": sorted(
            exclusions,
            key=lambda item: (item["match_kind"], item["value"], item["reason"]),
        ),
        "policy_sha256": "sha256:" + "0" * 64,
    }
    return LegacySourceInventoryPolicy.model_validate(_self_hash(value, "policy_sha256"))


def _roots(root: Path) -> LegacySourceRootConfiguration:
    return LegacySourceRootConfiguration.model_validate(
        {
            "schema_version": "legacy-source-root-configuration/1.0",
            "configuration_revision_id": "legacyrootconfigrev_" + "4" * 32,
            "roots": [
                {
                    "root_alias": "EOMIS_LEGACY_SOURCE",
                    "configuration_identity": "legacyroot_" + "5" * 32,
                    "absolute_path": str(root),
                }
            ],
        }
    )


def _inventory(root: Path):
    return LegacySourceInventoryScanner().scan(
        policy=_policy(),
        roots=_roots(root),
        root_alias=LegacyRootAlias.EOMIS_LEGACY_SOURCE,
        observed_at=REVIEWED_AT,
    )


def _fixture(root: Path) -> tuple[Path, Path]:
    originals = root / "legacy" / "originals"
    derived = root / "legacy" / "derived"
    originals.mkdir(parents=True)
    derived.mkdir(parents=True)
    original = originals / "[별책9] 과학과 교육과정.pdf"
    original.write_bytes(b"%PDF-1.7\nsynthetic integrated science\n%%EOF\n")
    comparison = derived / "curriculum-sections.json"
    comparison.write_text('{"synthetic":true}\n', encoding="utf-8")
    return original, comparison


def _rights_value(inventory: Any, entry: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "legacy-source-rights-review/2.0",
        "rights_review_id": "rightsreview_" + "6" * 32,
        "rights_review_revision_id": "rightsreviewrev_" + "7" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source": {
            "pointer_type": "INVENTORY_ENTRY",
            "inventory_id": inventory.inventory_id,
            "inventory_sha256": inventory.inventory_sha256,
            "entry_key": entry.entry_key,
            "content_sha256": entry.content_sha256,
        },
        "source_owner_reference": "eom_internal_curriculum",
        "document_type": "CURRICULUM",
        "rights_state": "CLEARED_INTERNAL",
        "allowed_internal_processing": True,
        "allowed_model_exposure": True,
        "allowed_roles": ["DATA_ANALYST_WORKER"],
        "allowed_excerpt_materialization": True,
        "allowed_page_image_materialization": False,
        "allowed_item_grounding": False,
        "answer_bearing": False,
        "retention_policy_key": "internal.curriculum.v1",
        "withdrawal_behavior": "RETIRE_FROM_NEW_RETRIEVAL",
        "evidence": [
            {
                "pointer_type": "ARTIFACT_MEMBER",
                "artifact_id": "artifact_" + "8" * 32,
                "artifact_revision_id": "rev_" + "9" * 32,
                "member_path": "evidence/review.json",
                "schema_ref": "eom://schemas/legal/source-evidence/1.0",
                "media_type": "application/json",
                "sha256": "sha256:" + "a" * 64,
            }
        ],
        "reviewed_at": "2026-08-24T19:00:00Z",
        "reviewed_by": "operator_01",
        "rights_review_sha256": "sha256:" + "0" * 64,
    }
    return _self_hash(value, "rights_review_sha256")


def _selection_value(inventory: Any, original: Any, comparison: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "legacy-source-selection/2.0",
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "selected_sources": [
            {
                "entry_key": original.entry_key,
                "content_sha256": original.content_sha256,
                "canonicality": "ORIGINAL",
                "reviewed_source_family": "CURRICULUM",
                "declared_intake_role": "GUIDELINE",
                "intended_corpus_key": "integrated-science.curriculum",
                "source_owner_reference": "eom_internal_curriculum",
                "rights_state": "CLEARED_INTERNAL",
                "rights_review": {
                    "pointer_type": "ARTIFACT_MEMBER",
                    "artifact_id": "artifact_" + "b" * 32,
                    "artifact_revision_id": "rev_" + "c" * 32,
                    "member_path": "reviews/rights.json",
                    "schema_ref": "eom://schemas/legacy-knowledge/rights-review/2.0",
                    "media_type": "application/json",
                    "sha256": "sha256:" + "d" * 64,
                },
            }
        ],
        "comparison_evidence": [
            {
                "entry_key": comparison.entry_key,
                "content_sha256": comparison.content_sha256,
                "canonicality": "DERIVED",
            }
        ],
        "reviewed_at": "2026-08-24T20:00:00Z",
        "reviewed_by": "operator_01",
    }
    identity_hash = content_sha256(value).removeprefix("sha256:")
    value["selection_id"] = "legacyselection_" + identity_hash[:32]
    value["selection_sha256"] = content_sha256(value)
    return value


class _RightsResolver:
    def __init__(self, rights: LegacySourceRightsReviewV2) -> None:
        self.rights = rights
        self.calls = 0

    def resolve(self, _pointer: Any) -> LegacySourceRightsReviewV2:
        self.calls += 1
        return self.rights


class _IntakeBoundary:
    def __init__(self) -> None:
        self.calls = 0
        self.snapshots: list[tuple[tuple[str, bytes, int], ...]] = []
        self.declarations: tuple[IntakeSourceDeclaration, ...] = ()

    def create(
        self,
        source_directory: Path,
        *,
        source_declarations: tuple[IntakeSourceDeclaration, ...],
        **_values: Any,
    ) -> LegacyContentIntakeReceipt:
        self.calls += 1
        self.declarations = source_declarations
        self.snapshots.append(
            tuple(
                (
                    path.name,
                    path.read_bytes(),
                    stat.S_IMODE(path.stat().st_mode),
                )
                for path in sorted(source_directory.iterdir())
            )
        )
        return LegacyContentIntakeReceipt(
            intake_batch_id="intake_" + "e" * 32,
            state="ANALYSIS_PENDING",
            source_fingerprint="sha256:" + "f" * 64,
            source_manifest_artifact_id="artifact_" + "1" * 32,
            source_manifest_artifact_revision_id="rev_" + "2" * 32,
            source_manifest_sha256="sha256:" + "3" * 64,
        )


class _SelectionArtifacts:
    def __init__(self) -> None:
        self.calls = 0

    def commit(self, _selection: Any, _intake: Any) -> LegacySelectionArtifactReceipt:
        self.calls += 1
        return LegacySelectionArtifactReceipt(
            artifact_id="artifact_" + "4" * 32,
            artifact_revision_id="rev_" + "5" * 32,
            content_sha256="sha256:" + "6" * 64,
            manifest_sha256="sha256:" + "7" * 64,
        )


def _prepared(tmp_path: Path):
    root = tmp_path / "legacy-root"
    staging = tmp_path / "staging"
    staging.mkdir()
    original_path, _comparison_path = _fixture(root)
    inventory = _inventory(root)
    original = next(entry for entry in inventory.entries if entry.source_family == "CURRICULUM")
    comparison = next(
        entry for entry in inventory.entries if entry.source_family == "DERIVED_EVIDENCE"
    )
    rights = LegacySourceRightsReviewV2.model_validate(_rights_value(inventory, original))
    selection = LegacySourceSelectionV2.model_validate(
        _selection_value(inventory, original, comparison)
    )
    resolver = _RightsResolver(rights)
    intake = _IntakeBoundary()
    artifacts = _SelectionArtifacts()
    service = LegacySourceSelectionService(
        settings=CatalogSettings(staging_root=staging),
        rights=resolver,
        intake=intake,
        selection_artifacts=artifacts,
    )
    return (
        service,
        selection,
        inventory,
        _roots(root),
        original_path,
        resolver,
        intake,
        artifacts,
    )


def test_v2_contracts_bind_rights_to_exact_inventory_entry(tmp_path: Path) -> None:
    (
        _service,
        selection,
        inventory,
        _roots_value,
        _original,
        resolver,
        _intake,
        _artifacts,
    ) = _prepared(tmp_path)
    validate_contract("legacy-source-selection-v2", selection.model_dump(mode="json"))
    validate_contract("legacy-source-rights-review-v2", resolver.rights.model_dump(mode="json"))
    invalid = resolver.rights.model_dump(mode="json")
    invalid.pop("source")
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("legacy-source-rights-review-v2", invalid)
    assert resolver.rights.source.inventory_id == inventory.inventory_id


def test_selection_materializes_only_original_and_replay_is_deterministic(
    tmp_path: Path,
) -> None:
    service, selection, inventory, roots, _original, resolver, intake, artifacts = _prepared(
        tmp_path
    )

    first = service.create_intake(selection=selection, inventory=inventory, roots=roots)
    second = service.create_intake(selection=selection, inventory=inventory, roots=roots)

    assert first == second
    assert first.validation.selected_source_count == 1
    assert first.validation.comparison_evidence_count == 1
    assert resolver.calls == 2
    assert intake.calls == 2
    assert artifacts.calls == 2
    assert intake.snapshots[0] == intake.snapshots[1]
    assert len(intake.snapshots[0]) == 1
    assert intake.snapshots[0][0][0].startswith("legacyentry_")
    assert intake.snapshots[0][0][1].startswith(b"%PDF-")
    assert intake.snapshots[0][0][2] == 0o600
    assert intake.declarations[0].original_filename == "[별책9] 과학과 교육과정.pdf"
    assert intake.declarations[0].declared_role == "GUIDELINE"
    assert not any(tmp_path.joinpath("staging").iterdir())


def test_stale_inventory_and_changed_bytes_fail_before_side_effects(tmp_path: Path) -> None:
    service, selection, inventory, roots, original, _resolver, intake, artifacts = _prepared(
        tmp_path
    )
    stale_value = selection.model_dump(mode="json")
    stale_value["inventory_sha256"] = "sha256:" + "0" * 64
    identity_value = {
        key: value
        for key, value in stale_value.items()
        if key not in {"selection_id", "selection_sha256"}
    }
    stale_value["selection_id"] = (
        "legacyselection_" + content_sha256(identity_value).removeprefix("sha256:")[:32]
    )
    stale_value["selection_sha256"] = content_sha256(
        {key: value for key, value in stale_value.items() if key != "selection_sha256"}
    )
    stale = LegacySourceSelectionV2.model_validate(stale_value)
    with pytest.raises(LegacySourceSelectionError) as mismatch:
        service.create_intake(selection=stale, inventory=inventory, roots=roots)
    assert mismatch.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_INVENTORY_STALE
    assert intake.calls == artifacts.calls == 0

    original.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
    with pytest.raises(LegacySourceSelectionError) as changed:
        service.create_intake(selection=selection, inventory=inventory, roots=roots)
    assert changed.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
    assert intake.calls == artifacts.calls == 0


@pytest.mark.parametrize("replacement", ["symlink", "hardlink"])
def test_selection_rejects_link_substitution(tmp_path: Path, replacement: str) -> None:
    service, selection, inventory, roots, original, _resolver, intake, artifacts = _prepared(
        tmp_path
    )
    original.unlink()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7\nsynthetic integrated science\n%%EOF\n")
    if replacement == "symlink":
        original.symlink_to(outside)
    else:
        os.link(outside, original)

    with pytest.raises(LegacySourceSelectionError) as failure:
        service.create_intake(selection=selection, inventory=inventory, roots=roots)
    assert failure.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
    assert intake.calls == artifacts.calls == 0


def test_wrong_rights_source_and_wrong_class_fail_closed(tmp_path: Path) -> None:
    service, selection, inventory, roots, _original, resolver, intake, artifacts = _prepared(
        tmp_path
    )
    rights_value = resolver.rights.model_dump(mode="json")
    rights_value["source"]["entry_key"] = "legacyentry_" + "0" * 32
    rights_value = _self_hash(rights_value, "rights_review_sha256")
    resolver.rights = LegacySourceRightsReviewV2.model_validate(rights_value)
    with pytest.raises(LegacySourceSelectionError) as rights_failure:
        service.create_intake(selection=selection, inventory=inventory, roots=roots)
    assert (
        rights_failure.value.code
        == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_RIGHTS_INVALID
    )
    assert intake.calls == artifacts.calls == 0

    selection_value = selection.model_dump(mode="json")
    selection_value["selected_sources"][0]["reviewed_source_family"] = "TEXTBOOK"
    identity_value = {
        key: value
        for key, value in selection_value.items()
        if key not in {"selection_id", "selection_sha256"}
    }
    selection_value["selection_id"] = (
        "legacyselection_" + content_sha256(identity_value).removeprefix("sha256:")[:32]
    )
    selection_value["selection_sha256"] = content_sha256(
        {key: value for key, value in selection_value.items() if key != "selection_sha256"}
    )
    wrong_class = LegacySourceSelectionV2.model_validate(selection_value)
    resolver.rights = LegacySourceRightsReviewV2.model_validate(
        _rights_value(
            inventory,
            next(entry for entry in inventory.entries if entry.source_family == "CURRICULUM"),
        )
    )
    with pytest.raises(LegacySourceSelectionError) as class_failure:
        service.create_intake(selection=wrong_class, inventory=inventory, roots=roots)
    assert (
        class_failure.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CLASS_INVALID
    )


def test_selection_id_and_self_hash_reject_conflicting_replay(tmp_path: Path) -> None:
    _service, selection, _inventory, _roots_value, _original, *_rest = _prepared(tmp_path)
    conflicting = copy.deepcopy(selection.model_dump(mode="json"))
    conflicting["selected_sources"][0]["intended_corpus_key"] = "different.corpus"
    conflicting["selection_sha256"] = content_sha256(
        {key: value for key, value in conflicting.items() if key != "selection_sha256"}
    )
    with pytest.raises(ValueError, match="selection_id"):
        LegacySourceSelectionV2.model_validate(conflicting)


def test_selection_cli_inspect_emits_only_bounded_identity(tmp_path: Path) -> None:
    _service, selection, _inventory_value, _roots_value, original, *_rest = _prepared(tmp_path)
    selection_file = (tmp_path / "selection.json").absolute()
    selection_file.write_text(
        json.dumps(selection.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    selection_file.chmod(0o600)

    result = CliRunner().invoke(
        app,
        [
            "knowledge",
            "legacy",
            "selection",
            "inspect",
            "--selection-file",
            str(selection_file),
        ],
    )

    assert result.exit_code == 0, result.stdout
    output = json.loads(result.stdout)
    assert output["selection_id"] == selection.selection_id
    assert output["selected_source_count"] == 1
    assert str(original.parent.parent.parent) not in result.stdout
