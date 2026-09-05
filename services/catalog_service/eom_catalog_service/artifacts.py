"""Core-owned immutable artifact adapter for catalog evidence and bundles."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
MAX_JOB_IDEMPOTENCY_KEY_LENGTH = 128


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
                if revision is None:
                    raise RuntimeError("catalog artifact job is incomplete")
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

        staging = self.settings.staging_root / job_id / "artifact"
        staged = stage_file_set_artifact(
            files=files,
            primary_file=primary_file,
            job_id=job_id,
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
            artifact_type=artifact_type,
            staging=staging,
            manifest_version=manifest_version,
            file_metadata=file_metadata,
        )
        if expected_file_sha256 is not None:
            actual_file_sha256 = {member.relative_path: member.sha256 for member in staged.files}
            if actual_file_sha256 != expected_file_sha256:
                raise ValueError("catalog artifact staged members do not match expected hashes")
        with transaction(self.sessions) as session:
            transition_job(session, job_id, JobState.VALIDATED, "CATALOG_ARTIFACT_VALIDATED")
            transition_job(session, job_id, JobState.QUEUED, "CATALOG_ARTIFACT_QUEUED")
            transition_job(session, job_id, JobState.CLAIMED, "CATALOG_CORE_CLAIMED")
            transition_job(session, job_id, JobState.RUNNING, "CATALOG_ARTIFACT_STAGED")
            transition_job(session, job_id, JobState.VALIDATING_RESULT, "CATALOG_ARTIFACT_HASHED")
            transition_job(session, job_id, JobState.COMMITTING, "CATALOG_ARTIFACT_COMMITTING")
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

        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, revision_id)
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != artifact_id
                or revision.content_hash != content_hash
            ):
                raise ValueError("JSON artifact pointer does not resolve")
            primary_name = revision.manifest.get("primary_file", "result.json")
            if primary_name != "result.json":
                raise ValueError("JSON artifact primary member is invalid")
            storage_root = self.settings.nas_artifact_root.resolve(strict=True)
            artifact_root = Path(revision.nas_path).resolve(strict=True)
            if not artifact_root.is_relative_to(storage_root):
                raise ValueError("JSON artifact escaped storage root")
            primary = artifact_root / primary_name
            metadata = primary.lstat()
            if (
                primary.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > max_bytes
                or sha256_file(primary) != content_hash
            ):
                raise ValueError("JSON artifact materialization is invalid")
            value: object = json.loads(primary.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON artifact is not an object")
            return value

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
