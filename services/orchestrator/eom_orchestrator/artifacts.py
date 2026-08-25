"""Validated local staging and immutable NAS revision commit."""

from __future__ import annotations

import os
import shutil
import stat
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


@dataclass(frozen=True)
class StagedFile:
    relative_path: str
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class StagedFileSet:
    directory: Path
    manifest_path: Path
    manifest: dict[str, object]
    files: tuple[StagedFile, ...]
    primary_hash: str
    primary_bytes: int
    manifest_hash: str
    logical_artifact_id: str
    revision_id: str


def stage_artifact(
    *, result: WorkerResult, staging: Path, worker_slot: str, created_at: datetime | None = None
) -> StagedArtifact:
    return stage_structured_artifact(
        result=result.model_dump(mode="json"),
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        staging=staging,
        worker_slot=worker_slot,
        created_at=created_at,
    )


def stage_structured_artifact(
    *,
    result: dict[str, object],
    job_id: str,
    logical_artifact_id: str,
    revision_id: str,
    staging: Path,
    worker_slot: str,
    created_at: datetime | None = None,
) -> StagedArtifact:
    staging.mkdir(mode=0o750, parents=True, exist_ok=True)
    result_bytes = canonical_json_bytes(result)
    result_path = staging / "result.json"
    result_temp = staging / ".result.json.tmp"
    result_temp.write_bytes(result_bytes)
    result_temp.replace(result_path)
    content_hash = sha256_bytes(result_bytes)
    manifest = ArtifactManifest(
        job_id=job_id,
        logical_artifact_id=logical_artifact_id,
        revision_id=revision_id,
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
    resolved_root = _resolve_nas_root(nas_root)
    logical_dir = nas_root / staged.manifest.logical_artifact_id
    final = logical_dir / staged.manifest.revision_id
    temporary: Path | None = None
    try:
        if logical_dir.is_symlink() or (logical_dir.exists() and not logical_dir.is_dir()):
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid logical artifact path")
        logical_dir.mkdir(mode=0o755, exist_ok=True)
        if logical_dir.resolve().parent != resolved_root:
            raise PlatformError(
                ErrorCode.ARTIFACT_COMMIT_FAILED, "logical artifact path escaped NAS root"
            )
        if final.is_symlink() or (final.exists() and not final.is_dir()):
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid artifact revision path")
        if final.exists():
            _verify_final(staged, final)
            return final

        temporary = logical_dir / f".{staged.manifest.revision_id}.tmp-{uuid4().hex}"
        temporary.mkdir(mode=0o750)
        shutil.copyfile(staged.result_path, temporary / "result.json")
        shutil.copyfile(staged.manifest_path, temporary / "manifest.json")
        _verify_final(staged, temporary)
        _fsync_file(temporary / "result.json")
        _fsync_file(temporary / "manifest.json")
        os.replace(temporary, final)
    except PlatformError:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    except OSError as exc:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "NAS artifact commit failed") from exc
    return final


def stage_file_set_artifact(
    *,
    files: dict[str, Path],
    primary_file: str,
    job_id: str,
    logical_artifact_id: str,
    revision_id: str,
    artifact_type: str,
    staging: Path,
    created_at: datetime | None = None,
    manifest_version: str = "hwpx-file-set/1.0",
    file_metadata: dict[str, dict[str, str]] | None = None,
) -> StagedFileSet:
    if primary_file not in files or not files:
        raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "primary artifact file is missing")
    if file_metadata is not None and (
        set(file_metadata) != set(files)
        or any(
            set(metadata) != {"schema_ref", "media_type"}
            or not all(isinstance(value, str) and value for value in metadata.values())
            for metadata in file_metadata.values()
        )
    ):
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "artifact member metadata does not match staged files",
        )
    staging.mkdir(mode=0o750, parents=True, exist_ok=True)
    staged_files: list[StagedFile] = []
    for relative_path, source in sorted(files.items()):
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in relative_path
            or relative_path in {"manifest.json", ""}
        ):
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "unsafe artifact file name")
        try:
            source_stat = source.lstat()
        except OSError as exc:
            raise PlatformError(
                ErrorCode.ARTIFACT_COMMIT_FAILED, "artifact source is missing"
            ) from exc
        if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "artifact source is not regular")
        target = staging / relative
        target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o640)
        staged_files.append(
            StagedFile(
                relative_path=relative.as_posix(),
                path=target,
                sha256=sha256_file(target),
                size=target.stat().st_size,
            )
        )
    primary = next(item for item in staged_files if item.relative_path == primary_file)
    manifest: dict[str, object] = {
        "manifest_version": manifest_version,
        "job_id": job_id,
        "logical_artifact_id": logical_artifact_id,
        "revision_id": revision_id,
        "artifact_type": artifact_type,
        "primary_file": primary_file,
        "content_hash": primary.sha256,
        "content_bytes": primary.size,
        "files": [
            {
                "file_name": item.relative_path,
                "sha256": item.sha256,
                "bytes": item.size,
                **((file_metadata or {}).get(item.relative_path, {})),
            }
            for item in staged_files
        ],
        "created_at": (created_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    manifest_path = staging / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o640)
    return StagedFileSet(
        directory=staging,
        manifest_path=manifest_path,
        manifest=manifest,
        files=tuple(staged_files),
        primary_hash=primary.sha256,
        primary_bytes=primary.size,
        manifest_hash=sha256_file(manifest_path),
        logical_artifact_id=logical_artifact_id,
        revision_id=revision_id,
    )


def commit_file_set_artifact(staged: StagedFileSet, nas_root: Path) -> Path:
    resolved_root = _resolve_nas_root(nas_root)
    logical_dir = nas_root / staged.logical_artifact_id
    final = logical_dir / staged.revision_id
    temporary: Path | None = None
    try:
        if logical_dir.is_symlink() or (logical_dir.exists() and not logical_dir.is_dir()):
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid logical artifact path")
        logical_dir.mkdir(mode=0o755, exist_ok=True)
        if logical_dir.resolve().parent != resolved_root:
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "artifact path escaped NAS root")
        if final.is_symlink() or (final.exists() and not final.is_dir()):
            raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "invalid artifact revision path")
        if final.exists():
            _verify_file_set(staged, final)
            return final
        temporary = logical_dir / f".{staged.revision_id}.tmp-{uuid4().hex}"
        temporary.mkdir(mode=0o750)
        for item in staged.files:
            target = temporary / item.relative_path
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            shutil.copyfile(item.path, target)
        shutil.copyfile(staged.manifest_path, temporary / "manifest.json")
        _verify_file_set(staged, temporary)
        for item in staged.files:
            _fsync_file(temporary / item.relative_path)
        _fsync_file(temporary / "manifest.json")
        os.replace(temporary, final)
    except PlatformError:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    except OSError as exc:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        raise PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "NAS artifact commit failed") from exc
    return final


def _resolve_nas_root(nas_root: Path) -> Path:
    if not nas_root.is_dir():
        raise PlatformError(ErrorCode.NAS_UNAVAILABLE, "NAS artifact root is unavailable")
    try:
        return nas_root.resolve(strict=True)
    except OSError as exc:
        raise PlatformError(ErrorCode.NAS_UNAVAILABLE, "NAS artifact root is unavailable") from exc


def _verify_final(staged: StagedArtifact, directory: Path) -> None:
    if sha256_file(directory / "result.json") != staged.content_hash:
        raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "result checksum mismatch")
    if sha256_file(directory / "manifest.json") != staged.manifest_hash:
        raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "manifest checksum mismatch")


def _verify_file_set(staged: StagedFileSet, directory: Path) -> None:
    for item in staged.files:
        target = directory / item.relative_path
        if not target.is_file() or target.is_symlink() or sha256_file(target) != item.sha256:
            raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "artifact file checksum mismatch")
    manifest = directory / "manifest.json"
    if not manifest.is_file() or sha256_file(manifest) != staged.manifest_hash:
        raise PlatformError(ErrorCode.ARTIFACT_HASH_MISMATCH, "manifest checksum mismatch")


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
