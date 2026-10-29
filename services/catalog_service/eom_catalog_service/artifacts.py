"""Core-owned immutable artifact adapter for catalog evidence and bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol, runtime_checkable
from uuid import uuid4

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_bytes,
    sha256_file,
)
from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import ArtifactManifest
from pydantic import BaseModel
from sqlalchemy import Engine, select

from eom_catalog_service.settings import CatalogSettings

CATALOG_PROTOCOL_VERSION = "catalog/1.1"
CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": CATALOG_PROTOCOL_VERSION,
        "contracts": [
            "intake-manifest-v1",
            "mapping-proposal-v1",
            "human-decision-v1",
            "content-pack-v1",
            "content-pack-v2",
            "item-revision-manifest-v1",
            "assessment-item-content-v1",
        ],
    }
)
CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION = "catalog/1.2"
CATALOG_ITEM_CONTENT_V2_SCHEMA_HASH = content_sha256(
    {
        "protocol": CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
        "contracts": [
            "item-revision-manifest-v1",
            "assessment-item-content-v1",
            "assessment-item-content-v2",
            "content-team-editorial-markdown-v1",
        ],
    }
)
CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION = "catalog/1.13"
CATALOG_ITEM_CONTENT_V3_SCHEMA_HASH = content_sha256(
    {
        "protocol": CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION,
        "contracts": [
            "item-revision-manifest-v1",
            "assessment-item-content-v1",
            "assessment-item-content-v2",
            "assessment-item-content-v3",
            "content-team-editorial-markdown-v2",
        ],
    }
)
MAX_JOB_IDEMPOTENCY_KEY_LENGTH = 128
MAX_JSON_REVISION_BATCH = 3072
MAX_JSON_REVISION_BATCH_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CatalogJsonRevisionRequest:
    """Exact immutable primary JSON identity, not source or role authorization."""

    artifact_id: str
    revision_id: str
    content_hash: str
    max_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_id, str)
            or re.fullmatch(r"artifact_[0-9a-f]{32}", self.artifact_id) is None
            or not isinstance(self.revision_id, str)
            or re.fullmatch(r"rev_[0-9a-f]{32}", self.revision_id) is None
            or not isinstance(self.content_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_hash) is None
            or type(self.max_bytes) is not int
            or self.max_bytes < 1
        ):
            raise ValueError("JSON artifact pointer is invalid")


@dataclass(frozen=True, slots=True)
class _JsonRevisionMaterialization:
    request: CatalogJsonRevisionRequest
    nas_path: str
    content_bytes: int


def _json_file_epoch(value: os.stat_result) -> tuple[int, ...]:
    # atime can change during this read; ctime, inode and payload metadata cannot.
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _json_directory_identity(value: os.stat_result) -> tuple[int, ...]:
    # New sibling publications may change directory timestamps, not its identity.
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def _read_json_revision_payload(
    settings: CatalogSettings, materialization: _JsonRevisionMaterialization
) -> bytes:
    configured_root = settings.nas_artifact_root.absolute()
    storage_root = configured_root.resolve(strict=True)
    raw_root = Path(materialization.nas_path)
    if not raw_root.is_absolute() or raw_root.as_posix() != materialization.nas_path:
        raise ValueError("JSON artifact root is invalid")
    # A configured storage alias is trusted configuration; all descendant paths
    # are opened relative to its resolved root without following any symlinks.
    if raw_root.is_relative_to(configured_root):
        relative = raw_root.relative_to(configured_root)
    elif raw_root.is_relative_to(storage_root):
        relative = raw_root.relative_to(storage_root)
    else:
        raise ValueError("JSON artifact escaped storage root")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("JSON artifact root is invalid")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptors: list[int] = []
    path_entries: list[tuple[int, str, tuple[int, ...]]] = []
    try:
        root_fd = os.open(storage_root, directory_flags)
        descriptors.append(root_fd)
        root_identity = _json_directory_identity(os.fstat(root_fd))
        if root_identity != _json_directory_identity(storage_root.lstat()):
            raise ValueError("JSON artifact storage root changed")
        parent_fd = root_fd
        for name in relative.parts:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError("JSON artifact root traverses a symbolic link")
            child_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            descriptors.append(child_fd)
            identity = _json_directory_identity(os.fstat(child_fd))
            if identity != _json_directory_identity(before):
                raise ValueError("JSON artifact root changed")
            path_entries.append((parent_fd, name, identity))
            parent_fd = child_fd
        before = os.stat("result.json", dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("JSON artifact materialization is invalid")
        descriptor = os.open(
            "result.json",
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        descriptors.append(descriptor)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or _json_file_epoch(opened) != _json_file_epoch(before)
            or opened.st_size != materialization.content_bytes
        ):
            raise ValueError("JSON artifact materialization is invalid")
        chunks: list[bytes] = []
        remaining = materialization.content_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if (
            len(payload) != materialization.content_bytes
            or sha256_bytes(payload) != materialization.request.content_hash
            or _json_file_epoch(opened) != _json_file_epoch(os.fstat(descriptor))
            or _json_file_epoch(opened)
            != _json_file_epoch(os.stat("result.json", dir_fd=parent_fd, follow_symlinks=False))
            or root_identity != _json_directory_identity(storage_root.lstat())
            or any(
                identity
                != _json_directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                for parent, name, identity in path_entries
            )
        ):
            raise ValueError("JSON artifact materialization changed or has an invalid hash")
        return payload
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _json_revision_materialization(
    request: CatalogJsonRevisionRequest,
    logical: ArtifactRecord,
    revision: ArtifactRevisionRecord,
) -> _JsonRevisionMaterialization:
    if (
        logical.approved is not True
        or revision.approved is not True
        or logical.logical_artifact_id != request.artifact_id
        or revision.logical_artifact_id != request.artifact_id
        or revision.revision_id != request.revision_id
        or revision.content_hash != request.content_hash
        or type(revision.content_bytes) is not int
        or not 1 <= revision.content_bytes <= request.max_bytes
    ):
        raise ValueError("JSON artifact pointer does not resolve")
    manifest = revision.manifest
    if not isinstance(manifest, dict):
        raise ValueError("JSON artifact manifest is invalid")
    primary: object
    if "files" not in manifest:
        legacy = ArtifactManifest.model_validate(manifest)
        digest = content_sha256(legacy)
        primary = legacy.file_name
    else:
        digest = content_sha256(manifest)
        primary = manifest.get("primary_file")
        files = manifest["files"]
        matching = (
            [
                entry
                for entry in files
                if isinstance(entry, dict) and entry.get("file_name") == primary
            ]
            if isinstance(files, list)
            else []
        )
        if (
            len(matching) != 1
            or matching[0].get("sha256") != request.content_hash
            or type(matching[0].get("bytes")) is not int
            or matching[0]["bytes"] != revision.content_bytes
            or matching[0].get("media_type", "application/json") != "application/json"
        ):
            raise ValueError("JSON artifact primary member is invalid")
    if (
        primary != "result.json"
        or digest != revision.manifest_hash
        or manifest.get("logical_artifact_id") != request.artifact_id
        or manifest.get("revision_id") != request.revision_id
        or manifest.get("job_id") != revision.job_id
        or manifest.get("content_hash") != request.content_hash
        or type(manifest.get("content_bytes")) is not int
        or manifest["content_bytes"] != revision.content_bytes
    ):
        raise ValueError("JSON artifact manifest does not match its revision")
    return _JsonRevisionMaterialization(request, revision.nas_path, revision.content_bytes)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _read_exact_member(
    directory_fd: int,
    name: str,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> bytes:
    if Path(name).name != name or expected_size < 1 or expected_size > max_bytes:
        raise ValueError("rendered prompt member pointer is invalid")
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != expected_size
        ):
            raise ValueError("rendered prompt member materialization is invalid")
        chunks: list[bytes] = []
        remaining = expected_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if (
            len(payload) != expected_size
            or sha256_bytes(payload) != expected_sha256
            or _stat_identity(opened) != _stat_identity(os.fstat(descriptor))
        ):
            raise ValueError("rendered prompt member content is invalid")
        return payload
    finally:
        os.close(descriptor)


def normalize_catalog_idempotency_key(value: str) -> str:
    """Keep platform keys bounded without discarding the full key's identity."""
    if len(value) <= MAX_JOB_IDEMPOTENCY_KEY_LENGTH:
        return value
    digest = content_sha256({"catalog_idempotency_key": value}).removeprefix("sha256:")
    return f"catalog:{digest}"


@dataclass(frozen=True)
class CatalogArtifact:
    job_id: str
    artifact_id: str
    revision_id: str
    content_hash: str
    manifest_hash: str
    content_bytes: int
    nas_path: str
    manifest: dict[str, Any]


class CatalogArtifactReader(Protocol):
    """Minimal immutable-member port shared by direct and request-cached readers."""

    @property
    def settings(self) -> CatalogSettings: ...

    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes: ...

    def verify_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> None: ...


class CatalogJsonRevisionReader(Protocol):
    """Exact immutable JSON primary, implemented by direct and bounded batch readers."""

    def load_json_revision(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        max_bytes: int = 1_048_576,
    ) -> dict[str, Any]: ...


@runtime_checkable
class CatalogModelArtifactReader(CatalogArtifactReader, Protocol):
    """Optional operation-scoped decoding; each call still resolves the exact member."""

    def read_model_member[Model: BaseModel](
        self,
        pointer: ArtifactMemberPointer,
        *,
        expected_bytes: int,
        decoder: Callable[[str, bytes], Model],
    ) -> Model: ...


@dataclass(frozen=True)
class VerifiedArtifactMemberStream:
    stream: BinaryIO
    content_length: int
    sha256: str

    def iter_chunks(self) -> Generator[bytes, None, None]:
        try:
            while chunk := self.stream.read(1024 * 1024):
                yield chunk
        finally:
            self.stream.close()


@runtime_checkable
class CatalogModelValueDecoder(Protocol):
    """Optional root-scoped interpretation of current canonical JSON metadata.

    This returns immutable values, not source admission or authorization. Callers
    still read current rows and apply their current-state checks on every use.
    """

    def decode_model_value[Model: BaseModel](
        self,
        schema_ref: str,
        value: object,
        *,
        decoder: Callable[[str, bytes], Model],
    ) -> Model: ...


class CatalogArtifactService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)

    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, Any],
        result: dict[str, Any],
        file_metadata: dict[str, dict[str, str]] | None = None,
        manifest_version: str = "catalog-file-set/1.0",
        protocol_version: str = CATALOG_PROTOCOL_VERSION,
        protocol_schema_hash: str = CATALOG_SCHEMA_HASH,
        expected_file_sha256: dict[str, str] | None = None,
    ) -> CatalogArtifact:
        idempotency_key = normalize_catalog_idempotency_key(idempotency_key)
        job_id = new_job_id()
        artifact_id = new_logical_artifact_id()
        revision_id = new_revision_id()
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, protocol_version, protocol_schema_hash)
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version=protocol_version,
                idempotency_key=idempotency_key,
                task_type=artifact_type,
                request=request,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
            )
            job_id = job.job_id
            artifact_id = job.logical_artifact_id
            revision_id = job.revision_id
        if not created:
            with self.sessions() as session:
                revision = session.scalar(
                    select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job_id)
                )
                if revision is not None:
                    return CatalogArtifact(
                        job_id=job_id,
                        artifact_id=revision.logical_artifact_id,
                        revision_id=revision.revision_id,
                        content_hash=revision.content_hash,
                        manifest_hash=revision.manifest_hash,
                        content_bytes=revision.content_bytes,
                        nas_path=revision.nas_path,
                        manifest=revision.manifest,
                    )
                existing_job = session.get(JobRecord, job_id)
                if existing_job is None or existing_job.status != JobState.CREATED.value:
                    raise RuntimeError("catalog artifact job is incomplete")

        # A source or expected-hash validation failure intentionally leaves the immutable Job in
        # CREATED.  Exact idempotent replay may therefore restage it, while every later state stays
        # fail-closed.  Per-attempt directories prevent concurrent callers from copying over one
        # another; the locked CREATED -> VALIDATED transition selects the sole commit winner.
        attempt_root = self.settings.staging_root / job_id / f"attempt-{uuid4().hex}"
        try:
            staged = stage_file_set_artifact(
                files=files,
                primary_file=primary_file,
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
                artifact_type=artifact_type,
                staging=attempt_root / "artifact",
                manifest_version=manifest_version,
                file_metadata=file_metadata,
            )
            if expected_file_sha256 is not None:
                actual_file_sha256 = {
                    member.relative_path: member.sha256 for member in staged.files
                }
                if actual_file_sha256 != expected_file_sha256:
                    raise ValueError("catalog artifact staged members do not match expected hashes")
            with transaction(self.sessions) as session:
                transition_job(session, job_id, JobState.VALIDATED, "CATALOG_ARTIFACT_VALIDATED")
                transition_job(session, job_id, JobState.QUEUED, "CATALOG_ARTIFACT_QUEUED")
                transition_job(session, job_id, JobState.CLAIMED, "CATALOG_CORE_CLAIMED")
                transition_job(session, job_id, JobState.RUNNING, "CATALOG_ARTIFACT_STAGED")
                transition_job(
                    session,
                    job_id,
                    JobState.VALIDATING_RESULT,
                    "CATALOG_ARTIFACT_HASHED",
                )
                transition_job(
                    session,
                    job_id,
                    JobState.COMMITTING,
                    "CATALOG_ARTIFACT_COMMITTING",
                )
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            with transaction(self.sessions) as session:
                job = session.execute(
                    select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
                ).scalar_one()
                create_artifact_records(
                    session,
                    job=job,
                    content_hash=staged.primary_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.primary_bytes,
                    nas_path=str(final),
                    manifest=staged.manifest,
                    result=result,
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "CATALOG_ARTIFACT_COMMITTED",
                    data={
                        "logical_artifact_id": artifact_id,
                        "revision_id": revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            return CatalogArtifact(
                job_id=job_id,
                artifact_id=artifact_id,
                revision_id=revision_id,
                content_hash=staged.primary_hash,
                manifest_hash=staged.manifest_hash,
                content_bytes=staged.primary_bytes,
                nas_path=str(final),
                manifest=staged.manifest,
            )
        finally:
            shutil.rmtree(attempt_root, ignore_errors=True)

    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes:
        """Read one exact immutable member after full pointer and filesystem validation."""

        target = self._resolve_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        return target.read_bytes()

    def open_verified_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> VerifiedArtifactMemberStream:
        """Resolve one immutable member, then bind its verified bytes to an opened FD."""

        target = self._resolve_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        descriptor = -1
        stream: BinaryIO | None = None
        try:
            descriptor = os.open(
                target,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            stream = os.fdopen(descriptor, "rb")
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= max_bytes
            ):
                raise ValueError("artifact member descriptor is unsafe")
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if "sha256:" + digest.hexdigest() != sha256 or _stat_identity(before) != _stat_identity(
                after
            ):
                raise ValueError("artifact member changed after pointer validation")
            stream.seek(0)
            return VerifiedArtifactMemberStream(
                stream=stream,
                content_length=before.st_size,
                sha256=sha256,
            )
        except (OSError, ValueError):
            if stream is not None:
                stream.close()
            elif descriptor >= 0:
                os.close(descriptor)
            raise

    def load_rendered_prompt(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        prompt_sha256: str,
        manifest_sha256: str,
        envelope_sha256: str,
        max_prompt_bytes: int = 256 * 1024,
        max_envelope_bytes: int = 64 * 1024,
    ) -> tuple[bytes, bytes]:
        """Resolve one previously committed prompt through its immutable file-set pointer."""

        with self.sessions() as session:
            logical = session.get(ArtifactRecord, artifact_id)
            revision = session.get(ArtifactRevisionRecord, revision_id)
            job = session.get(JobRecord, revision.job_id) if revision is not None else None
            if (
                logical is None
                or revision is None
                or job is None
                or not logical.approved
                or not revision.approved
                or logical.artifact_type != "rendered-workflow-prompt"
                or logical.job_id != revision.job_id
                or revision.logical_artifact_id != artifact_id
                or revision.content_hash != prompt_sha256
                or revision.manifest_hash != manifest_sha256
                or content_sha256(revision.manifest) != manifest_sha256
                or job.status != JobState.SUCCEEDED.value
                or job.logical_artifact_id != artifact_id
                or job.revision_id != revision_id
            ):
                raise ValueError("rendered prompt pointer does not resolve")
            manifest = revision.manifest
            files = manifest.get("files")
            if (
                manifest.get("logical_artifact_id") != artifact_id
                or manifest.get("revision_id") != revision_id
                or manifest.get("job_id") != revision.job_id
                or manifest.get("artifact_type") != "rendered-workflow-prompt"
                or manifest.get("primary_file") != "prompt.txt"
                or manifest.get("content_hash") != prompt_sha256
                or not isinstance(files, list)
            ):
                raise ValueError("rendered prompt manifest is invalid")
            members = {
                item.get("file_name"): item
                for item in files
                if isinstance(item, dict) and isinstance(item.get("file_name"), str)
            }
            prompt_entry = members.get("prompt.txt")
            envelope_entry = members.get("prompt-envelope.json")
            if (
                set(members) != {"prompt.txt", "prompt-envelope.json"}
                or len(files) != 2
                or not isinstance(prompt_entry, dict)
                or not isinstance(envelope_entry, dict)
                or prompt_entry.get("sha256") != prompt_sha256
                or envelope_entry.get("sha256") != envelope_sha256
                or not isinstance(prompt_entry.get("bytes"), int)
                or not isinstance(envelope_entry.get("bytes"), int)
                or prompt_entry["bytes"] != revision.content_bytes
                or prompt_entry["bytes"] > max_prompt_bytes
                or envelope_entry["bytes"] > max_envelope_bytes
            ):
                raise ValueError("rendered prompt members do not match their pointer")
            raw_artifact_root = Path(revision.nas_path)

        storage_root = self.settings.nas_artifact_root.resolve(strict=True)
        root_metadata = raw_artifact_root.lstat()
        if raw_artifact_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
            raise ValueError("rendered prompt materialization is invalid")
        artifact_root = raw_artifact_root.resolve(strict=True)
        if not artifact_root.is_relative_to(storage_root):
            raise ValueError("rendered prompt escaped storage root")
        root_fd = os.open(
            artifact_root,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened_root = os.fstat(root_fd)
            prompt_bytes = _read_exact_member(
                root_fd,
                "prompt.txt",
                expected_size=prompt_entry["bytes"],
                expected_sha256=prompt_sha256,
                max_bytes=max_prompt_bytes,
            )
            envelope_bytes = _read_exact_member(
                root_fd,
                "prompt-envelope.json",
                expected_size=envelope_entry["bytes"],
                expected_sha256=envelope_sha256,
                max_bytes=max_envelope_bytes,
            )
            if _stat_identity(opened_root) != _stat_identity(os.fstat(root_fd)):
                raise ValueError("rendered prompt root changed while reading")
        finally:
            os.close(root_fd)
        return prompt_bytes, envelope_bytes

    def verify_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> None:
        """Rehash one exact member without loading large source bytes into memory."""

        self._resolve_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )

    def _resolve_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> Path:

        relative = Path(member_path)
        if (
            relative.is_absolute()
            or relative.as_posix() != member_path
            or not relative.parts
            or ".." in relative.parts
            or max_bytes < 1
        ):
            raise ValueError("artifact member pointer is unsafe")
        with self.sessions() as session:
            logical = session.get(ArtifactRecord, artifact_id)
            revision = session.get(ArtifactRevisionRecord, revision_id)
            if (
                logical is None
                or revision is None
                or not logical.approved
                or not revision.approved
                or revision.logical_artifact_id != artifact_id
                or logical.logical_artifact_id != revision.logical_artifact_id
            ):
                raise ValueError("artifact member pointer does not resolve")
            files = revision.manifest.get("files")
            matching = (
                [value for value in files if isinstance(value, dict)]
                if isinstance(files, list)
                else []
            )
            matching = [value for value in matching if value.get("file_name") == member_path]
            if (
                len(matching) != 1
                or matching[0].get("sha256") != sha256
                or matching[0].get("media_type") != media_type
                or matching[0].get("schema_ref") != schema_ref
                or not isinstance(matching[0].get("bytes"), int)
                or matching[0]["bytes"] > max_bytes
            ):
                raise ValueError("artifact member manifest does not match pointer")
            storage_root = self.settings.nas_artifact_root.resolve(strict=True)
            raw_artifact_root = Path(revision.nas_path)
            root_metadata = raw_artifact_root.lstat()
            if raw_artifact_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
                raise ValueError("artifact root materialization is invalid")
            artifact_root = raw_artifact_root.resolve(strict=True)
            if not artifact_root.is_relative_to(storage_root):
                raise ValueError("artifact member escaped storage root")
            candidate = artifact_root / relative
            target = candidate.resolve(strict=True)
            if target != candidate or not target.is_relative_to(artifact_root):
                raise ValueError("artifact member traverses a symbolic link")
            metadata = target.lstat()
            if (
                target.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != matching[0]["bytes"]
                or metadata.st_size > max_bytes
                or sha256_file(target) != sha256
            ):
                raise ValueError("artifact member materialization is invalid")
            return target

    def load_json_revision(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        max_bytes: int = 1_048_576,
    ) -> dict[str, Any]:
        """Resolve one immutable small JSON result through its pinned artifact identity."""
        request = CatalogJsonRevisionRequest(artifact_id, revision_id, content_hash, max_bytes)
        return self.load_json_revisions((request,))[revision_id]

    def load_json_revisions(
        self, requests: tuple[CatalogJsonRevisionRequest, ...]
    ) -> dict[str, dict[str, Any]]:
        """Read bounded exact primaries with one fresh metadata query and no partial result.

        The returned values are not source authorization or Workflow provenance.
        Callers continue to validate those through their existing owner boundaries.
        """
        if not isinstance(requests, tuple) or len(requests) > MAX_JSON_REVISION_BATCH:
            raise ValueError("CATALOG_JSON_BATCH_SELECTION_INVALID")
        checked: dict[str, CatalogJsonRevisionRequest] = {}
        for request in requests:
            if type(request) is not CatalogJsonRevisionRequest:
                raise ValueError("CATALOG_JSON_BATCH_SELECTION_INVALID")
            # Frozen dataclasses are not a privilege boundary; revalidate forged instances.
            validated = CatalogJsonRevisionRequest(
                request.artifact_id, request.revision_id, request.content_hash, request.max_bytes
            )
            if validated.revision_id in checked:
                raise ValueError("CATALOG_JSON_BATCH_SELECTION_INVALID")
            checked[validated.revision_id] = validated
        if not checked:
            return {}
        with self.sessions() as session:
            rows = session.execute(
                select(ArtifactRevisionRecord, ArtifactRecord)
                .join(
                    ArtifactRecord,
                    ArtifactRecord.logical_artifact_id
                    == ArtifactRevisionRecord.logical_artifact_id,
                )
                .where(ArtifactRevisionRecord.revision_id.in_(tuple(checked)))
                .execution_options(populate_existing=True)
            ).all()
            by_revision = {revision.revision_id: (revision, logical) for revision, logical in rows}
            if len(by_revision) != len(checked):
                raise ValueError("JSON artifact pointer does not resolve")
            materializations = tuple(
                _json_revision_materialization(
                    request, by_revision[revision_id][1], by_revision[revision_id][0]
                )
                for revision_id, request in checked.items()
            )
            if (
                sum(value.content_bytes for value in materializations)
                > MAX_JSON_REVISION_BATCH_BYTES
            ):
                raise ValueError("CATALOG_JSON_BATCH_BUDGET_EXCEEDED")
            result: dict[str, dict[str, Any]] = {}
            for materialization in materializations:
                payload = _read_json_revision_payload(self.settings, materialization)
                value: object = json.loads(payload.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON artifact is not an object")
                result[materialization.request.revision_id] = value
            return result

    def verify_file_pointer(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        member: str,
    ) -> None:
        """Resolve one exact regular file member without exposing its storage location."""

        relative = Path(member)
        if (
            relative.is_absolute()
            or relative.as_posix() != member
            or len(relative.parts) != 1
            or ".." in relative.parts
        ):
            raise ValueError("artifact member is unsafe")
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, revision_id)
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != artifact_id
                or revision.content_hash != content_hash
            ):
                raise ValueError("file artifact pointer does not resolve")
            files = revision.manifest.get("files")
            if not isinstance(files, list) or revision.manifest.get("primary_file") != member:
                raise ValueError("file artifact manifest is invalid")
            matching = [
                value
                for value in files
                if isinstance(value, dict) and value.get("file_name") == member
            ]
            if len(matching) != 1 or matching[0].get("sha256") != content_hash:
                raise ValueError("file artifact manifest does not match pointer")
            storage_root = self.settings.nas_artifact_root.resolve(strict=True)
            artifact_root = Path(revision.nas_path).resolve(strict=True)
            if not artifact_root.is_relative_to(storage_root):
                raise ValueError("file artifact escaped storage root")
            target = artifact_root / member
            metadata = target.lstat()
            if (
                target.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or sha256_file(target) != content_hash
            ):
                raise ValueError("file artifact materialization is invalid")
