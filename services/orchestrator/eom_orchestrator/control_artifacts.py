"""Orchestrator-owned publication of bounded control-plane evidence and Markdown."""

from __future__ import annotations

import hashlib
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_bytes,
)
from eom_workflow import ControlArtifactPointer
from sqlalchemy import Engine, select, text

from eom_orchestrator.artifacts import (
    StagedFileSet,
    commit_file_set_artifact,
    stage_file_set_artifact,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobRecord,
    ProtocolVersionRecord,
)
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job

CONTROL_ARTIFACT_PROTOCOL = "control-artifact/1.1"
LEGACY_CONTROL_ARTIFACT_PROTOCOL = "control-artifact/1.0"
LEGACY_CONTROL_ARTIFACT_SCHEMA_HASH = content_sha256(
    {
        "protocol": LEGACY_CONTROL_ARTIFACT_PROTOCOL,
        "contract": "one approved immutable member with schema, media type, and SHA-256",
    }
)
CONTROL_ARTIFACT_SCHEMA_HASH = content_sha256(
    {
        "protocol": CONTROL_ARTIFACT_PROTOCOL,
        "contract": "one resumable approved immutable member",
        "request_fields": [
            "logical_name",
            "schema_ref",
            "media_type",
            "artifact_type",
            "sha256",
            "bytes",
            "source_commit",
            "created_at_utc",
        ],
        "result": "approved Job/Artifact/ArtifactRevision and exact single-member manifest",
        "recovery": "same idempotency key and persisted Job identity through COMMITTING",
    }
)
MAX_CONTROL_ARTIFACT_BYTES = 2 * 1024 * 1024
_PUBLICATION_LOCK_NAMESPACE = "eom:control-artifact-publication"
_NON_POSTGRES_PUBLICATION_LOCK = threading.Lock()
_BASE_REQUEST_FIELDS = frozenset(
    {
        "logical_name",
        "schema_ref",
        "media_type",
        "artifact_type",
        "sha256",
        "bytes",
        "source_commit",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_version",
        "job_id",
        "logical_artifact_id",
        "revision_id",
        "artifact_type",
        "primary_file",
        "content_hash",
        "content_bytes",
        "files",
        "created_at",
    }
)
_MEMBER_FIELDS = frozenset({"file_name", "sha256", "bytes", "schema_ref", "media_type"})
_PROTOCOL_SCHEMA_HASHES = {
    LEGACY_CONTROL_ARTIFACT_PROTOCOL: LEGACY_CONTROL_ARTIFACT_SCHEMA_HASH,
    CONTROL_ARTIFACT_PROTOCOL: CONTROL_ARTIFACT_SCHEMA_HASH,
}
_PUBLICATION_TRANSITIONS: dict[JobState, tuple[JobState, str]] = {
    JobState.CREATED: (JobState.VALIDATED, "CONTROL_ARTIFACT_VALIDATED"),
    JobState.VALIDATED: (JobState.QUEUED, "CONTROL_ARTIFACT_QUEUED"),
    JobState.QUEUED: (JobState.CLAIMED, "ORCHESTRATOR_CLAIMED"),
    JobState.CLAIMED: (JobState.RUNNING, "CONTROL_ARTIFACT_STAGED"),
    JobState.RUNNING: (JobState.VALIDATING_RESULT, "CONTROL_ARTIFACT_HASHED"),
    JobState.VALIDATING_RESULT: (JobState.COMMITTING, "CONTROL_ARTIFACT_COMMITTING"),
}


@dataclass(frozen=True)
class PublishedControlArtifact:
    job_id: str
    pointer: ControlArtifactPointer
    manifest_sha256: str


class ControlArtifactPublisher:
    """Commit a reviewed local value once through the Orchestrator artifact boundary."""

    def __init__(self, engine: Engine, settings: Settings | None = None) -> None:
        self.engine = engine
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
            "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        }
        # The persisted Job is the recovery authority. The same advisory lock covers Job lookup,
        # bounded NAS publication, and database completion, so concurrent callers cannot create a
        # second publication or observe a transient state as a permanent result.
        with self._publication_lock(idempotency_key):
            job, created = self._load_or_create_job(
                idempotency_key=idempotency_key,
                artifact_type=artifact_type,
                request=request,
            )
            if not created and job.status == JobState.SUCCEEDED.value:
                return self._existing(job_id=job.job_id, request=request)
            publication_created_at = self._require_resumable_job(job=job, request=request)
            with self._staged_attempt(
                job=job,
                payload=payload,
                logical_name=logical_name,
                schema_ref=schema_ref,
                media_type=media_type,
                artifact_type=artifact_type,
                created_at=publication_created_at,
            ) as staged:
                self._advance_to_committing(job.job_id)
                final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
                self._complete_job(job_id=job.job_id, staged=staged, final=final)
            return self._existing(job_id=job.job_id, request=request)

    @contextmanager
    def _publication_lock(self, idempotency_key: str) -> Iterator[None]:
        """Serialize one semantic publication across all production processes."""

        if self.engine.dialect.name != "postgresql":
            with _NON_POSTGRES_PUBLICATION_LOCK:
                yield
            return

        lock_key = int.from_bytes(
            hashlib.sha256(f"{_PUBLICATION_LOCK_NAMESPACE}:{idempotency_key}".encode()).digest()[
                :8
            ],
            byteorder="big",
            signed=True,
        )
        with self.engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": lock_key})
            try:
                yield
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )

    def _load_or_create_job(
        self,
        *,
        idempotency_key: str,
        artifact_type: str,
        request: dict[str, str | int],
    ) -> tuple[JobRecord, bool]:
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session, CONTROL_ARTIFACT_PROTOCOL, CONTROL_ARTIFACT_SCHEMA_HASH
            )
            existing = session.scalar(
                select(JobRecord)
                .where(JobRecord.idempotency_key == idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                return existing, False
            return submit_structured_job(
                session,
                job_id=new_job_id(),
                protocol_version=CONTROL_ARTIFACT_PROTOCOL,
                idempotency_key=idempotency_key,
                task_type=artifact_type,
                request=request,
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )

    def _require_resumable_job(
        self,
        *,
        job: JobRecord,
        request: dict[str, str | int],
    ) -> datetime:
        persisted_request_hash = content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
        compared_request_fields = _BASE_REQUEST_FIELDS - {"source_commit"}
        if (
            job.protocol_version != CONTROL_ARTIFACT_PROTOCOL
            or job.task_type != request["artifact_type"]
            or job.request_hash != persisted_request_hash
            or set(job.request) != _BASE_REQUEST_FIELDS | {"created_at_utc"}
            or any(job.request.get(key) != request.get(key) for key in compared_request_fields)
            or re.fullmatch(r"[0-9a-f]{40}", str(job.request.get("source_commit"))) is None
        ):
            raise ControlPlaneError("CONTROL_ARTIFACT_CONFLICT", "control artifact replay differs")
        if job.status in {JobState.FAILED.value, JobState.CANCELLED.value}:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_TERMINAL", "control artifact publication is terminal"
            )
        if JobState(job.status) not in {*_PUBLICATION_TRANSITIONS, JobState.COMMITTING}:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_INCOMPLETE", "control artifact replay state is invalid"
            )
        with self.sessions() as session:
            logical = session.get(ArtifactRecord, job.logical_artifact_id)
            revision = session.get(ArtifactRevisionRecord, job.revision_id)
        if logical is not None or revision is not None:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_CONFLICT",
                "nonterminal control artifact already has committed metadata",
            )
        return self._persisted_created_at(job)

    @staticmethod
    def _persisted_created_at(job: JobRecord) -> datetime:
        raw = job.request.get("created_at_utc")
        if not isinstance(raw, str) or not raw.endswith("Z"):
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_CONFLICT", "control artifact timestamp is invalid"
            )
        try:
            created_at = datetime.fromisoformat(raw.removesuffix("Z") + "+00:00")
        except ValueError as exc:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_CONFLICT", "control artifact timestamp is invalid"
            ) from exc
        if (
            created_at.utcoffset() != UTC.utcoffset(created_at)
            or created_at.isoformat().replace("+00:00", "Z") != raw
        ):
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_CONFLICT", "control artifact timestamp is invalid"
            )
        return created_at

    @contextmanager
    def _staged_attempt(
        self,
        *,
        job: JobRecord,
        payload: bytes,
        logical_name: str,
        schema_ref: str,
        media_type: str,
        artifact_type: str,
        created_at: datetime,
    ) -> Iterator[StagedFileSet]:
        self.settings.staging_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{job.job_id}-control-artifact-",
            dir=self.settings.staging_root,
        ) as temporary:
            attempt_root = Path(temporary)
            source_directory = attempt_root / "source"
            source_directory.mkdir(mode=0o700)
            source = source_directory.joinpath(*PurePosixPath(logical_name).parts)
            source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source.write_bytes(payload)
            source.chmod(0o600)
            yield stage_file_set_artifact(
                files={logical_name: source},
                primary_file=logical_name,
                job_id=job.job_id,
                logical_artifact_id=job.logical_artifact_id,
                revision_id=job.revision_id,
                artifact_type=artifact_type,
                staging=attempt_root / "artifact",
                created_at=created_at,
                manifest_version="control-file-set/1.0",
                file_metadata={logical_name: {"schema_ref": schema_ref, "media_type": media_type}},
            )

    def _advance_to_committing(self, job_id: str) -> None:
        with transaction(self.sessions) as session:
            job = session.execute(
                select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
            ).scalar_one()
            current = JobState(job.status)
            while current != JobState.COMMITTING:
                successor = _PUBLICATION_TRANSITIONS.get(current)
                if successor is None:
                    raise ControlPlaneError(
                        "CONTROL_ARTIFACT_INCOMPLETE",
                        "control artifact cannot advance from its current state",
                    )
                target, event = successor
                transition_job(session, job_id, target, event)
                current = target

    def _complete_job(self, *, job_id: str, staged: StagedFileSet, final: Path) -> None:
        with transaction(self.sessions) as session:
            job = session.execute(
                select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
            ).scalar_one()
            if job.status != JobState.COMMITTING.value:
                raise ControlPlaneError(
                    "CONTROL_ARTIFACT_INCOMPLETE",
                    "control artifact is not at its commit boundary",
                )
            create_artifact_records(
                session,
                job=job,
                content_hash=staged.primary_hash,
                manifest_hash=staged.manifest_hash,
                content_bytes=staged.primary_bytes,
                nas_path=str(final),
                manifest=staged.manifest,
                result={"schema_version": "control-artifact-result/1.0", **job.request},
            )
            transition_job(
                session,
                job_id,
                JobState.SUCCEEDED,
                "CONTROL_ARTIFACT_COMMITTED",
                data={
                    "logical_artifact_id": job.logical_artifact_id,
                    "revision_id": job.revision_id,
                    "content_hash": staged.primary_hash,
                },
            )

    def _existing(self, *, job_id: str, request: dict[str, str | int]) -> PublishedControlArtifact:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            logical = (
                session.get(ArtifactRecord, job.logical_artifact_id) if job is not None else None
            )
            protocol = (
                session.get(ProtocolVersionRecord, job.protocol_version)
                if job is not None
                else None
            )
            revision = session.scalar(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job_id)
            )
            persisted_request_hash = (
                content_sha256(
                    {
                        "protocol_version": job.protocol_version,
                        "task_type": job.task_type,
                        "request": job.request,
                    }
                )
                if job is not None
                else None
            )
            if (
                job is None
                or job.status != "SUCCEEDED"
                or job.protocol_version
                not in {LEGACY_CONTROL_ARTIFACT_PROTOCOL, CONTROL_ARTIFACT_PROTOCOL}
                or protocol is None
                or protocol.schema_sha256 != _PROTOCOL_SCHEMA_HASHES.get(job.protocol_version)
                or job.task_type != request["artifact_type"]
                or job.request_hash != persisted_request_hash
                or logical is None
                or logical.logical_artifact_id != job.logical_artifact_id
                or logical.job_id != job.job_id
                or logical.artifact_type != request["artifact_type"]
                or not logical.approved
                or revision is None
                or not revision.approved
                or revision.revision_id != job.revision_id
                or revision.logical_artifact_id != job.logical_artifact_id
                or revision.job_id != job.job_id
            ):
                raise ControlPlaneError(
                    "CONTROL_ARTIFACT_INCOMPLETE", "control artifact replay is incomplete"
                )
            expected_request_fields = _BASE_REQUEST_FIELDS | (
                {"created_at_utc"} if job.protocol_version == CONTROL_ARTIFACT_PROTOCOL else set()
            )
            compared_request_fields = _BASE_REQUEST_FIELDS - {"source_commit"}
            if (
                set(job.request) != expected_request_fields
                or any(job.request.get(key) != request.get(key) for key in compared_request_fields)
                or re.fullmatch(r"[0-9a-f]{40}", str(job.request.get("source_commit"))) is None
            ):
                raise ControlPlaneError(
                    "CONTROL_ARTIFACT_CONFLICT", "control artifact replay differs"
                )
            persisted_created_at = (
                self._persisted_created_at(job).isoformat().replace("+00:00", "Z")
                if job.protocol_version == CONTROL_ARTIFACT_PROTOCOL
                else None
            )
            files = revision.manifest.get("files")
            matching = files if isinstance(files, list) else []
            if (
                set(revision.manifest) != _MANIFEST_FIELDS
                or len(matching) != 1
                or not isinstance(matching[0], dict)
                or set(matching[0]) != _MEMBER_FIELDS
                or matching[0].get("file_name") != request["logical_name"]
                or matching[0].get("sha256") != request["sha256"]
                or matching[0].get("schema_ref") != request["schema_ref"]
                or matching[0].get("media_type") != request["media_type"]
                or matching[0].get("bytes") != request["bytes"]
                or revision.content_hash != request["sha256"]
                or revision.content_bytes != request["bytes"]
                or revision.manifest.get("manifest_version") != "control-file-set/1.0"
                or revision.manifest.get("job_id") != job.job_id
                or revision.manifest.get("logical_artifact_id") != job.logical_artifact_id
                or revision.manifest.get("revision_id") != job.revision_id
                or revision.manifest.get("artifact_type") != request["artifact_type"]
                or revision.manifest.get("primary_file") != request["logical_name"]
                or revision.manifest.get("content_hash") != request["sha256"]
                or revision.manifest.get("content_bytes") != request["bytes"]
                or (
                    job.protocol_version == CONTROL_ARTIFACT_PROTOCOL
                    and revision.manifest.get("created_at") != persisted_created_at
                )
                or content_sha256(revision.manifest) != revision.manifest_hash
                or revision.result
                != {"schema_version": "control-artifact-result/1.0", **job.request}
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
            or member.as_posix() != logical_name
            or logical_name in {"", "manifest.json"}
        ):
            raise ControlPlaneError("CONTROL_ARTIFACT_INVALID", "control artifact input is invalid")
        if (
            not schema_ref.startswith("eom://schemas/")
            or "/" not in media_type
            or not artifact_type.startswith("control_")
            or len(artifact_type) > 64
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
        try:
            ControlArtifactPointer(
                artifact_id="artifact_" + "0" * 32,
                artifact_revision_id="rev_" + "0" * 32,
                sha256=sha256_bytes(payload),
                schema_ref=schema_ref,
                media_type=media_type,
                logical_name=logical_name,
            )
        except ValueError as exc:
            raise ControlPlaneError(
                "CONTROL_ARTIFACT_INVALID", "control artifact pointer contract is invalid"
            ) from exc
