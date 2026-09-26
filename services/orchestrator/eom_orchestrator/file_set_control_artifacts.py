"""Orchestrator-only publication of bounded, immutable control file sets."""

from __future__ import annotations

import hashlib
import re
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_file,
)
from sqlalchemy import Engine, select, text

from eom_orchestrator.artifacts import commit_file_set_artifact, stage_file_set_artifact
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

CONTROL_FILE_SET_PROTOCOL = "control-file-set/1.0"
CONTROL_FILE_SET_SCHEMA_HASH = content_sha256(
    {
        "protocol": CONTROL_FILE_SET_PROTOCOL,
        "contract": "one bounded immutable typed file set committed only by Orchestrator",
        "request": [
            "primary_file",
            "artifact_type",
            "manifest_version",
            "members[file_name,sha256,bytes,schema_ref,media_type]",
            "source_commit",
            "created_at_utc",
        ],
        "result": "approved Artifact and ArtifactRevision with exact manifest and hashes",
    }
)
# The science visual-pilot result has one primary manifest plus at most 384 rendered
# pages and 512 candidate crops.  Keep the generic control boundary above that
# contract while still bounding all callers to a small immutable file set.
MAX_FILE_SET_MEMBERS = 1024
MAX_FILE_SET_BYTES = 1024 * 1024 * 1024
_LOCK_NAMESPACE = "eom:control-file-set-publication"
_LOCAL_LOCK = threading.Lock()
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
_TRANSITIONS: dict[JobState, tuple[JobState, str]] = {
    JobState.CREATED: (JobState.VALIDATED, "CONTROL_FILE_SET_VALIDATED"),
    JobState.VALIDATED: (JobState.QUEUED, "CONTROL_FILE_SET_QUEUED"),
    JobState.QUEUED: (JobState.CLAIMED, "ORCHESTRATOR_CLAIMED"),
    JobState.CLAIMED: (JobState.RUNNING, "CONTROL_FILE_SET_STAGED"),
    JobState.RUNNING: (JobState.VALIDATING_RESULT, "CONTROL_FILE_SET_HASHED"),
    JobState.VALIDATING_RESULT: (JobState.COMMITTING, "CONTROL_FILE_SET_COMMITTING"),
}


@dataclass(frozen=True, slots=True)
class ControlFileSetMember:
    file_name: str
    source: Path
    sha256: str
    bytes: int
    schema_ref: str
    media_type: str


@dataclass(frozen=True, slots=True)
class PublishedControlFileSet:
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    primary_file: str
    primary_sha256: str
    manifest_sha256: str
    nas_path: str


class ControlFileSetPublisher:
    """Publish one prevalidated file set with resumable idempotent commit semantics."""

    def __init__(self, engine: Engine, settings: Settings | None = None) -> None:
        self.engine = engine
        self.settings = settings or Settings.from_environment()
        self.sessions = build_session_factory(engine)

    def publish(
        self,
        *,
        members: tuple[ControlFileSetMember, ...],
        primary_file: str,
        artifact_type: str,
        manifest_version: str,
        idempotency_key: str,
        source_commit: str,
        created_at: datetime,
    ) -> PublishedControlFileSet:
        request = self._request(
            members=members,
            primary_file=primary_file,
            artifact_type=artifact_type,
            manifest_version=manifest_version,
            source_commit=source_commit,
            created_at=created_at,
            idempotency_key=idempotency_key,
        )
        with self._publication_lock(idempotency_key):
            job, created = self._load_or_create_job(
                idempotency_key=idempotency_key,
                artifact_type=artifact_type,
                request=request,
            )
            if not created and job.status == JobState.SUCCEEDED.value:
                return self._existing(job.job_id, request)
            self._require_resumable(job, request)
            staging = self.settings.staging_root / job.job_id / "control-file-set"
            staged = stage_file_set_artifact(
                files={value.file_name: value.source for value in members},
                primary_file=primary_file,
                job_id=job.job_id,
                logical_artifact_id=job.logical_artifact_id,
                revision_id=job.revision_id,
                artifact_type=artifact_type,
                staging=staging,
                created_at=self._created_at(job),
                manifest_version=manifest_version,
                file_metadata={
                    value.file_name: {
                        "schema_ref": value.schema_ref,
                        "media_type": value.media_type,
                    }
                    for value in members
                },
            )
            expected = {value.file_name: (value.sha256, value.bytes) for value in members}
            actual = {value.relative_path: (value.sha256, value.size) for value in staged.files}
            if actual != expected:
                raise ControlPlaneError(
                    "CONTROL_FILE_SET_HASH_MISMATCH",
                    "staged file set differs from its immutable request",
                )
            self._advance(job.job_id)
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            with transaction(self.sessions) as session:
                locked = session.execute(
                    select(JobRecord).where(JobRecord.job_id == job.job_id).with_for_update()
                ).scalar_one()
                if locked.status != JobState.COMMITTING.value:
                    raise ControlPlaneError(
                        "CONTROL_FILE_SET_INCOMPLETE",
                        "control file set is not at its commit boundary",
                    )
                create_artifact_records(
                    session,
                    job=locked,
                    content_hash=staged.primary_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.primary_bytes,
                    nas_path=str(final),
                    manifest=staged.manifest,
                    result={
                        "schema_version": "control-file-set-result/1.0",
                        **locked.request,
                    },
                )
                transition_job(
                    session,
                    job.job_id,
                    JobState.SUCCEEDED,
                    "CONTROL_FILE_SET_COMMITTED",
                    data={
                        "logical_artifact_id": job.logical_artifact_id,
                        "revision_id": job.revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
            return self._existing(job.job_id, request)

    def _request(
        self,
        *,
        members: tuple[ControlFileSetMember, ...],
        primary_file: str,
        artifact_type: str,
        manifest_version: str,
        source_commit: str,
        created_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if (
            not 1 <= len(members) <= MAX_FILE_SET_MEMBERS
            or not 16 <= len(idempotency_key) <= 128
            or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
            or created_at.tzinfo is None
            or created_at.utcoffset() != UTC.utcoffset(created_at)
            or not artifact_type.startswith("control_")
            or len(artifact_type) > 64
            or re.fullmatch(r"[a-z0-9][a-z0-9._/-]{2,127}", manifest_version) is None
        ):
            raise ControlPlaneError("CONTROL_FILE_SET_INVALID", "file-set input is invalid")
        names = tuple(value.file_name for value in members)
        if names != tuple(sorted(set(names))) or primary_file not in names:
            raise ControlPlaneError("CONTROL_FILE_SET_INVALID", "file-set members are invalid")
        total = 0
        request_members = []
        for member in members:
            relative = PurePosixPath(member.file_name)
            try:
                metadata = member.source.lstat()
            except OSError as exc:
                raise ControlPlaneError(
                    "CONTROL_FILE_SET_INVALID", "file-set source is missing"
                ) from exc
            if (
                relative.is_absolute()
                or relative.as_posix() != member.file_name
                or any(part in {"", ".", ".."} for part in relative.parts)
                or "\\" in member.file_name
                or member.file_name == "manifest.json"
                or member.source.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or metadata.st_size != member.bytes
                or sha256_file(member.source) != member.sha256
                or re.fullmatch(r"sha256:[0-9a-f]{64}", member.sha256) is None
                or re.fullmatch(r"eom://schemas/[A-Za-z0-9._/-]{1,220}", member.schema_ref) is None
                or re.fullmatch(
                    r"[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*",
                    member.media_type,
                )
                is None
            ):
                raise ControlPlaneError("CONTROL_FILE_SET_INVALID", "file-set member is invalid")
            total += member.bytes
            request_members.append(
                {
                    "file_name": member.file_name,
                    "sha256": member.sha256,
                    "bytes": member.bytes,
                    "schema_ref": member.schema_ref,
                    "media_type": member.media_type,
                }
            )
        if total > MAX_FILE_SET_BYTES:
            raise ControlPlaneError("CONTROL_FILE_SET_INVALID", "file set is too large")
        return {
            "primary_file": primary_file,
            "artifact_type": artifact_type,
            "manifest_version": manifest_version,
            "members": request_members,
            "source_commit": source_commit,
            "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        }

    @contextmanager
    def _publication_lock(self, idempotency_key: str) -> Iterator[None]:
        if self.engine.dialect.name != "postgresql":
            with _LOCAL_LOCK:
                yield
            return
        lock_key = int.from_bytes(
            hashlib.sha256(f"{_LOCK_NAMESPACE}:{idempotency_key}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        with self.engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:value)"), {"value": lock_key})
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:value)"), {"value": lock_key})

    def _load_or_create_job(
        self,
        *,
        idempotency_key: str,
        artifact_type: str,
        request: dict[str, Any],
    ) -> tuple[JobRecord, bool]:
        with transaction(self.sessions) as session:
            ensure_protocol_version(
                session,
                CONTROL_FILE_SET_PROTOCOL,
                CONTROL_FILE_SET_SCHEMA_HASH,
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
                protocol_version=CONTROL_FILE_SET_PROTOCOL,
                idempotency_key=idempotency_key,
                task_type=artifact_type,
                request=request,
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )

    def _require_resumable(self, job: JobRecord, request: dict[str, Any]) -> None:
        if (
            job.protocol_version != CONTROL_FILE_SET_PROTOCOL
            or job.task_type != request["artifact_type"]
            or job.request != request
            or job.request_hash
            != content_sha256(
                {
                    "protocol_version": job.protocol_version,
                    "task_type": job.task_type,
                    "request": job.request,
                }
            )
            or JobState(job.status) not in {*_TRANSITIONS, JobState.COMMITTING}
        ):
            raise ControlPlaneError(
                "CONTROL_FILE_SET_CONFLICT", "file-set publication replay differs"
            )
        with self.sessions() as session:
            if (
                session.get(ArtifactRecord, job.logical_artifact_id) is not None
                or session.get(ArtifactRevisionRecord, job.revision_id) is not None
            ):
                raise ControlPlaneError(
                    "CONTROL_FILE_SET_CONFLICT", "nonterminal file set already has metadata"
                )

    @staticmethod
    def _created_at(job: JobRecord) -> datetime:
        raw = job.request.get("created_at_utc")
        if not isinstance(raw, str) or not raw.endswith("Z"):
            raise ControlPlaneError("CONTROL_FILE_SET_CONFLICT", "timestamp is invalid")
        try:
            value = datetime.fromisoformat(raw.removesuffix("Z") + "+00:00")
        except ValueError as exc:
            raise ControlPlaneError("CONTROL_FILE_SET_CONFLICT", "timestamp is invalid") from exc
        if value.utcoffset() != UTC.utcoffset(value):
            raise ControlPlaneError("CONTROL_FILE_SET_CONFLICT", "timestamp is invalid")
        return value

    def _advance(self, job_id: str) -> None:
        with transaction(self.sessions) as session:
            job = session.execute(
                select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
            ).scalar_one()
            current = JobState(job.status)
            while current != JobState.COMMITTING:
                successor = _TRANSITIONS.get(current)
                if successor is None:
                    raise ControlPlaneError(
                        "CONTROL_FILE_SET_INCOMPLETE", "file set cannot advance"
                    )
                target, event = successor
                transition_job(session, job_id, target, event)
                current = target

    def _existing(
        self,
        job_id: str,
        request: dict[str, Any],
    ) -> PublishedControlFileSet:
        with self.sessions() as session:
            job = session.get(JobRecord, job_id)
            revision = session.scalar(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job_id)
            )
            logical = (
                session.get(ArtifactRecord, job.logical_artifact_id) if job is not None else None
            )
            protocol = (
                session.get(ProtocolVersionRecord, CONTROL_FILE_SET_PROTOCOL)
                if job is not None
                else None
            )
        if job is None:
            raise ControlPlaneError(
                "CONTROL_FILE_SET_INCOMPLETE", "published file set is incomplete"
            )
        if (
            job.protocol_version != CONTROL_FILE_SET_PROTOCOL
            or job.task_type != request["artifact_type"]
            or job.request != request
            or job.request_hash
            != content_sha256(
                {
                    "protocol_version": job.protocol_version,
                    "task_type": job.task_type,
                    "request": job.request,
                }
            )
        ):
            raise ControlPlaneError(
                "CONTROL_FILE_SET_CONFLICT", "file-set publication replay differs"
            )
        if (
            job.status != JobState.SUCCEEDED.value
            or protocol is None
            or protocol.schema_sha256 != CONTROL_FILE_SET_SCHEMA_HASH
            or logical is None
            or not logical.approved
            or logical.logical_artifact_id != job.logical_artifact_id
            or logical.job_id != job.job_id
            or logical.artifact_type != request["artifact_type"]
            or revision is None
            or not revision.approved
            or revision.logical_artifact_id != job.logical_artifact_id
            or revision.revision_id != job.revision_id
            or revision.job_id != job.job_id
        ):
            raise ControlPlaneError(
                "CONTROL_FILE_SET_INCOMPLETE", "published file set is incomplete"
            )
        members = request["members"]
        actual_members = revision.manifest.get("files")
        if (
            set(revision.manifest) != _MANIFEST_FIELDS
            or not isinstance(actual_members, list)
            or any(
                not isinstance(value, dict) or set(value) != _MEMBER_FIELDS
                for value in actual_members
            )
            or revision.manifest.get("job_id") != job.job_id
            or revision.manifest.get("logical_artifact_id") != job.logical_artifact_id
            or revision.manifest.get("revision_id") != job.revision_id
            or revision.manifest.get("primary_file") != request["primary_file"]
            or revision.manifest.get("artifact_type") != request["artifact_type"]
            or revision.manifest.get("manifest_version") != request["manifest_version"]
            or revision.manifest.get("created_at") != request["created_at_utc"]
            or actual_members != members
            or content_sha256(revision.manifest) != revision.manifest_hash
            or revision.result != {"schema_version": "control-file-set-result/1.0", **job.request}
        ):
            raise ControlPlaneError("CONTROL_FILE_SET_CONFLICT", "published file set differs")
        member_by_name = {value["file_name"]: value for value in members}
        primary = member_by_name[request["primary_file"]]
        if revision.content_hash != primary["sha256"] or revision.content_bytes != primary["bytes"]:
            raise ControlPlaneError("CONTROL_FILE_SET_CONFLICT", "published primary member differs")
        root = Path(revision.nas_path)
        try:
            root_metadata = root.lstat()
        except OSError as exc:
            raise ControlPlaneError(
                "CONTROL_FILE_SET_INCOMPLETE", "NAS revision is missing"
            ) from exc
        if root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
            raise ControlPlaneError("CONTROL_FILE_SET_INCOMPLETE", "NAS revision is missing")
        for member in members:
            target = root.joinpath(*PurePosixPath(member["file_name"]).parts)
            try:
                metadata = target.lstat()
            except OSError as exc:
                raise ControlPlaneError(
                    "CONTROL_FILE_SET_INCOMPLETE", "NAS member is invalid"
                ) from exc
            if target.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ControlPlaneError("CONTROL_FILE_SET_INCOMPLETE", "NAS member is invalid")
            if metadata.st_size != member["bytes"] or sha256_file(target) != member["sha256"]:
                raise ControlPlaneError("CONTROL_FILE_SET_INCOMPLETE", "NAS member is invalid")
        return PublishedControlFileSet(
            job_id=job.job_id,
            artifact_id=revision.logical_artifact_id,
            artifact_revision_id=revision.revision_id,
            primary_file=str(request["primary_file"]),
            primary_sha256=revision.content_hash,
            manifest_sha256=revision.manifest_hash,
            nas_path=revision.nas_path,
        )
