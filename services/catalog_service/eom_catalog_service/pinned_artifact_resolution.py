"""Read-only resolution of one immutable Artifact member inside a caller-owned DB snapshot."""

from __future__ import annotations

import os
import stat
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from threading import get_ident
from typing import Literal, cast

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel
from sqlalchemy import select, tuple_
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
    producer_job_id: str
    payload: bytes


class PinnedArtifactResolutionError(ValueError):
    """The pinned Artifact identity, provenance, manifest, or bytes did not resolve."""

    def __init__(
        self,
        message: str,
        *,
        descriptor_reason: str | None = None,
        artifact_id: str | None = None,
        artifact_revision_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = (
            "PINNED_ARTIFACT_DESCRIPTOR_" + descriptor_reason
            if descriptor_reason
            in {
                "HASH",
                "BYTES_TYPE",
                "NEGATIVE_BYTES",
                "EMPTY",
                "SIZE_LIMIT",
                "SCHEMA_MEDIA",
                "PRIMARY_HASH",
                "PRIMARY_BYTES",
            }
            else None
        )
        self.artifact_id = artifact_id
        self.artifact_revision_id = artifact_revision_id


def artifact_identity_hints(value: object) -> set[tuple[str, str]]:
    """Collect JSON pointer identities only, never validate or authorize a source."""
    found: set[tuple[str, str]] = set()
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            artifact, revision = node.get("artifact_id"), node.get("artifact_revision_id")
            if isinstance(artifact, str) and isinstance(revision, str):
                found.add((artifact, revision))
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return found


@dataclass(frozen=True)
class _ArtifactProvenance:
    logical_artifact_id: str
    revision_id: str
    producer_job_id: str
    artifact_type: str
    content_hash: str
    manifest_hash: str
    content_bytes: int
    nas_path: str


@dataclass(frozen=True)
class _CapturedArtifactMetadata:
    logical: ArtifactRecord
    revision: ArtifactRevisionRecord
    job: JobRecord | None
    manifest: dict[str, object]
    manifest_hash: str
    entry_count: int
    members: dict[str, tuple[dict[str, object], ...]]
    provenance: _ArtifactProvenance


def _capture_metadata(
    logical: ArtifactRecord, revision: ArtifactRevisionRecord, job: JobRecord | None
) -> _CapturedArtifactMetadata:
    manifest = revision.manifest
    files = manifest.get("files")
    if not isinstance(files, list):
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve")
    groups: dict[str, list[dict[str, object]]] = {}
    entries = tuple(value for value in files if isinstance(value, dict))
    for entry in entries:
        name = entry.get("file_name")
        if isinstance(name, str):
            groups.setdefault(name, []).append(entry)
    try:
        manifest_hash = content_sha256(manifest)
    except (TypeError, ValueError) as exc:
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve") from exc
    return _CapturedArtifactMetadata(
        logical,
        revision,
        job,
        manifest,
        manifest_hash,
        len(entries),
        {name: tuple(values) for name, values in groups.items()},
        _ArtifactProvenance(
            logical.logical_artifact_id,
            revision.revision_id,
            revision.job_id,
            logical.artifact_type,
            revision.content_hash,
            manifest_hash,
            revision.content_bytes,
            revision.nas_path,
        ),
    )


def _resolve_pinned_artifact_member(
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
    captured: _CapturedArtifactMetadata | None = None,
    materialized: PinnedArtifactMember | None = None,
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

    logical = session.get(ArtifactRecord, artifact_id) if captured is None else captured.logical
    revision = (
        session.get(ArtifactRevisionRecord, artifact_revision_id)
        if captured is None
        else captured.revision
    )
    job = (
        (session.get(JobRecord, revision.job_id) if revision is not None else None)
        if captured is None
        else captured.job
    )
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

    if captured is None:
        captured = _capture_metadata(logical, revision, job)
    manifest = captured.manifest
    files = manifest.get("files")
    if not isinstance(files, list):
        raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve")
    matches = captured.members.get(member_path, ())
    if (
        manifest.get("logical_artifact_id") != artifact_id
        or manifest.get("revision_id") != artifact_revision_id
        or manifest.get("job_id") != job.job_id
        or manifest.get("artifact_type") not in manifest_artifact_types
        or manifest.get("primary_file") != expected_primary_file
        or captured.manifest_hash != revision.manifest_hash
        or revision.manifest is not manifest
        or captured.entry_count != len(files)
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
    # Keep the same closed checks, with safe reason metadata instead of payload
    # text. Evaluate numeric comparisons only for an exact integer descriptor.
    descriptor_checks = (
        (entry.get("sha256") != sha256, "HASH"),
        (type(size) is not int, "BYTES_TYPE"),
        (type(size) is int and size < 0, "NEGATIVE_BYTES"),
        (size == 0 and (not allow_empty or member_path == expected_primary_file), "EMPTY"),
        (type(size) is int and size > max_bytes, "SIZE_LIMIT"),
        (not (metadata_matches or historical_contract), "SCHEMA_MEDIA"),
        (member_path == expected_primary_file and revision.content_hash != sha256, "PRIMARY_HASH"),
        (member_path == expected_primary_file and revision.content_bytes != size, "PRIMARY_BYTES"),
    )
    reason = next((reason for failed, reason in descriptor_checks if failed), None)
    if reason is not None:
        raise PinnedArtifactResolutionError(
            "pinned Artifact member descriptor differs",
            descriptor_reason=reason,
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
        )

    if materialized is not None:
        if (
            materialized.artifact_id,
            materialized.artifact_revision_id,
            materialized.member_path,
            materialized.sha256,
            materialized.schema_ref,
            materialized.media_type,
        ) != (
            artifact_id,
            artifact_revision_id,
            member_path,
            sha256,
            schema_ref,
            media_type,
        ) or len(materialized.payload) != size:
            raise PinnedArtifactResolutionError("pinned Artifact materialization differs")
        return materialized

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
        manifest_artifact_type=cast(str, manifest["artifact_type"]),
        approved=True,
        producing_job_state="SUCCEEDED",
        producer_job_id=revision.job_id,
        payload=payload,
    )


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
    """Preserved scalar boundary; metadata and file checks share one private leaf."""
    return _resolve_pinned_artifact_member(
        session,
        settings,
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path=member_path,
        sha256=sha256,
        schema_ref=schema_ref,
        media_type=media_type,
        expected_artifact_types=expected_artifact_types,
        expected_primary_file=expected_primary_file,
        max_bytes=max_bytes,
        expected_manifest_artifact_types=expected_manifest_artifact_types,
        historical_metadata_compatibility=historical_metadata_compatibility,
        allow_empty=allow_empty,
    )


@dataclass(frozen=True)
class _DecodedArtifactMember:
    decoder: object
    value: BaseModel
    byte_charge: int


def _deeply_immutable(value: BaseModel) -> bool:
    """Frozen roots with mutable nested fields cannot safely be shared by readers."""
    pending: list[object] = [value]
    visited: set[int] = set()
    while pending:
        node = pending.pop()
        if node is None or isinstance(
            node, (str, bytes, int, float, date, datetime, time, timedelta)
        ):
            continue
        if id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, BaseModel):
            if not node.model_config.get("frozen") or node.__pydantic_private__ or node.model_extra:
                return False
            pending.extend(node.__dict__.values())
        elif isinstance(node, (tuple, frozenset)):
            pending.extend(node)
        else:
            return False
    return True


class PinnedArtifactReadContext:
    """Bounded root-Session immutable decoding reuse, never a permission cache.

    Prefetch exact metadata in sets before public reads. No lazy per-pointer SQL
    or exported validated flag exists. Owners revalidate mutable provenance at the
    late handoff boundary; current source/IAM/policy checks stay with Catalog.
    """

    MAX_REVISIONS = 4096
    MAX_MEMBERS = 8192
    MAX_RETAINED_BYTES = 128 * 1024**2
    MAX_DECODED_BYTES = 32 * 1024**2
    MAX_DECODED_MEMBERS = 2048

    def __init__(self, session: Session, settings: CatalogSettings) -> None:
        root = session.get_transaction()
        if root is None or not root.is_active:
            raise PinnedArtifactResolutionError("pinned Artifact read transaction is invalid")
        self._session = session
        self._root = root
        self._thread_id = get_ident()
        self.settings = settings
        self._metadata: dict[tuple[str, str], _CapturedArtifactMetadata] = {}
        self._members: OrderedDict[tuple[str, str, str, str, str, str], PinnedArtifactMember] = (
            OrderedDict()
        )
        self._seen_members: set[tuple[str, str, str, str, str, str]] = set()
        self._retained_bytes = 0
        self._decoded: OrderedDict[tuple[str, str, str, str, str, str], _DecodedArtifactMember] = (
            OrderedDict()
        )
        self._decoded_bytes = 0

    def require_session(self, session: Session) -> None:
        if (
            session is not self._session
            or session.get_transaction() is not self._root
            or not self._root.is_active
            or self._thread_id != get_ident()
        ):
            raise PinnedArtifactResolutionError("pinned Artifact read transaction is invalid")

    def prefetch(self, identities: tuple[tuple[str, str], ...]) -> None:
        self.require_session(self._session)
        selected = tuple(sorted(set(identities).difference(self._metadata)))
        if len(self._metadata) + len(selected) > self.MAX_REVISIONS:
            raise PinnedArtifactResolutionError("pinned Artifact metadata budget is exceeded")
        if not selected:
            return
        revisions = tuple(
            self._session.scalars(
                select(ArtifactRevisionRecord)
                .where(
                    tuple_(
                        ArtifactRevisionRecord.logical_artifact_id,
                        ArtifactRevisionRecord.revision_id,
                    ).in_(selected)
                )
                .execution_options(populate_existing=True)
            )
        )
        logicals = {
            row.logical_artifact_id: row
            for row in self._session.scalars(
                select(ArtifactRecord)
                .where(
                    ArtifactRecord.logical_artifact_id.in_(
                        tuple(sorted({key[0] for key in selected}))
                    )
                )
                .execution_options(populate_existing=True)
            )
        }
        jobs = {
            row.job_id: row
            for row in self._session.scalars(
                select(JobRecord)
                .where(JobRecord.job_id.in_(tuple(sorted({row.job_id for row in revisions}))))
                .execution_options(populate_existing=True)
            )
        }
        found = {(row.logical_artifact_id, row.revision_id) for row in revisions}
        if found != set(selected):
            missing = sorted(set(selected) - found)
            raise PinnedArtifactResolutionError(
                "pinned Artifact provenance does not resolve",
                artifact_id=missing[0][0] if missing else None,
                artifact_revision_id=missing[0][1] if missing else None,
            )
        captured = {}
        for revision in revisions:
            logical = logicals.get(revision.logical_artifact_id)
            if logical is None:
                raise PinnedArtifactResolutionError("pinned Artifact provenance does not resolve")
            captured[(revision.logical_artifact_id, revision.revision_id)] = _capture_metadata(
                logical, revision, jobs.get(revision.job_id)
            )
        self._metadata.update(captured)

    def revalidate_provenance(self) -> None:
        """Refresh only small current lineage/lifecycle values, not immutable bytes/JSON.

        READ COMMITTED alone does not refresh captured ORM objects. This explicit
        boundary is three indexed batches regardless of member count, not an
        authority cache or a new locking/permission requirement.
        """
        self.require_session(self._session)
        if any(
            isinstance(row, (ArtifactRecord, ArtifactRevisionRecord, JobRecord))
            for rows in (self._session.new, self._session.dirty, self._session.deleted)
            for row in rows
        ):
            raise PinnedArtifactResolutionError("pinned Artifact read has pending mutations")
        if not self._metadata:
            return
        logical_ids = tuple(sorted({key[0] for key in self._metadata}))
        revision_ids = tuple(sorted({key[1] for key in self._metadata}))
        job_ids = tuple(
            sorted({value.provenance.producer_job_id for value in self._metadata.values()})
        )
        with self._session.no_autoflush:
            logicals = {
                row.logical_artifact_id: (row.job_id, row.artifact_type, row.approved)
                for row in self._session.execute(
                    select(
                        ArtifactRecord.logical_artifact_id,
                        ArtifactRecord.job_id,
                        ArtifactRecord.artifact_type,
                        ArtifactRecord.approved,
                    ).where(ArtifactRecord.logical_artifact_id.in_(logical_ids))
                )
            }
            revisions = {
                (row.logical_artifact_id, row.revision_id): (
                    row.job_id,
                    row.content_hash,
                    row.manifest_hash,
                    row.content_bytes,
                    row.nas_path,
                    row.approved,
                )
                for row in self._session.execute(
                    select(
                        ArtifactRevisionRecord.logical_artifact_id,
                        ArtifactRevisionRecord.revision_id,
                        ArtifactRevisionRecord.job_id,
                        ArtifactRevisionRecord.content_hash,
                        ArtifactRevisionRecord.manifest_hash,
                        ArtifactRevisionRecord.content_bytes,
                        ArtifactRevisionRecord.nas_path,
                        ArtifactRevisionRecord.approved,
                    ).where(ArtifactRevisionRecord.revision_id.in_(revision_ids))
                )
            }
            jobs = {
                row.job_id: (row.logical_artifact_id, row.revision_id, row.task_type, row.status)
                for row in self._session.execute(
                    select(
                        JobRecord.job_id,
                        JobRecord.logical_artifact_id,
                        JobRecord.revision_id,
                        JobRecord.task_type,
                        JobRecord.status,
                    ).where(JobRecord.job_id.in_(job_ids))
                )
            }
        if (
            set(logicals) != set(logical_ids)
            or set(revisions) != set(self._metadata)
            or set(jobs) != set(job_ids)
        ):
            raise PinnedArtifactResolutionError("pinned Artifact current provenance is missing")
        for identity, captured in self._metadata.items():
            original = captured.provenance
            if (
                logicals[identity[0]] != (original.producer_job_id, original.artifact_type, True)
                or revisions[identity]
                != (
                    original.producer_job_id,
                    original.content_hash,
                    original.manifest_hash,
                    original.content_bytes,
                    original.nas_path,
                    True,
                )
                or jobs[original.producer_job_id]
                != (
                    original.logical_artifact_id,
                    original.revision_id,
                    original.artifact_type,
                    "SUCCEEDED",
                )
            ):
                raise PinnedArtifactResolutionError("pinned Artifact current provenance differs")

    def require_file_set(
        self,
        artifact_id: str,
        revision_id: str,
        names: tuple[str, ...],
        *,
        manifest_version: str | None = None,
        manifest_sha256: str | None = None,
    ) -> None:
        """Check one fixed owner member closure; this is not source authorization."""
        self.require_session(self._session)
        captured = self._metadata.get((artifact_id, revision_id))
        if (
            captured is None
            or (
                manifest_version is not None
                and captured.manifest.get("manifest_version") != manifest_version
            )
            or (manifest_sha256 is not None and captured.manifest_hash != manifest_sha256)
            or captured.entry_count != len(captured.members)
            or set(captured.members) != set(names)
            or any(len(values) != 1 for values in captured.members.values())
        ):
            raise PinnedArtifactResolutionError("pinned Artifact member set differs")

    def member_pointer(
        self,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        *,
        schema_ref: str,
        media_type: str,
    ) -> ArtifactMemberPointer:
        """Resolve a descriptor pointer; callers must still read/verify its bytes."""
        self.require_session(self._session)
        captured = self._metadata.get((artifact_id, revision_id))
        descriptors = () if captured is None else captured.members.get(member_path, ())
        if (
            len(descriptors) != 1
            or descriptors[0].get("schema_ref") != schema_ref
            or descriptors[0].get("media_type") != media_type
        ):
            raise PinnedArtifactResolutionError("pinned Artifact member descriptor differs")
        return ArtifactMemberPointer.model_validate(
            {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": member_path,
                "schema_ref": schema_ref,
                "media_type": media_type,
                "sha256": descriptors[0].get("sha256"),
            }
        )

    def read_pinned(
        self,
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
    ) -> PinnedArtifactMember:
        self.require_session(self._session)
        captured = self._metadata.get((artifact_id, artifact_revision_id))
        if captured is None:
            raise PinnedArtifactResolutionError("pinned Artifact metadata was not captured")
        key = artifact_id, artifact_revision_id, member_path, sha256, schema_ref, media_type
        cached = self._members.get(key)
        if cached is None:
            if key not in self._seen_members and len(self._seen_members) >= self.MAX_MEMBERS:
                raise PinnedArtifactResolutionError("pinned Artifact member budget is exceeded")
            descriptors = captured.members.get(member_path, ())
            size = descriptors[0].get("bytes") if len(descriptors) == 1 else None
            if type(size) is int and size > self.MAX_RETAINED_BYTES:
                raise PinnedArtifactResolutionError("pinned Artifact byte budget is exceeded")
            # Retention is a memory bound, not a corpus-size admission limit.
            # Evicted bytes must pass the same physical checks on their next use.
            while type(size) is int and self._retained_bytes + size > self.MAX_RETAINED_BYTES:
                _evicted_key, evicted = self._members.popitem(last=False)
                self._retained_bytes -= len(evicted.payload)
                # Typed values have their own bounded LRU. Model reads still
                # resolve exact bytes before a hit, even after raw eviction.
        member = _resolve_pinned_artifact_member(
            self._session,
            self.settings,
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
            member_path=member_path,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            expected_artifact_types=expected_artifact_types,
            expected_primary_file=expected_primary_file,
            max_bytes=max_bytes,
            expected_manifest_artifact_types=expected_manifest_artifact_types,
            captured=captured,
            materialized=cached,
        )
        if cached is not None:
            self._members.move_to_end(key)
            return member
        if self._retained_bytes + len(member.payload) > self.MAX_RETAINED_BYTES:
            raise PinnedArtifactResolutionError("pinned Artifact byte budget is exceeded")
        self._members[key] = member
        self._seen_members.add(key)
        self._retained_bytes += len(member.payload)
        return member

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
        self.require_session(self._session)
        captured = self._metadata.get((artifact_id, revision_id))
        if captured is None:
            raise PinnedArtifactResolutionError("pinned Artifact metadata was not captured")
        primary = captured.manifest.get("primary_file")
        manifest_type = captured.manifest.get("artifact_type")
        if not isinstance(primary, str) or not isinstance(manifest_type, str):
            raise PinnedArtifactResolutionError("pinned Artifact manifest does not resolve")
        return self.read_pinned(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            expected_artifact_types=(captured.logical.artifact_type,),
            expected_manifest_artifact_types=(manifest_type,),
            expected_primary_file=primary,
            max_bytes=max_bytes,
        ).payload

    def read_model_member[Model: BaseModel](
        self,
        pointer: ArtifactMemberPointer,
        *,
        expected_bytes: int,
        decoder: Callable[[str, bytes], Model],
    ) -> Model:
        """Reuse only immutable decoding, never member/provenance/current authority checks."""
        if type(expected_bytes) is not int or expected_bytes < 1:
            raise PinnedArtifactResolutionError("pinned Artifact member byte count is invalid")
        payload = self.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=expected_bytes,
        )
        if len(payload) != expected_bytes:
            raise PinnedArtifactResolutionError("pinned Artifact member byte count differs")
        key = (
            pointer.artifact_id,
            pointer.artifact_revision_id,
            pointer.member_path,
            pointer.sha256,
            pointer.schema_ref,
            pointer.media_type,
        )
        return self._decode_immutable(key, pointer.schema_ref, payload, decoder)

    def decode_model_value[Model: BaseModel](
        self,
        schema_ref: str,
        value: object,
        *,
        decoder: Callable[[str, bytes], Model],
    ) -> Model:
        """Interpret exact current JSON; never retain its dictionary or authority.

        Hash the complete current value on each call, so changed DB metadata
        cannot inherit an earlier interpretation merely by keeping its row ID.
        Artifact raw hashes remain separate from this temporary semantic key.
        """
        self.require_session(self._session)
        payload = canonical_json_bytes(value)
        key = ("canonical-json", schema_ref, sha256_bytes(payload), "", "", "")
        return self._decode_immutable(key, schema_ref, payload, decoder)

    def _decode_immutable[Model: BaseModel](
        self,
        key: tuple[str, str, str, str, str, str],
        schema_ref: str,
        payload: bytes,
        decoder: Callable[[str, bytes], Model],
    ) -> Model:
        cached = self._decoded.get(key)
        if cached is not None and cached.decoder is decoder:
            self._decoded.move_to_end(key)
            return cast(Model, cached.value)
        # A different decoder must not inherit the previous interpretation, even
        # if its own validation fails or returns a mutable model.
        if cached is not None:
            self._decoded_bytes -= self._decoded.pop(key).byte_charge
        value = decoder(schema_ref, payload)
        if (
            len(payload) <= self.MAX_DECODED_BYTES
            and self.MAX_DECODED_MEMBERS > 0
            and _deeply_immutable(value)
        ):
            while self._decoded and (
                len(self._decoded) >= self.MAX_DECODED_MEMBERS
                or self._decoded_bytes + len(payload) > self.MAX_DECODED_BYTES
            ):
                _key, evicted = self._decoded.popitem(last=False)
                self._decoded_bytes -= evicted.byte_charge
            self._decoded[key] = _DecodedArtifactMember(decoder, value, len(payload))
            self._decoded_bytes += len(payload)
        return value

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
        self.read_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            max_bytes=max_bytes,
        )


__all__ = [
    "PinnedArtifactMember",
    "PinnedArtifactReadContext",
    "PinnedArtifactResolutionError",
    "artifact_identity_hints",
    "resolve_pinned_artifact_member",
]
