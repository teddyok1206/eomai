from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "schemas/infra/postgres-backup-manifest-v1.schema.json"
BACKUP_ROOT = Path("/mnt/nas/eom/backups/postgresql")
MAX_MANIFEST_BYTES = 16 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
LEGACY_KEYS = frozenset(
    {"created_at_utc", "database", "postgres_version", "file", "size_bytes", "sha256"}
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PostgresBackupManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["postgres-backup-manifest/1.0"]
    backup_id: str = Field(pattern=r"^pgbackup_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}$")
    created_at_utc: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    database: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[A-Za-z_][A-Za-z0-9_$-]*$",
    )
    postgres_version: str = Field(min_length=1, max_length=200)
    dump_format: Literal["custom"]
    file: str = Field(pattern=r"^eom_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}\.dump$")
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> PostgresBackupManifestV1:
        datetime.strptime(self.created_at_utc, "%Y%m%dT%H%M%SZ")
        short_hash = self.sha256[:12]
        expected_id = f"pgbackup_{self.created_at_utc}_{short_hash}"
        expected_file = f"eom_{self.created_at_utc}_{short_hash}.dump"
        if self.backup_id != expected_id:
            raise ValueError("backup_id does not match timestamp and content hash")
        if self.file != expected_file:
            raise ValueError("backup file does not match timestamp and content hash")
        return self


def load_schema() -> dict[str, Any]:
    value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("backup manifest schema must be an object")
    Draft202012Validator.check_schema(value)
    return value


def canonical_manifest_bytes(manifest: PostgresBackupManifestV1) -> bytes:
    payload = manifest.model_dump(mode="json")
    Draft202012Validator(load_schema()).validate(payload)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_manifest(
    *,
    created_at_utc: str,
    database: str,
    postgres_version: str,
    file_name: str,
    size_bytes: int,
    sha256: str,
) -> PostgresBackupManifestV1:
    return PostgresBackupManifestV1.model_validate(
        {
            "schema_version": "postgres-backup-manifest/1.0",
            "backup_id": f"pgbackup_{created_at_utc}_{sha256[:12]}",
            "created_at_utc": created_at_utc,
            "database": database,
            "postgres_version": postgres_version,
            "dump_format": "custom",
            "file": file_name,
            "size_bytes": size_bytes,
            "sha256": sha256,
        }
    )


def parse_manifest(value: object) -> tuple[PostgresBackupManifestV1, bool]:
    if not isinstance(value, Mapping):
        raise ValueError("backup manifest must be an object")
    payload = dict(value)
    if payload.get("schema_version") == "postgres-backup-manifest/1.0":
        Draft202012Validator(load_schema()).validate(payload)
        return PostgresBackupManifestV1.model_validate(payload), False
    if frozenset(payload) != LEGACY_KEYS:
        raise ValueError("legacy backup manifest has unknown or missing fields")
    created_at = payload.get("created_at_utc")
    sha256 = payload.get("sha256")
    if not isinstance(created_at, str) or not isinstance(sha256, str):
        raise ValueError("legacy backup identity fields are invalid")
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("legacy backup hash is invalid")
    adapted = {
        "schema_version": "postgres-backup-manifest/1.0",
        "backup_id": f"pgbackup_{created_at}_{sha256[:12]}",
        "dump_format": "custom",
        **payload,
    }
    manifest = PostgresBackupManifestV1.model_validate(adapted)
    Draft202012Validator(load_schema()).validate(manifest.model_dump(mode="json"))
    return manifest, True


def _require_direct_child(root: Path, path: Path) -> str:
    if not root.is_absolute() or not path.is_absolute() or path.parent != root:
        raise ValueError("backup path must be a direct child of the fixed backup root")
    if path.name in {"", ".", ".."} or Path(path.name).name != path.name:
        raise ValueError("backup path has an invalid leaf")
    return path.name


def _open_root(root: Path) -> int:
    metadata = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("backup root is unsafe")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(root, flags)


def _open_regular(root_fd: int, leaf: str) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(leaf, flags, dir_fd=root_fd)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise ValueError("backup member must be a single-link regular file")
    return descriptor


def _stable_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(4096, maximum + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > maximum:
            raise ValueError("backup manifest exceeds the bounded size")
    return b"".join(chunks)


def _hash_file(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, HASH_CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def verify_backup_pair(
    dump_path: Path,
    manifest_path: Path,
    *,
    backup_root: Path = BACKUP_ROOT,
) -> tuple[PostgresBackupManifestV1, bool]:
    dump_leaf = _require_direct_child(backup_root, dump_path)
    manifest_leaf = _require_direct_child(backup_root, manifest_path)
    if manifest_leaf != f"{dump_path.stem}.manifest.json":
        raise ValueError("backup manifest leaf does not match dump leaf")

    root_fd = _open_root(backup_root)
    try:
        manifest_fd = _open_regular(root_fd, manifest_leaf)
        try:
            manifest_before = os.fstat(manifest_fd)
            raw_manifest = _read_bounded(manifest_fd, MAX_MANIFEST_BYTES)
            manifest_after = os.fstat(manifest_fd)
        finally:
            os.close(manifest_fd)
        if _stable_identity(manifest_before) != _stable_identity(manifest_after):
            raise ValueError("backup manifest changed while being read")
        try:
            payload = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("backup manifest is not valid UTF-8 JSON") from exc
        manifest, legacy = parse_manifest(payload)

        dump_fd = _open_regular(root_fd, dump_leaf)
        try:
            dump_before = os.fstat(dump_fd)
            actual_size, actual_hash = _hash_file(dump_fd)
            dump_after = os.fstat(dump_fd)
        finally:
            os.close(dump_fd)
    finally:
        os.close(root_fd)

    if _stable_identity(dump_before) != _stable_identity(dump_after):
        raise ValueError("backup dump changed while being read")
    if manifest.file != dump_leaf:
        raise ValueError("manifest points to a different backup dump")
    if manifest.size_bytes != actual_size:
        raise ValueError("backup dump size does not match manifest")
    if manifest.sha256 != actual_hash:
        raise ValueError("backup dump hash does not match manifest")
    return manifest, legacy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--created-at-utc", required=True)
    create.add_argument("--database", required=True)
    create.add_argument("--postgres-version", required=True)
    create.add_argument("--file", required=True)
    create.add_argument("--size-bytes", required=True, type=int)
    create.add_argument("--sha256", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("dump", type=Path)
    verify.add_argument("manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "create":
        manifest = build_manifest(
            created_at_utc=args.created_at_utc,
            database=args.database,
            postgres_version=args.postgres_version,
            file_name=args.file,
            size_bytes=args.size_bytes,
            sha256=args.sha256,
        )
        os.write(1, canonical_manifest_bytes(manifest))
        return 0

    manifest, legacy = verify_backup_pair(args.dump, args.manifest)
    print("PASS postgres_backup_manifest")
    print(f"backup_id={manifest.backup_id}")
    print(f"legacy_adapter={'YES' if legacy else 'NO'}")
    print(f"size_bytes={manifest.size_bytes}")
    print(f"sha256_prefix={manifest.sha256[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
