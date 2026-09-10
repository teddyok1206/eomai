"""Read-only resolution of one immutable Artifact member inside a caller-owned DB snapshot."""

from __future__ import annotations

import os
import stat
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from eom_identifiers import content_sha256, sha256_bytes, sha256_file
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy.orm import Session

from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True)
class PinnedArtifactMember:
    """Validated Artifact provenance plus the exact immutable member bytes."""

    artifact_id: str
    artifact_revision_id: str
    member_path: str
    schema_ref: str
    media_type: str
    sha256: str
    artifact_type: str
    manifest_artifact_type: str
    approved: Literal[True]
    producing_job_state: Literal["SUCCEEDED"]
    payload: bytes


class PinnedArtifactResolutionError(ValueError):
    """The pinned Artifact identity, provenance, manifest, or bytes did not resolve."""


def resolve_pinned_artifact_member(
    session: Session,
    settings: CatalogSettings,
    *,
    artifact_id: str,
    artifact_revision_id: str,
    member_path: str,
    sha256: str,
    schema_ref: str,
    media_type: str,
    expected_artifact_types: Collection[str],
    expected_primary_file: str,
    max_bytes: int,
    expected_manifest_artifact_types: Collection[str] | None = None,
    historical_metadata_compatibility: bool = False,
    allow_empty: bool = False,
) -> PinnedArtifactMember:
    """Resolve one member without opening a second database transaction.

    Historical Item Revision manifests were committed before member schema/media metadata was
    persisted.  The compatibility mode is deliberately narrow: both metadata keys must be absent,
    the Artifact type and primary member must be ``item-revision-manifest`` and
    ``item-revision-manifest.json``, and the caller still schema-validates the returned bytes.
    """

    relative = PurePosixPath(member_path)
    manifest_artifact_types = (
        expected_artifact_types
        if expected_manifest_artifact_types is None
        else expected_manifest_artifact_types
    )
    if (
        relative.is_absolute()
        or relative.as_posix() != member_path
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in member_path
        or max_bytes < 1
        or type(allow_empty) is not bool
        or not expected_artifact_types
        or not manifest_artifact_types
    ):
        raise PinnedArtifactResolutionError("pinned Artifact member request is invalid")

    logical = session.get(ArtifactRecord, artifact_id)
    revision = session.get(ArtifactRevisionRecord, artifact_revision_id)
    job = session.get(JobRecord, revision.job_id) if revision is not None else None
    if (
        logical is None
        or revision is None
        or job is None
        or not logical.approved
        or not revision.approved
        or logical.artifact_type not in expected_artifact_types
        or revision.logical_artifact_id != logical.logical_artifact_id
        or logical.logical_artifact_id != artifact_id
        or logical.job_id != revision.job_id
        or revision.job_id != job.job_id
        or job.status != "SUCCEEDED"
        or job.task_type != logical.artifact_type
        or job.logical_artifact_id != artifact_id
        or job.revision_id != artifact_revision_id
    ):
        raise PinnedArtifactResolutionError("pinned Artifact provenance does not resolve")

    manifest = revision.manifest
    files = manifest.get("files")
    if not isinstance(files, list):
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve")
    entries = tuple(value for value in files if isinstance(value, dict))
    matches = tuple(value for value in entries if value.get("file_name") == member_path)
    try:
        manifest_hash = content_sha256(manifest)
    except (TypeError, ValueError) as exc:
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve") from exc
    if (
        manifest.get("logical_artifact_id") != artifact_id
        or manifest.get("revision_id") != artifact_revision_id
        or manifest.get("job_id") != job.job_id
        or manifest.get("artifact_type") not in manifest_artifact_types
        or manifest.get("primary_file") != expected_primary_file
        or manifest_hash != revision.manifest_hash
        or len(entries) != len(files)
        or len(matches) != 1
    ):
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve")
    entry = matches[0]
    size = entry.get("bytes")
    metadata_matches = (
        entry.get("schema_ref") == schema_ref and entry.get("media_type") == media_type
    )
    historical_contract = (
        historical_metadata_compatibility
        and logical.artifact_type == "item-revision-manifest"
        and expected_primary_file == "item-revision-manifest.json"
        and member_path == "item-revision-manifest.json"
        and "schema_ref" not in entry
        and "media_type" not in entry
    )
    if (
        entry.get("sha256") != sha256
        or type(size) is not int
        or size < 0
        or (size == 0 and (not allow_empty or member_path == expected_primary_file))
        or size > max_bytes
        or not (metadata_matches or historical_contract)
        or (member_path == expected_primary_file and revision.content_hash != sha256)
        or (member_path == expected_primary_file and revision.content_bytes != size)
    ):
        raise PinnedArtifactResolutionError("pinned Artifact member descriptor differs")

    try:
        storage_root = settings.nas_artifact_root.resolve(strict=True)
        raw_root = Path(revision.nas_path)
        raw_metadata = raw_root.lstat()
        if raw_root.is_symlink() or not stat.S_ISDIR(raw_metadata.st_mode):
            raise PinnedArtifactResolutionError("pinned Artifact root is invalid")
        artifact_root = raw_root.resolve(strict=True)
        if not artifact_root.is_relative_to(storage_root):
            raise PinnedArtifactResolutionError("pinned Artifact escaped storage root")
        candidate = artifact_root.joinpath(*relative.parts)
        target = candidate.resolve(strict=True)
        metadata = target.lstat()
        if (
            target != candidate
            or not target.is_relative_to(artifact_root)
            or target.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != size
            or sha256_file(target) != sha256
        ):
            raise PinnedArtifactResolutionError("pinned Artifact materialization differs")

        descriptor = os.open(
            target,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = size + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            closed = os.fstat(descriptor)
            if (
                len(payload) != size
                or sha256_bytes(payload) != sha256
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size)
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (closed.st_dev, closed.st_ino, closed.st_size)
            ):
                raise PinnedArtifactResolutionError("pinned Artifact changed while reading")
        finally:
            os.close(descriptor)
    except PinnedArtifactResolutionError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise PinnedArtifactResolutionError(
            "pinned Artifact materialization does not resolve"
        ) from exc

    return PinnedArtifactMember(
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path=member_path,
        schema_ref=schema_ref,
        media_type=media_type,
        sha256=sha256,
        artifact_type=logical.artifact_type,
        manifest_artifact_type=manifest["artifact_type"],
        approved=True,
        producing_job_state="SUCCEEDED",
        payload=payload,
    )


__all__ = [
    "PinnedArtifactMember",
    "PinnedArtifactResolutionError",
    "resolve_pinned_artifact_member",
]
