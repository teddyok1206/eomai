"""Core-owned immutable artifact adapter for catalog evidence and bundles."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_file,
)
from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
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
MAX_JOB_IDEMPOTENCY_KEY_LENGTH = 128


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
        )

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
