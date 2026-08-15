"""Validated local staging and immutable NAS revision commit."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eom_identifiers import canonical_json_bytes, sha256_bytes, sha256_file
from eom_protocol import ArtifactManifest, ErrorCode, WorkerResult, validate_message

from eom_orchestrator.errors import PlatformError


@dataclass(frozen=True)
class StagedArtifact:
    directory: Path
    result_path: Path
    manifest_path: Path
    manifest: ArtifactManifest
    content_hash: str
    manifest_hash: str


def stage_artifact(
    *, result: WorkerResult, staging: Path, worker_slot: str, created_at: datetime | None = None
) -> StagedArtifact:
    staging.mkdir(mode=0o750, parents=True, exist_ok=True)
    result_bytes = canonical_json_bytes(result)
    result_path = staging / "result.json"
    result_temp = staging / ".result.json.tmp"
    result_temp.write_bytes(result_bytes)
    result_temp.replace(result_path)
    content_hash = sha256_bytes(result_bytes)
    manifest = ArtifactManifest(
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        content_bytes=len(result_bytes),
        worker_slot=worker_slot,
        created_at=created_at or datetime.now(UTC),
    )
    manifest_data = manifest.model_dump(mode="json")
    validate_message("artifact-manifest", manifest_data)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path = staging / "manifest.json"
    manifest_temp = staging / ".manifest.json.tmp"
    manifest_temp.write_bytes(manifest_bytes)
    manifest_temp.replace(manifest_path)
    return StagedArtifact(
        directory=staging,
        result_path=result_path,
        manifest_path=manifest_path,
        manifest=manifest,
        content_hash=content_hash,
        manifest_hash=sha256_bytes(manifest_bytes),
    )


def commit_artifact(staged: StagedArtifact, nas_root: Path) -> Path:
    if not nas_root.is_dir():
        raise PlatformError(ErrorCode.NAS_UNAVAILABLE, "NAS artifact root is unavailable")
    try:
        resolved_root = nas_root.resolve(strict=True)
    except OSError as exc:
        raise PlatformError(ErrorCode.NAS_UNAVAILABLE, "NAS artifact root is unavailable") from exc
    logical_dir = nas_root / staged.manifest.logical_artifact_id
    final = logical_dir / staged.manifest.revision_id
    if logical_dir.is_symlink() or (logical_dir.exists() and not logical_dir.is_dir()):
        raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid logical artifact path")
    logical_dir.mkdir(mode=0o755, exist_ok=True)
    if logical_dir.resolve().parent != resolved_root:
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED, "logical artifact path escaped NAS root"
        )
    if final.exists():
        if final.is_symlink() or not final.is_dir():
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid artifact revision path")
        _verify_final(staged, final)
        return final

    temporary = logical_dir / f".{staged.manifest.revision_id}.tmp-{uuid4().hex}"
    try:
        temporary.mkdir(mode=0o750)
        shutil.copyfile(staged.result_path, temporary / "result.json")
        shutil.copyfile(staged.manifest_path, temporary / "manifest.json")
        _verify_final(staged, temporary)
        _fsync_file(temporary / "result.json")
        _fsync_file(temporary / "manifest.json")
        os.replace(temporary, final)
    except PlatformError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "NAS artifact commit failed") from exc
    return final


def _verify_final(staged: StagedArtifact, directory: Path) -> None:
    if sha256_file(directory / "result.json") != staged.content_hash:
        raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "result checksum mismatch")
    if sha256_file(directory / "manifest.json") != staged.manifest_hash:
        raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "manifest checksum mismatch")


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
