"""Resolve one immutable control-Artifact member through its typed pointer."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import cast

from eom_image_contracts import ImageEvaluationArtifactMember
from sqlalchemy import Engine, text


class ControlArtifactResolutionError(RuntimeError):
    """Stable fail-closed control-Artifact resolution error."""


def _manifest_member(manifest: object, member_path: str) -> Mapping[str, object]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MANIFEST_INVALID")
    matches = [
        value
        for value in manifest["files"]
        if isinstance(value, dict) and value.get("file_name") == member_path
    ]
    if len(matches) != 1:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
    return cast(Mapping[str, object], matches[0])


def _safe_read_beneath(root: Path, member_path: str, *, maximum_bytes: int) -> bytes:
    parts = PurePosixPath(member_path).parts
    if not root.is_absolute() or not parts or any(value in {"", ".", ".."} for value in parts):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
    descriptors: list[int] = []
    try:
        current = os.open(
            root,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(
                part,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            descriptors.append(current)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current,
        )
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_CHANGED")
        return bytes(payload)
    except ControlArtifactResolutionError:
        raise
    except OSError as exc:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_MISSING") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def resolve_control_artifact_member(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
    *,
    maximum_bytes: int,
) -> bytes:
    """Resolve an approved immutable member and verify metadata, bytes, and hash."""

    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        row = (
            connection.execute(
                text(
                    """
                    SELECT ar.nas_path, ar.manifest, ar.approved AS revision_approved,
                           a.approved AS artifact_approved
                    FROM artifact_revisions ar
                    JOIN artifacts a ON a.logical_artifact_id = ar.logical_artifact_id
                    WHERE ar.logical_artifact_id = :artifact_id
                      AND ar.revision_id = :revision_id
                    """
                ),
                {
                    "artifact_id": pointer.artifact_id,
                    "revision_id": pointer.artifact_revision_id,
                },
            )
            .mappings()
            .one_or_none()
        )
    if row is None or not row["artifact_approved"] or not row["revision_approved"]:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_POINTER_INVALID")
    member = _manifest_member(row["manifest"], pointer.member_path)
    if (
        member.get("sha256") != pointer.sha256
        or member.get("schema_ref") != pointer.schema_ref
        or member.get("media_type") != pointer.media_type
    ):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
    payload = _safe_read_beneath(
        Path(str(row["nas_path"])), pointer.member_path, maximum_bytes=maximum_bytes
    )
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != pointer.sha256:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_HASH_MISMATCH")
    return payload
