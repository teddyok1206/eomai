"""Orchestrator-owned publication of bounded control-plane evidence and Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_bytes,
)
from eom_protocol import ErrorCode
from eom_workflow import ControlArtifactPointer
from sqlalchemy import Engine, select

from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job

CONTROL_ARTIFACT_PROTOCOL = "control-artifact/1.0"
CONTROL_ARTIFACT_SCHEMA_HASH = content_sha256(
    {
        "protocol": CONTROL_ARTIFACT_PROTOCOL,
        "contract": "one approved immutable member with schema, media type, and SHA-256",
    }
)
MAX_CONTROL_ARTIFACT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PublishedControlArtifact:
    job_id: str
    pointer: ControlArtifactPointer
    manifest_sha256: str


class ControlArtifactPublisher:
    """Commit a reviewed local value once through the Orchestrator artifact boundary."""

    def __init__(self, engine: Engine, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self.sessions = build_session_factory(engine)

    def publish_bytes(
        self,
        *,
        payload: bytes,
        logical_name: str,
        schema_ref: str,
        media_type: str,
        artifact_type: str,
        idempotency_key: str,
        created_at: datetime,
        source_commit: str,
    ) -> PublishedControlArtifact:
        self._validate_input(
            payload=payload,
            logical_name=logical_name,
            schema_ref=schema_ref,
            media_type=media_type,
            artifact_type=artifact_type,
            idempotency_key=idempotency_key,
            created_at=created_at,
            source_commit=source_commit,
        )
        digest = sha256_bytes(payload)
        request: dict[str, str | int] = {
            "logical_name": logical_name,
            "schema_ref": schema_ref,
            "media_type": media_type,
            "artifact_type": artifact_type,
            "sha256": digest,
            "bytes": len(payload),
            "source_commit": source_commit,
        }
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session, CONTROL_ARTIFACT_PROTOCOL, CONTROL_ARTIFACT_SCHEMA_HASH
            )
            job, created = submit_structured_job(
                session,
                job_id=new_job_id(),
                protocol_version=CONTROL_ARTIFACT_PROTOCOL,
                idempotency_key=idempotency_key,
                task_type=artifact_type,
                request=request,
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )
            job_id = job.job_id
            artifact_id = job.logical_artifact_id
            revision_id = job.revision_id
        if not created:
            return self._existing(job_id=job_id, request=request)

        source_directory = self.settings.staging_root / job_id / "control-source"
        artifact_staging = self.settings.staging_root / job_id / "control-artifact"
        try:
            source_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            source = source_directory / logical_name
            if source.parent != source_directory:
                source.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
            source.write_bytes(payload)
            source.chmod(0o600)
            staged = stage_file_set_artifact(
                files={logical_name: source},
                primary_file=logical_name,
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
                artifact_type=artifact_type,
                staging=artifact_staging,
                created_at=created_at,
                manifest_version="control-file-set/1.0",
                file_metadata={logical_name: {"schema_ref": schema_ref, "media_type": media_type}},
            )
            with transaction(self.sessions) as session:
                transition_job(session, job_id, JobState.VALIDATED, "CONTROL_ARTIFACT_VALIDATED")
                transition_job(session, job_id, JobState.QUEUED, "CONTROL_ARTIFACT_QUEUED")
                transition_job(session, job_id, JobState.CLAIMED, "ORCHESTRATOR_CLAIMED")
                transition_job(session, job_id, JobState.RUNNING, "CONTROL_ARTIFACT_STAGED")
                transition_job(
                    session, job_id, JobState.VALIDATING_RESULT, "CONTROL_ARTIFACT_HASHED"
                )
                transition_job(session, job_id, JobState.COMMITTING, "CONTROL_ARTIFACT_COMMITTING")
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
                    result={"schema_version": "control-artifact-result/1.0", **request},
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    "CONTROL_ARTIFACT_COMMITTED",
                    data={
                        "logical_artifact_id": artifact_id,
                        "revision_id": revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
        except Exception:
            self._fail_job(job_id)
            raise
        return PublishedControlArtifact(
            job_id=job_id,
            pointer=ControlArtifactPointer(
                artifact_id=artifact_id,
                artifact_revision_id=revision_id,
                sha256=digest,
                schema_ref=schema_ref,
                media_type=media_type,
                logical_name=logical_name,
            ),
            manifest_sha256=staged.manifest_hash,
        )

    def _existing(self, *, job_id: str, request: dict[str, str | int]) -> PublishedControlArtifact:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            revision = session.scalar(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job_id)
            )
            if (
                job is None
                or job.status != "SUCCEEDED"
                or revision is None
                or not revision.approved
            ):
                raise ControlPlaneError(
                    "CONTROL_ARTIFACT_INCOMPLETE", "control artifact replay is incomplete"
                )
            files = revision.manifest.get("files")
            matching = (
                [entry for entry in files if isinstance(entry, dict)]
                if isinstance(files, list)
                else []
            )
            if (
                len(matching) != 1
                or matching[0].get("file_name") != request["logical_name"]
                or matching[0].get("sha256") != request["sha256"]
                or matching[0].get("schema_ref") != request["schema_ref"]
                or matching[0].get("media_type") != request["media_type"]
                or revision.content_hash != request["sha256"]
            ):
                raise ControlPlaneError(
                    "CONTROL_ARTIFACT_CONFLICT", "control artifact replay differs"
                )
            return PublishedControlArtifact(
                job_id=job.job_id,
                pointer=ControlArtifactPointer(
                    artifact_id=revision.logical_artifact_id,
                    artifact_revision_id=revision.revision_id,
                    sha256=revision.content_hash,
                    schema_ref=str(request["schema_ref"]),
                    media_type=str(request["media_type"]),
                    logical_name=str(request["logical_name"]),
                ),
                manifest_sha256=revision.manifest_hash,
            )

    def _fail_job(self, job_id: str) -> None:
        try:
            with transaction(self.sessions) as session:
                job = session.get(JobRecord, job_id)
                if job is not None and job.status not in {"SUCCEEDED", "FAILED"}:
                    job.error_code = ErrorCode.ARTIFACT_COMMIT_FAILED.value
                    job.error_message = "control artifact publication failed"
                    transition_job(
                        session,
                        job_id,
                        JobState.FAILED,
                        "CONTROL_ARTIFACT_FAILED",
                    )
        except Exception:
            return

    @staticmethod
    def _validate_input(
        *,
        payload: bytes,
        logical_name: str,
        schema_ref: str,
        media_type: str,
        artifact_type: str,
        idempotency_key: str,
        created_at: datetime,
        source_commit: str,
    ) -> None:
        member = PurePosixPath(logical_name)
        if (
            not payload
            or len(payload) > MAX_CONTROL_ARTIFACT_BYTES
            or member.is_absolute()
            or ".." in member.parts
            or "." in member.parts
            or "\\" in logical_name
            or logical_name in {"", "manifest.json"}
        ):
            raise ControlPlaneError("CONTROL_ARTIFACT_INVALID", "control artifact input is invalid")
        if (
            not schema_ref.startswith("eom://schemas/")
            or "/" not in media_type
            or not artifact_type.startswith("control_")
            or not 16 <= len(idempotency_key) <= 128
            or created_at.tzinfo is None
            or created_at.utcoffset() != UTC.utcoffset(created_at)
            or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        ):
            raise ControlPlaneError("CONTROL_ARTIFACT_INVALID", "control artifact input is invalid")
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_INVALID", "control artifact must be UTF-8"
            ) from exc
