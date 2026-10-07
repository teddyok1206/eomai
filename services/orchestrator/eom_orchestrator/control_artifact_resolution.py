"""Resolve one immutable control-Artifact member through its typed pointer."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from eom_image_contracts import ImageEvaluationArtifactMember
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, text


class ControlArtifactResolutionError(RuntimeError):
    """Stable fail-closed control-Artifact resolution error."""


@dataclass(frozen=True, slots=True)
class BoundedControlArtifactRead:
    """A temporary materialization request, not a new persistent Artifact identity."""

    pointer: ArtifactMemberPointer | ImageEvaluationArtifactMember
    maximum_bytes: int


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
    pointer: ArtifactMemberPointer | ImageEvaluationArtifactMember,
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
    return _read_verified_member(
        root=Path(str(row["nas_path"])),
        member=member,
        pointer=pointer,
        maximum_bytes=maximum_bytes,
    )


def _read_verified_member(
    *,
    root: Path,
    member: Mapping[str, object],
    pointer: ArtifactMemberPointer | ImageEvaluationArtifactMember,
    maximum_bytes: int,
) -> bytes:
    if (
        member.get("sha256") != pointer.sha256
        or member.get("schema_ref") != pointer.schema_ref
        or member.get("media_type") != pointer.media_type
    ):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
    payload = _safe_read_beneath(root, pointer.member_path, maximum_bytes=maximum_bytes)
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != pointer.sha256:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_HASH_MISMATCH")
    return payload


def resolve_control_artifact_members(
    engine: Engine,
    reads: tuple[BoundedControlArtifactRead, ...],
) -> tuple[bytes, ...]:
    """One indexed snapshot query and one manifest map/revision; preserve request order.

    This is a bounded Orchestrator materialization boundary, not a shared/persistent cache.
    Metadata for all requests is admitted before any bytes are read. Complexity is linear
    in manifest members and requested bytes instead of per-image DB queries/list scans.
    """
    if not 1 <= len(reads) <= 128:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_BATCH_INVALID")
    try:
        pointers = tuple(
            ArtifactMemberPointer.model_validate_json(read.pointer.model_dump_json())
            for read in reads
        )
    except ValueError as exc:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_BATCH_INVALID") from exc
    if len(set(pointers)) != len(pointers) or any(
        type(read.maximum_bytes) is not int or not 0 < read.maximum_bytes <= 64 * 1024**2
        for read in reads
    ):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_BATCH_INVALID")
    # A real bounded LoRA member can exceed the old PNG-only ceiling; keep an aggregate cap so
    # admitting that member never turns the 128-entry API into an unbounded materialization.
    if sum(read.maximum_bytes for read in reads) > 128 * 1024**2:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_BATCH_INVALID")
    keys = tuple(
        dict.fromkeys((pointer.artifact_id, pointer.artifact_revision_id) for pointer in pointers)
    )
    key_set = frozenset(keys)
    placeholders = ",".join(
        f"(:artifact_id_{index}, :revision_id_{index})" for index in range(len(keys))
    )
    parameters = {
        name: value
        for index, key in enumerate(keys)
        for name, value in ((f"artifact_id_{index}", key[0]), (f"revision_id_{index}", key[1]))
    }
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        rows = (
            connection.execute(
                text(
                    "SELECT ar.logical_artifact_id AS artifact_id, ar.revision_id, "
                    "ar.nas_path, ar.manifest, "
                    "ar.approved AS revision_approved, a.approved AS artifact_approved "
                    "FROM artifact_revisions ar JOIN artifacts a "
                    "ON a.logical_artifact_id = ar.logical_artifact_id "
                    "WHERE (ar.logical_artifact_id, ar.revision_id) IN (" + placeholders + ")"
                ),
                parameters,
            )
            .mappings()
            .all()
        )
    metadata = {}
    for row in rows:
        key = (row["artifact_id"], row["revision_id"])
        if (
            key in metadata
            or key not in key_set
            or not row["revision_approved"]
            or not row["artifact_approved"]
        ):
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_POINTER_INVALID")
        manifest = row["manifest"]
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MANIFEST_INVALID")
        by_name = {}
        for member in manifest["files"]:
            if (
                not isinstance(member, dict)
                or not isinstance(member.get("file_name"), str)
                or member["file_name"] in by_name
            ):
                raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
            by_name[member["file_name"]] = member
        metadata[key] = (Path(str(row["nas_path"])), by_name)
    if set(metadata) != key_set:
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_POINTER_INVALID")
    admitted = []
    for pointer, read in zip(pointers, reads, strict=True):
        root, members = metadata[(pointer.artifact_id, pointer.artifact_revision_id)]
        member = members.get(pointer.member_path)
        if member is None or any(
            member.get(name) != getattr(pointer, name)
            for name in ("sha256", "schema_ref", "media_type")
        ):
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
        declared_bytes = member.get("bytes")
        if type(declared_bytes) is not int or not 0 < declared_bytes <= read.maximum_bytes:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
        admitted.append((root, member, pointer, read.maximum_bytes, declared_bytes))
    result = []
    for root, member, pointer, maximum, expected_bytes in admitted:
        payload = _read_verified_member(
            root=root, member=member, pointer=pointer, maximum_bytes=maximum
        )
        if len(payload) != expected_bytes:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_INVALID")
        result.append(payload)
    return tuple(result)
