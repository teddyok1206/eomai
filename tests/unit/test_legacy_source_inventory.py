from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    LegacyKnowledgeContractErrorCode,
    LegacyRootAlias,
    LegacySourceInventoryPolicy,
    catalog_schema_inventory,
    validate_contract,
)
from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.legacy_knowledge_intake_service import LegacyKnowledgeIntakeService
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryError,
    LegacySourceInventoryScanner,
    LegacySourceRootConfiguration,
    load_inventory_manifest,
    load_inventory_policy,
    load_root_configuration,
    write_inventory_manifest,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eomctl.cli import app
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
OBSERVED = datetime(2026, 8, 24, 16, 30, tzinfo=UTC)


def _self_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = content_sha256({key: item for key, item in value.items() if key != field})
    return value


def _exclusions() -> list[dict[str, str]]:
    values = [
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
    return sorted(values, key=lambda value: (value["match_kind"], value["value"], value["reason"]))


def _policy_value(*, max_observations: int = 5000) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "legacy-source-inventory-policy/1.0",
        "policy_revision_id": "legacyinventorypolicyrev_" + "1" * 32,
        "scanner_version": "1.0.0",
        "limits": {
            "max_observations": max_observations,
            "max_candidate_bytes": 4 * 1024 * 1024 * 1024,
            "max_file_bytes": 512 * 1024 * 1024,
            "max_depth": 16,
            "max_path_length": 500,
            "signature_scan_bytes": 64 * 1024,
        },
        "classification_rules": [
            {
                "rule_id": "legacyinventoryrule_" + "2" * 32,
                "root_alias": "EOMIS_LEGACY_SOURCE",
                "relative_prefix": "source/derived",
                "preliminary_class": "DERIVED_MIGRATION_EVIDENCE",
                "source_family": "DERIVED_EVIDENCE",
                "allowed_suffixes": [".json", ".md", ".png"],
            },
            {
                "rule_id": "legacyinventoryrule_" + "3" * 32,
                "root_alias": "EOMIS_LEGACY_SOURCE",
                "relative_prefix": "source/originals",
                "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
                "source_family": "ITEM",
                "allowed_suffixes": [".hwp", ".hwpx", ".pdf"],
            },
        ],
        "exclusion_rules": _exclusions(),
        "policy_sha256": "sha256:" + "0" * 64,
    }
    return _self_hash(value, "policy_sha256")


def _policy(*, max_observations: int = 5000) -> LegacySourceInventoryPolicy:
    return LegacySourceInventoryPolicy.model_validate(
        _policy_value(max_observations=max_observations)
    )


def _root_configuration(root: Path) -> LegacySourceRootConfiguration:
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


def _write_fixture(root: Path) -> None:
    originals = root / "source" / "originals"
    derived = root / "source" / "derived"
    originals.mkdir(parents=True)
    derived.mkdir(parents=True)
    (originals / "original.pdf").write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    hwp = originals / "linked.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic")
    os.link(hwp, originals / "linked-copy.hwp")
    (originals / "link.pdf").symlink_to("original.pdf")
    (derived / "derived.json").write_text('{"synthetic":true}\n', encoding="utf-8")
    (derived / ".env").write_text("TOKEN=synthetic-secret-value\n", encoding="utf-8")
    (derived / "secrets.json").write_text(
        '{"api_key":"synthetic-credential-material-123456"}\n', encoding="utf-8"
    )
    (derived / "cache.sqlite").write_bytes(b"SQLite format 3\0")
    (derived / "unsupported.bin").write_bytes(b"synthetic")
    os.mkfifo(derived / "runtime.pipe")


def _scan(root: Path, *, observed_at: datetime = OBSERVED, max_observations: int = 5000):
    return LegacySourceInventoryScanner().scan(
        policy=_policy(max_observations=max_observations),
        roots=_root_configuration(root),
        root_alias=LegacyRootAlias.EOMIS_LEGACY_SOURCE,
        observed_at=observed_at,
    )


def test_inventory_policy_and_v2_schema_are_canonical_and_packaged() -> None:
    inventory = dict(catalog_schema_inventory())
    assert inventory["legacy-source-inventory"].sha256 == (
        "sha256:7fdce3b0bfeab4248c546d3eb6404fc9ddc8a5f340b31d48d3e4f3ac70954411"
    )
    for name, filename in (
        ("legacy-source-inventory-policy", "legacy-source-inventory-policy-v1.schema.json"),
        ("legacy-source-inventory-v2", "legacy-source-inventory-v2.schema.json"),
    ):
        resource = inventory[name]
        canonical = ROOT / "schemas" / "legacy-knowledge" / filename
        packaged = (
            ROOT
            / "packages"
            / "catalog_contracts"
            / "eom_catalog_contracts"
            / "resources"
            / "legacy-knowledge"
            / filename
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        assert resource.sha256 == "sha256:" + hashlib.sha256(canonical.read_bytes()).hexdigest()
    validate_contract("legacy-source-inventory-policy", _policy_value())
    example = load_inventory_policy(
        (ROOT / "config" / "legacy-source-inventory-policy.example.json").absolute()
    )
    assert example.policy_sha256 == (
        "sha256:956acee0036faac465a2ee75e258f3a789a9bbda8b696214b078cde5b81cf9aa"
    )


def test_scanner_classifies_synthetic_files_without_following_links(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)

    inventory = _scan(root)

    assert inventory.summary.original_source_candidates.file_count == 1
    assert inventory.summary.derived_migration_evidence.file_count == 1
    assert inventory.summary.excluded_runtime_state.file_count == 8
    by_name = {Path(entry.relative_path).name: entry for entry in inventory.entries}
    assert by_name["original.pdf"].media_type == "application/pdf"
    assert by_name["derived.json"].media_type == "application/json"
    assert by_name["link.pdf"].file_observation == "SYMLINK"
    assert by_name["linked.hwp"].file_observation == "HARDLINK"
    assert by_name["linked-copy.hwp"].content_sha256 is None
    assert by_name[".env"].exclusion_reasons == ("SECRET_OR_CREDENTIAL",)
    assert by_name["secrets.json"].exclusion_reasons == ("SECRET_OR_CREDENTIAL",)
    assert by_name["secrets.json"].content_sha256 is None
    assert by_name["cache.sqlite"].exclusion_reasons == ("RUNTIME_DATABASE_OR_INDEX",)
    assert by_name["runtime.pipe"].file_observation == "SPECIAL"
    assert by_name["unsupported.bin"].exclusion_reasons == ("OUTSIDE_ALLOWLIST",)
    serialized = json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False)
    assert str(root) not in serialized
    validate_contract("legacy-source-inventory-v2", inventory.model_dump(mode="json"))


def test_identical_observation_has_stable_identity_but_distinct_audit_time(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)

    first = _scan(root)
    second = _scan(root, observed_at=OBSERVED + timedelta(minutes=1))

    assert first.observed_at != second.observed_at
    assert first.source_set_sha256 == second.source_set_sha256
    assert first.inventory_id == second.inventory_id
    assert first.inventory_sha256 == second.inventory_sha256

    changed = root / "source" / "derived" / "derived.json"
    changed.write_text('{"synthetic":false}\n', encoding="utf-8")
    third = _scan(root, observed_at=OBSERVED + timedelta(minutes=2))
    assert third.source_set_sha256 != first.source_set_sha256
    assert third.inventory_id != first.inventory_id


def test_scan_does_not_mutate_observed_file_bytes_or_metadata(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    observed = root / "source" / "originals" / "original.pdf"
    before = observed.stat()
    before_bytes = observed.read_bytes()

    _scan(root)

    after = observed.stat()
    assert observed.read_bytes() == before_bytes
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ctime_ns == before.st_ctime_ns


def test_manifest_write_is_exclusive_protected_and_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    inventory = _scan(root)
    manifest = (tmp_path / "inventory.json").absolute()

    write_inventory_manifest(manifest, inventory)

    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert load_inventory_manifest(manifest) == inventory
    with pytest.raises(LegacySourceInventoryError) as failure:
        write_inventory_manifest(manifest, inventory)
    assert failure.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID


def test_scanner_rejects_symlink_root_and_casefold_collision(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    alias = tmp_path / "legacy-link"
    alias.symlink_to(root, target_is_directory=True)

    with pytest.raises(LegacySourceInventoryError) as failure:
        _scan(alias)
    assert failure.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_INVALID

    (root / "source" / "derived" / "A.json").write_text("{}", encoding="utf-8")
    (root / "source" / "derived" / "a.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LegacySourceInventoryError) as collision:
        _scan(root)
    assert collision.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_DUPLICATE_ENTRY


def test_scanner_fails_closed_at_capacity_and_signature_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    with pytest.raises(LegacySourceInventoryError) as failure:
        _scan(root, max_observations=1)
    assert failure.value.code == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CAPACITY_EXCEEDED

    (root / "source" / "originals" / "original.pdf").write_bytes(b"not a PDF")
    inventory = _scan(root)
    original = next(
        entry for entry in inventory.entries if entry.relative_path.endswith("original.pdf")
    )
    assert original.content_sha256 is None
    assert original.exclusion_reasons == ("UNSUPPORTED_MEDIA",)


def test_policy_fails_closed_without_mandatory_exclusions() -> None:
    value = _policy_value()
    value["exclusion_rules"] = [
        rule for rule in value["exclusion_rules"] if rule["value"] != ".pem"
    ]
    value = _self_hash(value, "policy_sha256")
    with pytest.raises(ValueError, match="mandatory safety exclusion"):
        LegacySourceInventoryPolicy.model_validate(value)


def test_control_documents_require_safe_modes_and_do_not_expose_root(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    policy_path = tmp_path / "policy.json"
    roots_path = tmp_path / "roots.json"
    policy_path.write_text(json.dumps(_policy_value()), encoding="utf-8")
    roots_path.write_text(
        _root_configuration(root).model_dump_json(),
        encoding="utf-8",
    )
    policy_path.chmod(0o644)
    roots_path.chmod(0o600)

    assert load_inventory_policy(policy_path) == _policy()
    assert load_root_configuration(roots_path) == _root_configuration(root)

    roots_path.chmod(0o644)
    with pytest.raises(LegacySourceInventoryError) as failure:
        load_root_configuration(roots_path)
    assert (
        failure.value.code
        == LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONFIGURATION_INVALID
    )


class _ArtifactRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def commit_file_set(self, **kwargs: Any) -> CatalogArtifact:
        self.calls.append(kwargs)
        assert set(kwargs["files"]) == {"legacy-source-inventory.json"}
        assert kwargs["files"]["legacy-source-inventory.json"].is_file()
        assert kwargs["idempotency_key"].startswith("legacy-source-inventory:sha256:")
        return CatalogArtifact(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash="sha256:" + "4" * 64,
            manifest_hash="sha256:" + "5" * 64,
            content_bytes=10,
            nas_path="/not-emitted",
            manifest={},
        )


def test_commit_delegates_only_manifest_to_existing_artifact_boundary(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    inventory = _scan(root)
    staging = tmp_path / "staging"
    staging.mkdir()
    recorder = _ArtifactRecorder()
    service = LegacyKnowledgeIntakeService(settings=CatalogSettings(staging_root=staging))
    service.artifacts = cast(CatalogArtifactService, recorder)

    result = service.commit_inventory(inventory)

    assert result.inventory_id == inventory.inventory_id
    assert result.artifact_id == "artifact_" + "2" * 32
    call = recorder.calls[0]
    assert call["result"]["source_set_sha256"] == inventory.source_set_sha256
    assert call["file_metadata"]["legacy-source-inventory.json"]["media_type"] == (
        "application/json"
    )
    assert not tuple(staging.iterdir())


def test_eomctl_dry_run_and_inspect_emit_only_safe_summary(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write_fixture(root)
    policy_path = tmp_path / "policy.json"
    roots_path = tmp_path / "roots.json"
    manifest_path = (tmp_path / "manifest.json").absolute()
    policy_path.write_text(json.dumps(_policy_value()), encoding="utf-8")
    roots_path.write_text(_root_configuration(root).model_dump_json(), encoding="utf-8")
    policy_path.chmod(0o644)
    roots_path.chmod(0o600)
    runner = CliRunner()

    dry_run = runner.invoke(
        app,
        [
            "knowledge",
            "legacy",
            "inventory",
            "dry-run",
            "--root-alias",
            "EOMIS_LEGACY_SOURCE",
            "--policy-file",
            str(policy_path),
            "--root-config-file",
            str(roots_path),
            "--manifest-file",
            str(manifest_path),
        ],
    )
    assert dry_run.exit_code == 0, dry_run.stdout
    assert str(root) not in dry_run.stdout
    assert '"manifest_created": true' in dry_run.stdout

    inspected = runner.invoke(
        app,
        [
            "knowledge",
            "legacy",
            "inventory",
            "inspect",
            "--manifest-file",
            str(manifest_path),
        ],
    )
    assert inspected.exit_code == 0, inspected.stdout
    assert str(root) not in inspected.stdout
    assert '"schema_version": "legacy-source-inventory/2.0"' in inspected.stdout
