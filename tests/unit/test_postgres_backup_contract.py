from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError as PydanticValidationError

from scripts.infra.postgres_backup_contract import (
    PostgresBackupManifestV1,
    build_manifest,
    canonical_manifest_bytes,
    load_schema,
    parse_manifest,
    verify_backup_pair,
)

CREATED_AT = "20260915T160000Z"


def _pair(root: Path, payload: bytes = b"postgres-custom-dump") -> tuple[Path, Path]:
    digest = hashlib.sha256(payload).hexdigest()
    dump = root / f"eom_{CREATED_AT}_{digest[:12]}.dump"
    manifest_path = root / f"eom_{CREATED_AT}_{digest[:12]}.manifest.json"
    dump.write_bytes(payload)
    manifest = build_manifest(
        created_at_utc=CREATED_AT,
        database="eom",
        postgres_version="postgres (PostgreSQL) 18.6",
        file_name=dump.name,
        size_bytes=len(payload),
        sha256=digest,
    )
    manifest_path.write_bytes(canonical_manifest_bytes(manifest))
    return dump, manifest_path


def test_schema_and_pydantic_accept_exact_v1_manifest() -> None:
    schema = load_schema()
    digest = hashlib.sha256(b"dump").hexdigest()
    manifest = build_manifest(
        created_at_utc=CREATED_AT,
        database="eom",
        postgres_version="postgres (PostgreSQL) 18.6",
        file_name=f"eom_{CREATED_AT}_{digest[:12]}.dump",
        size_bytes=4,
        sha256=digest,
    )

    Draft202012Validator(schema).validate(manifest.model_dump(mode="json"))
    assert PostgresBackupManifestV1.model_validate(manifest.model_dump(mode="json")) == manifest


def test_identity_cannot_disagree_with_timestamp_or_hash() -> None:
    digest = hashlib.sha256(b"dump").hexdigest()

    with pytest.raises(PydanticValidationError, match="backup_id does not match"):
        PostgresBackupManifestV1.model_validate(
            {
                "schema_version": "postgres-backup-manifest/1.0",
                "backup_id": f"pgbackup_{CREATED_AT}_000000000000",
                "created_at_utc": CREATED_AT,
                "database": "eom",
                "postgres_version": "postgres (PostgreSQL) 18.6",
                "dump_format": "custom",
                "file": f"eom_{CREATED_AT}_{digest[:12]}.dump",
                "size_bytes": 4,
                "sha256": digest,
            }
        )


def test_verify_backup_pair_checks_exact_bytes(tmp_path: Path) -> None:
    dump, manifest_path = _pair(tmp_path)

    manifest, legacy = verify_backup_pair(dump, manifest_path, backup_root=tmp_path)

    assert not legacy
    assert manifest.file == dump.name
    assert manifest.size_bytes == dump.stat().st_size


@pytest.mark.parametrize("field", ["size_bytes", "sha256", "file"])
def test_verify_backup_pair_rejects_manifest_drift(tmp_path: Path, field: str) -> None:
    dump, manifest_path = _pair(tmp_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if field == "size_bytes":
        value[field] += 1
    elif field == "sha256":
        value[field] = "0" * 64
        value["backup_id"] = f"pgbackup_{CREATED_AT}_{'0' * 12}"
        value["file"] = f"eom_{CREATED_AT}_{'0' * 12}.dump"
    else:
        value[field] = f"eom_{CREATED_AT}_{'0' * 12}.dump"
    manifest_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError):
        verify_backup_pair(dump, manifest_path, backup_root=tmp_path)


def test_verify_backup_pair_rejects_symlink_manifest(tmp_path: Path) -> None:
    dump, manifest_path = _pair(tmp_path)
    real_manifest = tmp_path / "real.manifest"
    manifest_path.rename(real_manifest)
    manifest_path.symlink_to(real_manifest)

    with pytest.raises(OSError):
        verify_backup_pair(dump, manifest_path, backup_root=tmp_path)


def test_verify_backup_pair_rejects_hard_linked_dump(tmp_path: Path) -> None:
    dump, manifest_path = _pair(tmp_path)
    os.link(dump, tmp_path / "second-link.dump")

    with pytest.raises(ValueError, match="single-link regular file"):
        verify_backup_pair(dump, manifest_path, backup_root=tmp_path)


def test_legacy_manifest_is_explicitly_adapted(tmp_path: Path) -> None:
    dump, manifest_path = _pair(tmp_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy = {
        key: value[key]
        for key in (
            "created_at_utc",
            "database",
            "postgres_version",
            "file",
            "size_bytes",
            "sha256",
        )
    }
    manifest_path.write_text(json.dumps(legacy), encoding="utf-8")

    manifest, legacy_used = verify_backup_pair(dump, manifest_path, backup_root=tmp_path)

    assert legacy_used
    assert manifest.schema_version == "postgres-backup-manifest/1.0"


def test_legacy_manifest_rejects_unknown_fields() -> None:
    value = {
        "created_at_utc": CREATED_AT,
        "database": "eom",
        "postgres_version": "postgres (PostgreSQL) 18.6",
        "file": f"eom_{CREATED_AT}_{'0' * 12}.dump",
        "size_bytes": 1,
        "sha256": "0" * 64,
        "unexpected": True,
    }

    with pytest.raises(ValueError, match="unknown or missing"):
        parse_manifest(value)


def test_canonical_manifest_has_one_newline() -> None:
    digest = hashlib.sha256(b"dump").hexdigest()
    manifest = build_manifest(
        created_at_utc=CREATED_AT,
        database="eom",
        postgres_version="postgres (PostgreSQL) 18.6",
        file_name=f"eom_{CREATED_AT}_{digest[:12]}.dump",
        size_bytes=4,
        sha256=digest,
    )

    encoded = canonical_manifest_bytes(manifest)

    assert encoded.endswith(b"\n")
    assert not encoded.endswith(b"\n\n")


def test_shell_boundaries_use_the_typed_contract_before_restore_mutation() -> None:
    root = Path(__file__).resolve().parents[2]
    backup = (root / "scripts/infra/postgres_backup.sh").read_text(encoding="utf-8")
    restore = (root / "scripts/infra/postgres_restore_dry_run.sh").read_text(encoding="utf-8")

    assert "postgres_backup_contract.py" in backup
    assert "postgres_backup_contract.py" in restore
    invocation = '"$EOM_CORE_PYTHON" -I "$MANIFEST_CONTRACT" verify'
    assert invocation in backup.replace("\\\n  ", "")
    assert invocation in restore
    assert "python3" not in backup
    assert "python3" not in restore
    assert restore.index('MANIFEST_CONTRACT" verify') < restore.index("docker cp")
    assert 'RESTORE_DB="eom_restore_${TS}_$$"' in restore
    assert 'ln "$NAS_TMP" "$NAS_FINAL"' in backup
    assert 'ln "$NAS_MANIFEST_TMP" "$NAS_MANIFEST"' in backup
    assert 'mv "$NAS_TMP" "$NAS_FINAL"' not in backup
    assert "REMOVE_PUBLISHED" not in backup
    assert backup.index('ln "$NAS_TMP" "$NAS_FINAL"') < backup.index("DUMP_PUBLISHED=1")
    assert backup.index('ln "$NAS_MANIFEST_TMP" "$NAS_MANIFEST"') < backup.index(
        "MANIFEST_PUBLISHED=1"
    )
    assert 'if [[ "${DUMP_PUBLISHED:-0}" == "1" ]]' in backup
    assert 'if [[ "${MANIFEST_PUBLISHED:-0}" == "1" ]]' in backup
