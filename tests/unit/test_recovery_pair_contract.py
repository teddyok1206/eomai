from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator

from scripts.infra import verify_recovery_pair as recovery_pair
from scripts.infra.verify_recovery_pair import (
    ArtifactStoreSnapshotManifestV1,
    RecoveryRevisionReceiptV1,
    RecoveryValidationReceiptV1,
    build_snapshot_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def _recovery_revision_schema() -> dict[str, object]:
    full_schema = json.loads(
        (ROOT / "schemas/infra/recovery-validation-receipt-v1.schema.json").read_text()
    )
    return full_schema["$defs"]["revision"] | {"$defs": full_schema["$defs"]}


def _artifact_snapshot(root: Path) -> None:
    revision = root / ("artifact_" + "1" * 32) / ("rev_" + "2" * 32)
    revision.mkdir(parents=True)
    payload = b'{"status":"ok"}'
    (revision / "result.json").write_bytes(payload)
    manifest = {
        "manifest_version": "artifact-file-set/1.0",
        "job_id": "job_" + "3" * 32,
        "logical_artifact_id": "artifact_" + "1" * 32,
        "revision_id": "rev_" + "2" * 32,
        "artifact_type": "test-result",
        "primary_file": "result.json",
        "content_hash": sha256_bytes(payload),
        "content_bytes": len(payload),
        "files": [
            {
                "file_name": "result.json",
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
            }
        ],
        "created_at": "2026-10-02T00:00:00Z",
    }
    (revision / "manifest.json").write_bytes(canonical_json_bytes(manifest))


def test_snapshot_manifest_is_self_hashed_and_schema_valid(tmp_path: Path) -> None:
    snapshot = tmp_path / "artifact-snapshot-test"
    snapshot.mkdir()
    _artifact_snapshot(snapshot)
    manifest = build_snapshot_manifest(
        snapshot,
        captured_at=datetime(2026, 10, 2, tzinfo=UTC),
        artifact_root_label="isolated-test",
    )
    assert manifest.artifact_revision_count == 1
    assert manifest.snapshot_id.endswith(manifest.snapshot_sha256[7:39])
    schema = json.loads(
        (ROOT / "schemas/infra/artifact-store-snapshot-manifest-v1.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(manifest.model_dump(mode="json"))


def test_snapshot_inventory_rejects_symlink_revision(tmp_path: Path) -> None:
    snapshot = tmp_path / "artifact-snapshot-test"
    snapshot.mkdir()
    artifact = snapshot / ("artifact_" + "1" * 32)
    artifact.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (artifact / ("rev_" + "2" * 32)).symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="unexpected revision"):
        build_snapshot_manifest(
            snapshot,
            captured_at=datetime(2026, 10, 2, tzinfo=UTC),
            artifact_root_label="isolated-test",
        )


@pytest.mark.parametrize("snapshot_relation", ("same", "descendant", "ancestor"))
def test_snapshot_root_rejects_live_artifact_tree_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot_relation: str,
) -> None:
    live_root = tmp_path / "storage" / "artifacts"
    live_root.mkdir(parents=True)
    monkeypatch.setattr(recovery_pair, "LIVE_ARTIFACT_ROOT", live_root)
    roots = {
        "same": live_root,
        "descendant": live_root / "snapshot",
        "ancestor": live_root.parent,
    }
    snapshot = roots[snapshot_relation]
    snapshot.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="ancestors"):
        build_snapshot_manifest(
            snapshot,
            captured_at=datetime(2026, 10, 2, tzinfo=UTC),
            artifact_root_label="isolated-test",
        )


def test_snapshot_inventory_rejects_unlisted_or_nested_symlink_members(tmp_path: Path) -> None:
    snapshot = tmp_path / "artifact-snapshot-test"
    snapshot.mkdir()
    _artifact_snapshot(snapshot)
    revision = snapshot / ("artifact_" + "1" * 32) / ("rev_" + "2" * 32)
    (revision / "unlisted.bin").write_bytes(b"not in manifest")
    with pytest.raises(ValueError, match="differ from its manifest"):
        build_snapshot_manifest(
            snapshot,
            captured_at=datetime(2026, 10, 2, tzinfo=UTC),
            artifact_root_label="isolated-test",
        )
    (revision / "unlisted.bin").unlink()
    nested = revision / "nested"
    nested.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        build_snapshot_manifest(
            snapshot,
            captured_at=datetime(2026, 10, 2, tzinfo=UTC),
            artifact_root_label="isolated-test",
        )


def test_recovery_receipt_rejects_wrong_self_hash() -> None:
    payload = {
        "schema_version": "recovery-validation-receipt/1.0",
        "verification_mode": "SAMPLED",
        "database_backup_id": "pgbackup_20261002T000000Z_" + "1" * 12,
        "database_backup_created_at": "2026-10-02T00:00:00Z",
        "database_backup_sha256": "sha256:" + "1" * 64,
        "database_manifest_sha256": "sha256:" + "2" * 64,
        "database_inventory_sha256": "sha256:" + "5" * 64,
        "artifact_snapshot_id": "artifactsnapshot_" + "3" * 32,
        "artifact_snapshot_captured_at": "2026-10-02T00:00:01Z",
        "artifact_snapshot_sha256": "sha256:" + "4" * 64,
        "artifact_inventory_sha256": "sha256:" + "5" * 64,
        "restored_database_identity": "eom_test_recovery",
        "artifact_revision_count": 0,
        "verified_revision_count": 0,
        "verified_member_count": 0,
        "evidence_revision_count": 0,
        "evidence_member_count": 0,
        "evidence_revisions": [],
        "validated_at": "2026-10-02T00:00:00Z",
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValueError, match="receipt hash"):
        RecoveryValidationReceiptV1.model_validate(payload)
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256")
    payload["receipt_sha256"] = content_sha256(unsigned)
    assert RecoveryValidationReceiptV1.model_validate(payload).evidence_revision_count == 0


def test_recovery_receipt_rejects_inventory_or_full_coverage_mismatch() -> None:
    base = {
        "schema_version": "recovery-validation-receipt/1.0",
        "verification_mode": "FULL",
        "database_backup_id": "pgbackup_20261002T000000Z_" + "1" * 12,
        "database_backup_created_at": "2026-10-02T00:00:00Z",
        "database_backup_sha256": "sha256:" + "1" * 64,
        "database_manifest_sha256": "sha256:" + "2" * 64,
        "database_inventory_sha256": "sha256:" + "3" * 64,
        "artifact_snapshot_id": "artifactsnapshot_" + "4" * 32,
        "artifact_snapshot_captured_at": "2026-10-02T00:00:01Z",
        "artifact_snapshot_sha256": "sha256:" + "5" * 64,
        "artifact_inventory_sha256": "sha256:" + "6" * 64,
        "restored_database_identity": "eom_restore_drill",
        "artifact_revision_count": 2,
        "verified_revision_count": 1,
        "verified_member_count": 0,
        "evidence_revision_count": 0,
        "evidence_member_count": 0,
        "evidence_revisions": [],
        "validated_at": "2026-10-02T00:00:02Z",
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValueError, match="inventories"):
        RecoveryValidationReceiptV1.model_validate(base)
    base["artifact_inventory_sha256"] = base["database_inventory_sha256"]
    with pytest.raises(ValueError, match="every Artifact revision"):
        RecoveryValidationReceiptV1.model_validate(base)


def test_snapshot_manifest_model_rejects_forged_identity() -> None:
    with pytest.raises(ValueError, match="snapshot identity"):
        ArtifactStoreSnapshotManifestV1.model_validate(
            {
                "schema_version": "artifact-store-snapshot-manifest/1.0",
                "snapshot_id": "artifactsnapshot_" + "0" * 32,
                "captured_at": "2026-10-02T00:00:00Z",
                "artifact_root_label": "isolated-test",
                "artifact_revision_count": 0,
                "inventory_sha256": "sha256:" + "1" * 64,
                "snapshot_sha256": "sha256:" + "2" * 64,
            }
        )


def test_snapshot_builder_normalizes_timestamps_to_utc(tmp_path: Path) -> None:
    snapshot = tmp_path / "artifact-snapshot-test"
    snapshot.mkdir()
    _artifact_snapshot(snapshot)
    manifest = build_snapshot_manifest(
        snapshot,
        captured_at=datetime.fromisoformat("2026-10-02T09:00:00+09:00"),
        artifact_root_label="isolated-test",
    )
    assert manifest.captured_at == datetime(2026, 10, 2, tzinfo=UTC)


def test_recovery_revision_receipt_accepts_safe_nested_primary_member() -> None:
    receipt = RecoveryRevisionReceiptV1(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        artifact_type="evidence-bundle",
        content_sha256="sha256:" + "3" * 64,
        manifest_sha256="sha256:" + "4" * 64,
        primary_file="evidence/manifest.json",
        member_count=2,
    )
    assert receipt.primary_file == "evidence/manifest.json"
    Draft202012Validator(_recovery_revision_schema()).validate(receipt.model_dump(mode="json"))


@pytest.mark.parametrize("primary_file", ("/absolute.json", "../escape.json", "a/../b.json"))
def test_recovery_revision_receipt_rejects_unsafe_primary_member(primary_file: str) -> None:
    value = {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "artifact_type": "evidence-bundle",
        "content_sha256": "sha256:" + "3" * 64,
        "manifest_sha256": "sha256:" + "4" * 64,
        "primary_file": primary_file,
        "member_count": 2,
    }
    with pytest.raises(ValueError):
        RecoveryRevisionReceiptV1.model_validate(value)
    assert not Draft202012Validator(_recovery_revision_schema()).is_valid(value)
