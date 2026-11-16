"""Private source adoption: reserve identity, validate/publish outside locks, then CAS.

No public intake endpoint or collector activation exists here. The installed
capture owner must supply current admission authority; DTO validity is not a grant.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization
from eom_catalog_contracts.kakao_media import KakaoMediaBlobReceipt
from eom_catalog_contracts.kakao_snapshot import KakaoRoomSnapshot
from eom_catalog_contracts.kakao_source import (
    SOURCE_RESOLUTION_REF,
    KakaoSourceAdmission,
    KakaoSourceResolution,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_room_scope,
)
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_question_editing import (
    KakaoAttachmentSource,
    ResolvedKakaoQuestionSource,
)
from eom_catalog_service.kakao_source_models import (
    KakaoSourceCommandRecord,
    KakaoSourceHeadRecord,
    KakaoSourceRevisionRecord,
)
from eom_catalog_service.kakao_source_pointers import (
    validate_source_pointer_metadata,
    validate_source_pointer_metadata_batch,
)
from eom_catalog_service.kakao_source_resolution import (
    build_source_resolution,
    validate_capture_source,
)

SourceAdmissionAuthorizer = Callable[[Session, ActorContext, KakaoSourceAdmission], None]
MAX_RESOLUTION_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AcceptedKakaoSource:
    resolution: KakaoSourceResolution
    manifest: ArtifactMemberPointer
    publication_job_id: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class AcceptedKakaoQuestionSource:
    """Resolved content plus its exact accepted closure for late metadata checks."""

    accepted: AcceptedKakaoSource
    resolved: ResolvedKakaoQuestionSource


@dataclass(frozen=True, slots=True)
class _Reservation:
    command_id: str
    source_revision_id: str
    reserved_at: datetime
    owner: str
    completed: bool


def source_admission_pointers(admission: KakaoSourceAdmission) -> tuple[ArtifactMemberPointer, ...]:
    authority = admission.authority
    values = (
        admission.source,
        admission.snapshot,
        admission.normalization,
        authority.command,
        authority.capability,
        authority.capture_report,
        authority.capture_result,
        *(
            pointer
            for attachment in admission.attachments
            for pointer in (attachment.original, attachment.media_receipt)
            if pointer is not None
        ),
    )
    return tuple(
        {
            (
                p.artifact_id,
                p.artifact_revision_id,
                p.member_path,
                p.schema_ref,
                p.media_type,
                p.sha256,
            ): p
            for p in values
        }.values()
    )


class KakaoSourceService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        authorize_capture: SourceAdmissionAuthorizer,
    ) -> None:
        if not callable(authorize_capture):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
        self._sessions = build_session_factory(engine)
        self._artifacts = artifacts
        self._authorize_capture = authorize_capture

    def _scope(
        self, session: Session, actor: ActorContext, binding_id: str, room_id: str, *, mutate: bool
    ) -> str:
        owner, _ = authorize_kakao_room_scope(
            session,
            actor,
            binding_id,
            room_id,
            PermissionKey.KAKAO_ARCHIVE_COLLECT if mutate else PermissionKey.KAKAO_ARCHIVE_READ,
            lock=mutate,
        )
        # DRAFT is not upgraded here. The mandatory actual capture owner alone can
        # approve the exact verified-channel/run/attempt authority below.
        return owner

    def _authority(
        self, session: Session, actor: ActorContext, admission: KakaoSourceAdmission
    ) -> None:
        try:
            self._authorize_capture(session, actor, admission)
        except KakaoArchiveError:
            raise
        except (PermissionError, ValueError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED") from None
        validate_source_pointer_metadata_batch(session, source_admission_pointers(admission))

    @staticmethod
    def _precondition(head: KakaoSourceHeadRecord, admission: KakaoSourceAdmission) -> None:
        if (head.current_source_revision_id, head.resource_version) != (
            admission.expected_source_revision_id,
            admission.expected_resource_version,
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

    def _reserve(
        self, actor: ActorContext, admission: KakaoSourceAdmission, key: str
    ) -> _Reservation:
        digest = kakao_command_sha256(admission)
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, "source/" + admission.room_id, key)
            self._scope(session, actor, admission.source_binding_id, admission.room_id, mutate=True)
            self._authority(session, actor, admission)
            prior = session.scalar(
                select(KakaoSourceCommandRecord).where(
                    KakaoSourceCommandRecord.owner_operator_id == owner,
                    KakaoSourceCommandRecord.room_id == admission.room_id,
                    KakaoSourceCommandRecord.idempotency_key == key,
                )
            )
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _Reservation(
                    prior.command_id,
                    prior.source_revision_id,
                    prior.reserved_at,
                    owner,
                    prior.state == "COMPLETED",
                )
            if (
                session.scalar(
                    select(KakaoSourceCommandRecord.command_id).where(
                        KakaoSourceCommandRecord.source_binding_id == admission.source_binding_id,
                        KakaoSourceCommandRecord.capture_attempt_id
                        == admission.authority.attempt_id,
                    )
                )
                is not None
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            head = session.get(KakaoSourceHeadRecord, admission.room_id)
            if head is None:
                head = KakaoSourceHeadRecord(
                    room_id=admission.room_id,
                    owner_operator_id=owner,
                    source_binding_id=admission.source_binding_id,
                    current_source_revision_id=None,
                    resource_version=0,
                )
                session.add(head)
            self._precondition(head, admission)
            reserved = _Reservation(
                "kakaocommand_" + uuid4().hex,
                "kakaosourcerev_" + uuid4().hex,
                datetime.now(UTC),
                owner,
                False,
            )
            session.add(
                KakaoSourceCommandRecord(
                    command_id=reserved.command_id,
                    owner_operator_id=owner,
                    source_binding_id=admission.source_binding_id,
                    room_id=admission.room_id,
                    idempotency_key=key,
                    request_sha256=digest,
                    capture_attempt_id=admission.authority.attempt_id,
                    source_revision_id=reserved.source_revision_id,
                    previous_revision_id=admission.expected_source_revision_id,
                    expected_resource_version=admission.expected_resource_version,
                    state="RESERVED",
                    reserved_at=reserved.reserved_at,
                    completed_at=None,
                )
            )
            return reserved

    def _check(self, actor: ActorContext, admission: KakaoSourceAdmission) -> None:
        with self._sessions.begin() as session:
            self._scope(session, actor, admission.source_binding_id, admission.room_id, mutate=True)
            self._authority(session, actor, admission)

    def _read(self, pointer: ArtifactMemberPointer, *, limit: int) -> bytes:
        try:
            payload = self._artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=limit,
            )
            if len(payload) > limit or sha256_bytes(payload) != pointer.sha256:
                raise ValueError("source hash mismatch")
            return payload
        except (ValueError, OSError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_ARTIFACT_UNAVAILABLE") from None

    def _inputs(self, admission: KakaoSourceAdmission) -> KakaoMessageNormalization:
        normalization = KakaoMessageNormalization.model_validate_json(
            self._read(admission.normalization, limit=128 * 1024 * 1024)
        )
        snapshot = KakaoRoomSnapshot.model_validate_json(
            self._read(admission.snapshot, limit=32768)
        )
        authority = admission.authority
        receipts = {}
        receipt_cache: dict[tuple[str, ...], KakaoMediaBlobReceipt] = {}
        original_sizes: dict[tuple[str, ...], int] = {}

        def identity(pointer: ArtifactMemberPointer) -> tuple[str, ...]:
            return (
                pointer.artifact_id,
                pointer.artifact_revision_id,
                pointer.member_path,
                pointer.schema_ref,
                pointer.media_type,
                pointer.sha256,
            )

        total_bytes = 0
        for attachment in admission.attachments:
            if attachment.media_receipt is not None and attachment.original is not None:
                receipt_key = identity(attachment.media_receipt)
                if receipt_key not in receipt_cache:
                    receipt_cache[receipt_key] = KakaoMediaBlobReceipt.model_validate_json(
                        self._read(attachment.media_receipt, limit=32768)
                    )
                receipt = receipt_cache[receipt_key]
                original_key = identity(attachment.original)
                if original_key not in original_sizes:
                    total_bytes += receipt.source_bytes
                    if total_bytes > 256 * 1024 * 1024:
                        raise ValueError("KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT")
                    original_sizes[original_key] = len(
                        self._read(attachment.original, limit=32 * 1024 * 1024)
                    )
                if original_sizes[original_key] != receipt.source_bytes:
                    raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_MEDIA_INVALID")
                receipts[attachment.attachment_id] = receipt
        validate_capture_source(
            admission,
            snapshot=snapshot,
            normalization=normalization,
            source=self._read(admission.source, limit=32 * 1024 * 1024),
            command_bytes=self._read(authority.command, limit=32768),
            capability_bytes=self._read(authority.capability, limit=128 * 1024),
            report_bytes=self._read(authority.capture_report, limit=4 * 1024 * 1024),
            result_bytes=self._read(authority.capture_result, limit=32768),
            media_receipts=receipts,
        )
        return normalization

    def admit_source(
        self, actor: ActorContext, admission: KakaoSourceAdmission, *, idempotency_key: str
    ) -> AcceptedKakaoSource:
        try:
            admission = KakaoSourceAdmission.model_validate(admission.model_dump(mode="json"))
            key = validate_kakao_idempotency_key(idempotency_key)
            reserved = self._reserve(actor, admission, key)
            if reserved.completed:
                accepted = self.get_source(
                    actor,
                    admission.source_binding_id,
                    admission.room_id,
                    source_revision_id=reserved.source_revision_id,
                )
                return AcceptedKakaoSource(
                    accepted.resolution, accepted.manifest, accepted.publication_job_id, True
                )
            normalization = self._inputs(admission)
            previous = None
            previous_normalization = None
            if admission.expected_source_revision_id is not None:
                previous = self.get_source(
                    actor,
                    admission.source_binding_id,
                    admission.room_id,
                    source_revision_id=admission.expected_source_revision_id,
                ).resolution
                previous_normalization = KakaoMessageNormalization.model_validate_json(
                    self._read(previous.admission.normalization, limit=128 * 1024 * 1024)
                )
            resolution = build_source_resolution(
                admission,
                normalization,
                source_revision_id=reserved.source_revision_id,
                command_id=reserved.command_id,
                owner=reserved.owner,
                reserved_at=reserved.reserved_at,
                previous=previous,
                previous_normalization=previous_normalization,
            )
            payload = canonical_json_bytes(resolution.model_dump(mode="json"))
            if len(payload) > MAX_RESOLUTION_BYTES:
                raise ValueError("KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT")
            self._check(actor, admission)
            with tempfile.TemporaryDirectory(
                prefix="kakao-source.", dir=self._artifacts.settings.staging_root
            ) as directory:
                path = Path(directory) / "resolution.json"
                with path.open("xb") as stream:
                    stream.write(payload)
                artifact = self._artifacts.commit_file_set(
                    files={"resolution.json": path},
                    primary_file="resolution.json",
                    artifact_type="kakao-source-resolution",
                    idempotency_key="kakao:source:" + reserved.source_revision_id,
                    request={
                        "source_revision_id": reserved.source_revision_id,
                        "command_id": reserved.command_id,
                        "source_binding_id": admission.source_binding_id,
                        "room_id": admission.room_id,
                        "request_sha256": kakao_command_sha256(admission),
                    },
                    result={
                        "row_count": len(resolution.rows),
                        "resolution_sha256": sha256_bytes(payload),
                    },
                    file_metadata={
                        "resolution.json": {
                            "schema_ref": SOURCE_RESOLUTION_REF,
                            "media_type": "application/json",
                        }
                    },
                    expected_file_sha256={"resolution.json": sha256_bytes(payload)},
                )
            if artifact.content_hash != sha256_bytes(payload) or artifact.content_bytes != len(
                payload
            ):
                raise ValueError("KAKAO_ARCHIVE_PUBLICATION_MISMATCH")
            pointer = ArtifactMemberPointer(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                member_path="resolution.json",
                schema_ref=SOURCE_RESOLUTION_REF,
                media_type="application/json",
                sha256=artifact.content_hash,
            )
            replayed = self._adopt(actor, resolution, pointer, artifact.job_id, key)
            return AcceptedKakaoSource(resolution, pointer, artifact.job_id, replayed)
        except KakaoArchiveError:
            raise
        except (AttributeError, ValueError, OSError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_INVALID") from None

    def _adopt(
        self,
        actor: ActorContext,
        resolution: KakaoSourceResolution,
        pointer: ArtifactMemberPointer,
        job_id: str,
        key: str,
    ) -> bool:
        admission = resolution.admission
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, "source/" + admission.room_id, key)
            self._scope(session, actor, admission.source_binding_id, admission.room_id, mutate=True)
            self._authority(session, actor, admission)
            command = session.get(KakaoSourceCommandRecord, resolution.command_id)
            if (
                command is None
                or command.owner_operator_id != owner
                or command.request_sha256 != kakao_command_sha256(admission)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            logical, revision = validate_source_pointer_metadata(session, pointer)
            if (
                logical.artifact_type != "kakao-source-resolution"
                or revision.job_id != job_id
                or revision.content_hash != pointer.sha256
                or revision.manifest.get("primary_file") != "resolution.json"
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
            if command.state == "COMPLETED":
                stored = session.get(KakaoSourceRevisionRecord, resolution.source_revision_id)
                if (
                    stored is None
                    or stored.manifest_sha256 != pointer.sha256
                    or stored.manifest_artifact_revision_id != pointer.artifact_revision_id
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID")
                return True
            head = session.get(KakaoSourceHeadRecord, admission.room_id)
            if head is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID")
            self._precondition(head, admission)
            session.add(
                KakaoSourceRevisionRecord(
                    source_revision_id=resolution.source_revision_id,
                    owner_operator_id=owner,
                    source_binding_id=admission.source_binding_id,
                    room_id=admission.room_id,
                    command_id=resolution.command_id,
                    previous_revision_id=admission.expected_source_revision_id,
                    resource_version=resolution.resource_version,
                    snapshot_revision_id=admission.snapshot_revision_id,
                    normalization_revision_id=admission.normalization_revision_id,
                    manifest_artifact_id=pointer.artifact_id,
                    manifest_artifact_revision_id=pointer.artifact_revision_id,
                    manifest_sha256=pointer.sha256,
                    publication_job_id=job_id,
                    row_count=len(resolution.rows),
                    observed_at=resolution.observed_at,
                    created_at=resolution.created_at,
                )
            )
            head.current_source_revision_id = resolution.source_revision_id
            head.resource_version = resolution.resource_version
            command.state = "COMPLETED"
            command.completed_at = datetime.now(UTC)
            return False

    def get_source(
        self, actor: ActorContext, source_binding_id: str, room_id: str, *, source_revision_id: str
    ) -> AcceptedKakaoSource:
        """Exact immutable revision read; no current/latest fallback and no runtime work."""
        with self._sessions.begin() as session:
            owner = self._scope(session, actor, source_binding_id, room_id, mutate=False)
            row = session.scalar(
                select(KakaoSourceRevisionRecord).where(
                    KakaoSourceRevisionRecord.source_revision_id == source_revision_id,
                    KakaoSourceRevisionRecord.owner_operator_id == owner,
                    KakaoSourceRevisionRecord.source_binding_id == source_binding_id,
                    KakaoSourceRevisionRecord.room_id == room_id,
                )
            )
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            pointer = ArtifactMemberPointer(
                artifact_id=row.manifest_artifact_id,
                artifact_revision_id=row.manifest_artifact_revision_id,
                member_path="resolution.json",
                schema_ref=SOURCE_RESOLUTION_REF,
                media_type="application/json",
                sha256=row.manifest_sha256,
            )
            validate_source_pointer_metadata(session, pointer)
            expected = (
                row.command_id,
                row.resource_version,
                row.snapshot_revision_id,
                row.normalization_revision_id,
                row.previous_revision_id,
                row.row_count,
                row.observed_at,
                row.created_at,
            )
            job_id = row.publication_job_id
        try:
            resolution = KakaoSourceResolution.model_validate_json(
                self._read(pointer, limit=MAX_RESOLUTION_BYTES)
            )
            admission = resolution.admission
            if (
                resolution.source_revision_id,
                resolution.created_by,
                admission.source_binding_id,
                admission.room_id,
            ) != (source_revision_id, owner, source_binding_id, room_id) or (
                resolution.command_id,
                resolution.resource_version,
                admission.snapshot_revision_id,
                admission.normalization_revision_id,
                admission.expected_source_revision_id,
                len(resolution.rows),
                resolution.observed_at,
                resolution.created_at,
            ) != expected:
                raise ValueError("stored resolution mismatch")
        except (ValueError, AttributeError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID") from None
        with self._sessions.begin() as session:
            self._scope(session, actor, source_binding_id, room_id, mutate=False)
            _, revision = validate_source_pointer_metadata(session, pointer)
            if revision.job_id != job_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID")
            validate_source_pointer_metadata_batch(session, source_admission_pointers(admission))
        return AcceptedKakaoSource(resolution, pointer, job_id)

    def resolve_question_source(
        self, actor: ActorContext, source_binding_id: str, room_id: str, *, source_revision_id: str
    ) -> ResolvedKakaoQuestionSource:
        """One exact accepted source, for reuse across all its selected questions.

        No owner handoff or latest fallback: the caller retains the same actor and
        resolves each distinct source revision once per bounded application request.
        """
        return self.resolve_question_source_context(
            actor, source_binding_id, room_id, source_revision_id=source_revision_id
        ).resolved

    def resolve_question_source_context(
        self, actor: ActorContext, source_binding_id: str, room_id: str, *, source_revision_id: str
    ) -> AcceptedKakaoQuestionSource:
        """Read once, retaining immutable source provenance for post-I/O adoption."""
        accepted = self.get_source(
            actor, source_binding_id, room_id, source_revision_id=source_revision_id
        )
        resolution = accepted.resolution
        admission = resolution.admission
        try:
            normalization = KakaoMessageNormalization.model_validate_json(
                self._read(admission.normalization, limit=128 * 1024 * 1024)
            )
            if (
                (
                    normalization.source_binding_id,
                    normalization.room_id,
                    normalization.snapshot_revision_id,
                    normalization.normalization_revision_id,
                )
                != (
                    source_binding_id,
                    room_id,
                    admission.snapshot_revision_id,
                    admission.normalization_revision_id,
                )
                or normalization.source_sha256 != admission.source.sha256
                or normalization.observed_at_utc != resolution.observed_at
                or tuple(message.row_ordinal for message in normalization.messages)
                != tuple(row.row_ordinal for row in resolution.rows)
            ):
                raise ValueError("accepted normalization identity mismatch")
            observations = {
                attachment.attachment_id: attachment
                for message in normalization.messages
                for attachment in message.attachments
            }
            if set(observations) != {
                attachment.attachment_id for attachment in admission.attachments
            }:
                raise ValueError("accepted attachment coverage mismatch")
            attachments = {}
            for attachment in admission.attachments:
                observation = observations[attachment.attachment_id]
                if observation.attachment_revision_id != attachment.attachment_revision_id or (
                    observation.availability == "available"
                ) != (attachment.original is not None):
                    raise ValueError("accepted attachment revision mismatch")
                if attachment.original is not None:
                    attachments[attachment.attachment_id] = KakaoAttachmentSource(
                        attachment.attachment_revision_id, attachment.original, attachment.quality
                    )
            resolved = ResolvedKakaoQuestionSource(
                normalization,
                admission.normalization,
                {row.row_ordinal: row.occurrence_id for row in resolution.rows},
                attachments,
            )
        except KakaoArchiveError:
            raise
        except (ValueError, AttributeError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID") from None
        # File I/O is complete. Recheck the actual owner's mutable access and the
        # same immutable source closure before returning any original content.
        with self._sessions.begin() as session:
            self._scope(session, actor, source_binding_id, room_id, mutate=False)
            validate_source_pointer_metadata_batch(
                session, (accepted.manifest, *source_admission_pointers(admission))
            )
        return AcceptedKakaoQuestionSource(accepted, resolved)

    def validate_question_source_metadata(
        self,
        session: Session,
        actor: ActorContext,
        contexts: tuple[AcceptedKakaoQuestionSource, ...],
    ) -> None:
        """Current source ACL/lifecycle in a caller's short transaction; no file I/O.

        Only already-resolved contexts enter here. Norm/image checks alone would
        miss withdrawal of the accepted resolution, raw snapshot or capture proof.
        """
        scopes = {
            (
                item.accepted.resolution.admission.source_binding_id,
                item.accepted.resolution.admission.room_id,
            )
            for item in contexts
        }
        owners = {
            (binding, room): self._scope(session, actor, binding, room, mutate=False)
            for binding, room in scopes
        }
        expected = {item.accepted.resolution.source_revision_id: item for item in contexts}
        if len(expected) != len(contexts):
            raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_DUPLICATED")
        rows = tuple(
            session.scalars(
                select(KakaoSourceRevisionRecord).where(
                    KakaoSourceRevisionRecord.source_revision_id.in_(tuple(expected))
                )
            )
        )
        if len(rows) != len(expected):
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        pointers: list[ArtifactMemberPointer] = []
        for row in rows:
            item = expected[row.source_revision_id]
            accepted, resolved = item.accepted, item.resolved
            admission = accepted.resolution.admission
            if (
                row.owner_operator_id != owners[(admission.source_binding_id, admission.room_id)]
                or (
                    row.source_binding_id,
                    row.room_id,
                    row.normalization_revision_id,
                    row.manifest_artifact_id,
                    row.manifest_artifact_revision_id,
                    row.manifest_sha256,
                    row.publication_job_id,
                )
                != (
                    admission.source_binding_id,
                    admission.room_id,
                    resolved.normalization.normalization_revision_id,
                    accepted.manifest.artifact_id,
                    accepted.manifest.artifact_revision_id,
                    accepted.manifest.sha256,
                    accepted.publication_job_id,
                )
                or resolved.pointer != admission.normalization
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_SOURCE_INVALID")
            pointers.extend((accepted.manifest, *source_admission_pointers(admission)))
        validate_source_pointer_metadata_batch(session, tuple(pointers))
