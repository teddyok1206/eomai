#!/usr/bin/env python3
"""Verify one disposable database restore against one immutable Artifact snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url


def _load_backup_contract() -> Any:
    path = Path(__file__).resolve().with_name("postgres_backup_contract.py")
    spec = importlib.util.spec_from_file_location("_eom_postgres_backup_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PostgreSQL backup contract loader is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


postgres_backup_contract = _load_backup_contract()

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCHEMA = ROOT / "schemas/infra/artifact-store-snapshot-manifest-v1.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas/infra/recovery-validation-receipt-v1.schema.json"
LIVE_ARTIFACT_ROOT = Path("/mnt/nas/eom/artifacts")
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
ARTIFACT_PATTERN = re.compile(r"^artifact_[0-9a-f]{32}$")
REVISION_PATTERN = re.compile(r"^rev_[0-9a-f]{32}$")
SAFE_DATABASE_PATTERN = re.compile(r"^eom_(?:restore|test)_[a-z0-9_]{1,63}$")


def _load_schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"schema is not an object: {path.name}")
    Draft202012Validator.check_schema(value)
    return value


class ArtifactStoreSnapshotManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["artifact-store-snapshot-manifest/1.0"]
    snapshot_id: str = Field(pattern=r"^artifactsnapshot_[0-9a-f]{32}$")
    captured_at: datetime
    artifact_root_label: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    artifact_revision_count: int = Field(ge=0)
    inventory_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_self_hash(self) -> ArtifactStoreSnapshotManifestV1:
        if self.captured_at.utcoffset() != UTC.utcoffset(self.captured_at):
            raise ValueError("Artifact snapshot captured_at must be UTC")
        body = self.model_dump(mode="json", exclude={"snapshot_id", "snapshot_sha256"})
        expected = content_sha256(body)
        if self.snapshot_sha256 != expected or self.snapshot_id != (
            "artifactsnapshot_" + expected.removeprefix("sha256:")[:32]
        ):
            raise ValueError("Artifact snapshot identity does not match canonical content")
        return self


class RecoveryRevisionReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_type: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    primary_file: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_primary_member_path(self) -> RecoveryRevisionReceiptV1:
        if _safe_member_path(self.primary_file).as_posix() != self.primary_file:
            raise ValueError("recovery receipt primary file is not a safe member path")
        return self

    member_count: int = Field(ge=1, le=100_000)


class RecoveryValidationReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["recovery-validation-receipt/1.0"]
    verification_mode: Literal["SAMPLED", "FULL"]
    database_backup_id: str = Field(pattern=r"^pgbackup_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}$")
    database_backup_created_at: datetime
    database_backup_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    database_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    database_inventory_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_snapshot_id: str = Field(pattern=r"^artifactsnapshot_[0-9a-f]{32}$")
    artifact_snapshot_captured_at: datetime
    artifact_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_inventory_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    restored_database_identity: str = Field(pattern=r"^(eom_restore|eom_test)_[a-z0-9_]{1,63}$")
    artifact_revision_count: int = Field(ge=0)
    verified_revision_count: int = Field(ge=0)
    verified_member_count: int = Field(ge=0)
    evidence_revision_count: int = Field(ge=0, le=10_000)
    evidence_member_count: int = Field(ge=0)
    evidence_revisions: tuple[RecoveryRevisionReceiptV1, ...] = Field(max_length=10_000)
    validated_at: datetime
    receipt_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_receipt(self) -> RecoveryValidationReceiptV1:
        timestamps = (
            self.database_backup_created_at,
            self.artifact_snapshot_captured_at,
            self.validated_at,
        )
        if any(value.utcoffset() != UTC.utcoffset(value) for value in timestamps):
            raise ValueError("recovery receipt timestamps must be UTC")
        expected_backup_id = (
            "pgbackup_"
            + self.database_backup_created_at.strftime("%Y%m%dT%H%M%SZ")
            + "_"
            + self.database_backup_sha256.removeprefix("sha256:")[:12]
        )
        if self.database_backup_id != expected_backup_id:
            raise ValueError("recovery receipt backup identity is inconsistent")
        if self.database_inventory_sha256 != self.artifact_inventory_sha256:
            raise ValueError("database and Artifact snapshot inventories do not match")
        if self.evidence_revision_count != len(self.evidence_revisions) or (
            self.evidence_member_count != sum(row.member_count for row in self.evidence_revisions)
        ):
            raise ValueError("recovery receipt counts do not match evidence revisions")
        if self.evidence_revision_count > self.verified_revision_count:
            raise ValueError("recovery evidence exceeds the verified revision set")
        if self.verification_mode == "SAMPLED" and (
            self.verified_revision_count != self.evidence_revision_count
            or self.verified_member_count != self.evidence_member_count
        ):
            raise ValueError("sampled recovery counts must equal their evidence set")
        if self.verification_mode == "FULL" and (
            self.verified_revision_count != self.artifact_revision_count
            or self.verified_member_count < self.evidence_member_count
        ):
            raise ValueError("full recovery verification must cover every Artifact revision")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("recovery receipt hash does not match canonical content")
        return self


def _safe_snapshot_root(root: Path) -> Path:
    if not root.is_absolute():
        raise ValueError("Artifact snapshot root must be absolute")
    metadata = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Artifact snapshot root must be a non-symlink directory")
    resolved = root.resolve(strict=True)
    live_root = LIVE_ARTIFACT_ROOT.resolve(strict=False)
    if (
        resolved == live_root
        or resolved.is_relative_to(live_root)
        or live_root.is_relative_to(resolved)
    ):
        raise ValueError(
            "live Artifact storage, its descendants, and its ancestors cannot be used as a "
            "recovery snapshot"
        )
    return resolved


def _regular_file_bytes(path: Path, maximum: int) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError(f"unsafe recovery file: {path.name}")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("recovery file identity changed before open")
        data = bytearray()
        while chunk := os.read(descriptor, min(65536, maximum + 1 - len(data))):
            data.extend(chunk)
            if len(data) > maximum:
                raise ValueError("recovery file exceeds its bounded size")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if identity(opened) != identity(after):
        raise ValueError("recovery file changed while being read")
    return bytes(data)


def _manifest_value(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_regular_file_bytes(path, MAX_MANIFEST_BYTES).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Artifact manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Artifact manifest must be an object")
    return value


def _snapshot_inventory(root: Path) -> tuple[int, str]:
    entries: list[dict[str, str]] = []
    for artifact_dir in sorted(root.iterdir(), key=lambda value: value.name):
        if artifact_dir.name == "snapshot-manifest.json":
            continue
        metadata = artifact_dir.lstat()
        if (
            not ARTIFACT_PATTERN.fullmatch(artifact_dir.name)
            or artifact_dir.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise ValueError("Artifact snapshot contains an unexpected root member")
        for revision_dir in sorted(artifact_dir.iterdir(), key=lambda value: value.name):
            revision_metadata = revision_dir.lstat()
            if (
                not REVISION_PATTERN.fullmatch(revision_dir.name)
                or revision_dir.is_symlink()
                or not stat.S_ISDIR(revision_metadata.st_mode)
            ):
                raise ValueError("Artifact snapshot contains an unexpected revision member")
            manifest = _manifest_value(revision_dir / "manifest.json")
            _validate_revision_layout(revision_dir, manifest)
            entries.append(
                {
                    "artifact_id": artifact_dir.name,
                    "artifact_revision_id": revision_dir.name,
                    "manifest_sha256": content_sha256(manifest),
                }
            )
    return len(entries), content_sha256(entries)


def build_snapshot_manifest(
    root: Path,
    *,
    captured_at: datetime,
    artifact_root_label: str,
) -> ArtifactStoreSnapshotManifestV1:
    resolved = _safe_snapshot_root(root)
    count, inventory_sha256 = _snapshot_inventory(resolved)
    body = {
        "schema_version": "artifact-store-snapshot-manifest/1.0",
        "captured_at": captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "artifact_root_label": artifact_root_label,
        "artifact_revision_count": count,
        "inventory_sha256": inventory_sha256,
    }
    snapshot_sha256 = content_sha256(body)
    value = ArtifactStoreSnapshotManifestV1.model_validate(
        body
        | {
            "snapshot_id": "artifactsnapshot_" + snapshot_sha256.removeprefix("sha256:")[:32],
            "snapshot_sha256": snapshot_sha256,
        }
    )
    Draft202012Validator(_load_schema(SNAPSHOT_SCHEMA)).validate(value.model_dump(mode="json"))
    return value


def load_snapshot_manifest(path: Path) -> ArtifactStoreSnapshotManifestV1:
    value = json.loads(_regular_file_bytes(path, 64 * 1024).decode("utf-8"))
    Draft202012Validator(_load_schema(SNAPSHOT_SCHEMA)).validate(value)
    return ArtifactStoreSnapshotManifestV1.model_validate(value)


def _safe_member_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("Artifact member path is not a string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or value == "manifest.json"
    ):
        raise ValueError("Artifact member path is unsafe")
    return path


def _members(manifest: Mapping[str, Any]) -> tuple[tuple[PurePosixPath, int, str], ...]:
    raw_members = manifest.get("files", manifest.get("members"))
    if isinstance(raw_members, list):
        result: list[tuple[PurePosixPath, int, str]] = []
        seen: set[str] = set()
        for raw in raw_members:
            if not isinstance(raw, Mapping):
                raise ValueError("Artifact member descriptor is invalid")
            path = _safe_member_path(raw.get("file_name", raw.get("member_path")))
            size = raw.get("bytes")
            digest = raw.get("sha256")
            if (
                path.as_posix() in seen
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("Artifact member descriptor is invalid")
            seen.add(path.as_posix())
            result.append((path, size, digest))
        if not result:
            raise ValueError("Artifact manifest has no members")
        return tuple(result)
    path = _safe_member_path(manifest.get("file_name"))
    size = manifest.get("content_bytes")
    digest = manifest.get("content_hash")
    if (
        not isinstance(size, int)
        or size < 1
        or not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("legacy Artifact manifest member is invalid")
    return ((path, size, digest),)


def _primary_file(manifest: Mapping[str, Any]) -> str:
    value = manifest.get("primary_file", manifest.get("file_name"))
    return _safe_member_path(value).as_posix()


def _revision_file_inventory(revision_root: Path) -> set[str]:
    found: set[str] = set()

    def visit(directory: Path, prefix: PurePosixPath) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                relative = prefix / entry.name
                if entry.is_symlink():
                    raise ValueError("Artifact revision contains a symlink")
                if stat.S_ISDIR(metadata.st_mode):
                    visit(Path(entry.path), relative)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    found.add(relative.as_posix())
                else:
                    raise ValueError("Artifact revision contains an unsafe member")

    visit(revision_root, PurePosixPath())
    return found


def _validate_revision_layout(revision_root: Path, manifest: Mapping[str, Any]) -> None:
    expected = {"manifest.json"} | {path.as_posix() for path, _size, _sha256 in _members(manifest)}
    if _revision_file_inventory(revision_root) != expected:
        raise ValueError("Artifact revision members differ from its manifest")


def _open_regular_member(revision_root: Path, member_path: PurePosixPath) -> int:
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    descriptor = os.open(revision_root, directory_flags)
    try:
        for part in member_path.parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        member_descriptor = os.open(member_path.name, file_flags, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    return member_descriptor


def _hash_regular_member(
    revision_root: Path,
    member_path: PurePosixPath,
    expected_size: int,
) -> str:
    descriptor = _open_regular_member(revision_root, member_path)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != expected_size
        ):
            raise ValueError("Artifact member identity does not match its manifest")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, HASH_CHUNK_BYTES):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("Artifact member changed while being read")
    return "sha256:" + digest.hexdigest()


REVISION_QUERY = (
    "SELECT r.revision_id, r.logical_artifact_id, r.content_hash, r.manifest_hash, "
    "r.content_bytes, r.nas_path, r.manifest, a.artifact_type "
    "FROM artifact_revisions r JOIN artifacts a "
    "ON a.logical_artifact_id = r.logical_artifact_id "
)


def _selected_rows(connection: Any, count: int, sample_size: int) -> tuple[Any, ...]:
    if count == 0 or sample_size == 0:
        return ()
    half = (min(count, sample_size) + 1) // 2
    rows_by_id: dict[str, Any] = {}
    for direction in ("ASC", "DESC"):
        statement = text(REVISION_QUERY + f"ORDER BY r.revision_id {direction} LIMIT :limit")
        for row in connection.execute(statement, {"limit": half}):
            rows_by_id[row.revision_id] = row
    return tuple(rows_by_id[key] for key in sorted(rows_by_id))[:sample_size]


def _all_rows(connection: Any) -> tuple[Any, ...]:
    return tuple(connection.execute(text(REVISION_QUERY + "ORDER BY r.revision_id ASC")))


def _database_inventory(connection: Any) -> tuple[int, str]:
    entries: list[dict[str, str]] = []
    rows = connection.execute(
        text(
            "SELECT logical_artifact_id, revision_id, manifest_hash "
            "FROM artifact_revisions ORDER BY logical_artifact_id, revision_id"
        )
    )
    for row in rows:
        if (
            ARTIFACT_PATTERN.fullmatch(row.logical_artifact_id) is None
            or REVISION_PATTERN.fullmatch(row.revision_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", row.manifest_hash) is None
        ):
            raise ValueError("restored Artifact inventory identity is invalid")
        entries.append(
            {
                "artifact_id": row.logical_artifact_id,
                "artifact_revision_id": row.revision_id,
                "manifest_sha256": row.manifest_hash,
            }
        )
    return len(entries), content_sha256(entries)


def verify_recovery_pair(
    *,
    database_url: str,
    backup_dump: Path,
    backup_manifest: Path,
    snapshot_root: Path,
    snapshot_manifest_path: Path,
    sample_size: int,
    full: bool = False,
    validated_at: datetime | None = None,
) -> RecoveryValidationReceiptV1:
    database_name = make_url(database_url).database or ""
    if SAFE_DATABASE_PATTERN.fullmatch(database_name) is None:
        raise ValueError("recovery validation requires an eom_restore_* or eom_test_* database")
    backup, _legacy = postgres_backup_contract.verify_backup_pair(backup_dump, backup_manifest)
    resolved_root = _safe_snapshot_root(snapshot_root)
    if (
        snapshot_manifest_path.name != "snapshot-manifest.json"
        or snapshot_manifest_path.parent.resolve(strict=True) != resolved_root
    ):
        raise ValueError("Artifact snapshot manifest must be the fixed member of its snapshot root")
    snapshot = load_snapshot_manifest(snapshot_manifest_path)
    actual_count, inventory_sha256 = _snapshot_inventory(resolved_root)
    if (
        actual_count != snapshot.artifact_revision_count
        or inventory_sha256 != snapshot.inventory_sha256
    ):
        raise ValueError("Artifact snapshot inventory differs from its immutable manifest")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            restored_name = connection.scalar(select(func.current_database()))
            if restored_name != database_name:
                raise ValueError("connected database identity changed")
            database_count, database_inventory_sha256 = _database_inventory(connection)
            if (
                database_count != snapshot.artifact_revision_count
                or database_inventory_sha256 != snapshot.inventory_sha256
            ):
                raise ValueError("database and Artifact snapshot inventories differ")
            evidence_rows = _selected_rows(connection, database_count, sample_size)
            rows = _all_rows(connection) if full else evidence_rows
    finally:
        engine.dispose()

    evidence_ids = {row.revision_id for row in evidence_rows}
    evidence: list[RecoveryRevisionReceiptV1] = []
    verified_member_count = 0
    for row in rows:
        manifest = row.manifest
        if not isinstance(manifest, dict):
            raise ValueError("restored Artifact manifest is not an object")
        if content_sha256(manifest) != row.manifest_hash:
            raise ValueError("restored Artifact manifest hash is invalid")
        if (
            manifest.get("logical_artifact_id") != row.logical_artifact_id
            or manifest.get("revision_id") != row.revision_id
        ):
            raise ValueError("restored Artifact manifest identity is invalid")
        expected_suffix = Path(row.logical_artifact_id) / row.revision_id
        if Path(row.nas_path).parts[-2:] != expected_suffix.parts:
            raise ValueError("restored Artifact storage path does not match its identity")
        revision_root = resolved_root / expected_suffix
        disk_manifest = _manifest_value(revision_root / "manifest.json")
        if disk_manifest != manifest:
            raise ValueError("Artifact snapshot manifest differs from restored metadata")
        members = _members(manifest)
        primary_file = _primary_file(manifest)
        if primary_file not in {path.as_posix() for path, _, _ in members}:
            raise ValueError("Artifact primary file is absent from its member set")
        for member_path, expected_size, expected_sha256 in members:
            actual_sha256 = _hash_regular_member(revision_root, member_path, expected_size)
            if actual_sha256 != expected_sha256:
                raise ValueError("Artifact member hash does not match its manifest")
        verified_member_count += len(members)
        primary = next(row for row in members if row[0].as_posix() == primary_file)
        if primary[2] != row.content_hash or primary[1] != row.content_bytes:
            raise ValueError("restored Artifact primary content identity is invalid")
        if row.revision_id in evidence_ids:
            evidence.append(
                RecoveryRevisionReceiptV1(
                    artifact_id=row.logical_artifact_id,
                    artifact_revision_id=row.revision_id,
                    artifact_type=row.artifact_type,
                    content_sha256=row.content_hash,
                    manifest_sha256=row.manifest_hash,
                    primary_file=primary_file,
                    member_count=len(members),
                )
            )

    backup_manifest_sha256 = sha256_bytes(_regular_file_bytes(backup_manifest, 64 * 1024))
    backup_created_at = datetime.strptime(backup.created_at_utc, "%Y%m%dT%H%M%SZ").replace(
        tzinfo=UTC
    )
    body: dict[str, Any] = {
        "schema_version": "recovery-validation-receipt/1.0",
        "verification_mode": "FULL" if full else "SAMPLED",
        "database_backup_id": backup.backup_id,
        "database_backup_created_at": backup_created_at.isoformat().replace("+00:00", "Z"),
        "database_backup_sha256": "sha256:" + backup.sha256,
        "database_manifest_sha256": backup_manifest_sha256,
        "database_inventory_sha256": database_inventory_sha256,
        "artifact_snapshot_id": snapshot.snapshot_id,
        "artifact_snapshot_captured_at": snapshot.captured_at.isoformat().replace("+00:00", "Z"),
        "artifact_snapshot_sha256": snapshot.snapshot_sha256,
        "artifact_inventory_sha256": snapshot.inventory_sha256,
        "restored_database_identity": database_name,
        "artifact_revision_count": database_count,
        "verified_revision_count": len(rows),
        "verified_member_count": verified_member_count,
        "evidence_revision_count": len(evidence),
        "evidence_member_count": sum(row.member_count for row in evidence),
        "evidence_revisions": [row.model_dump(mode="json") for row in evidence],
        "validated_at": (validated_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    body["receipt_sha256"] = content_sha256(body)
    Draft202012Validator(_load_schema(RECEIPT_SCHEMA)).validate(body)
    return RecoveryValidationReceiptV1.model_validate(body)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot-manifest")
    snapshot.add_argument("snapshot_root", type=Path)
    snapshot.add_argument("--captured-at", required=True)
    snapshot.add_argument("--label", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup-dump", required=True, type=Path)
    verify.add_argument("--backup-manifest", required=True, type=Path)
    verify.add_argument("--snapshot-root", required=True, type=Path)
    verify.add_argument("--snapshot-manifest", required=True, type=Path)
    verify.add_argument("--database-url-env", default="EOM_RECOVERY_DATABASE_URL")
    verify.add_argument("--sample-size", type=int, default=64, choices=range(1, 10_001))
    verify.add_argument(
        "--full",
        action="store_true",
        help="verify bytes for every restored Artifact revision instead of a bounded sample",
    )
    return parser


def _canonical_output(value: BaseModel) -> str:
    return canonical_json_bytes(value.model_dump(mode="json")).decode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "snapshot-manifest":
        captured_at = datetime.fromisoformat(args.captured_at.replace("Z", "+00:00"))
        if captured_at.tzinfo is None:
            raise ValueError("captured-at must include a UTC offset")
        print(
            _canonical_output(
                build_snapshot_manifest(
                    args.snapshot_root,
                    captured_at=captured_at,
                    artifact_root_label=args.label,
                )
            )
        )
        return 0
    database_url = os.environ.get(args.database_url_env)
    if database_url is None:
        raise ValueError(f"database URL environment variable is absent: {args.database_url_env}")
    receipt = verify_recovery_pair(
        database_url=database_url,
        backup_dump=args.backup_dump,
        backup_manifest=args.backup_manifest,
        snapshot_root=args.snapshot_root,
        snapshot_manifest_path=args.snapshot_manifest,
        sample_size=args.sample_size,
        full=args.full,
    )
    print(_canonical_output(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
