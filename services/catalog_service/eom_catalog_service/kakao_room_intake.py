"""Current-owner confirmation of a captured room through existing publication/admission.

No browser actions, new work queue or source/capability activation occur here.
The command pins a MANUAL lease and capture; the installed input adapter chooses
the protected root/UID/GID. Completed replays resolve canonical evidence instead
of requiring the worker's temporary materialization forever.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.kakao_capture_intake import manual_capture_preview_sha256
from eom_catalog_contracts.kakao_room_intake import (
    CSV_POPUP_ROOM_EVIDENCE_REF,
    MANUAL_ROOM_EVIDENCE_REF,
    MANUAL_ROOM_EVIDENCE_REFS,
    ConfirmKakaoManualRoom,
    KakaoCsvPopupRoomEvidence,
    KakaoManualRoomEvidence,
    ManualRoomEvidence,
    manual_channel_identity_sha256,
    manual_room_evidence_type,
    manual_room_identity_sha256,
    observed_manual_room_keys,
)
from eom_catalog_contracts.kakao_rooms import (
    ROOM_OBSERVATION_REF,
    KakaoRoomMutation,
    KakaoRoomObservation,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_observation import MANUAL_PAGE_OBSERVATION_REF
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.kakao_download_inputs import KakaoDownloadInputError, ReceivedKakaoDownload
from eom_orchestrator.repository import IdempotencyConflict
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_csv_parser import read_kakao_csv_messages
from .kakao_manual_capture_access import OwnedManualCaptureRun, authorize_owned_manual_capture
from .kakao_room_csv_identity import observed_csv_popup_room_keys
from .kakao_room_intake_models import KakaoManualChannelPinRecord
from .kakao_room_models import KakaoRoomAdmissionRecord
from .kakao_room_service import KakaoRoomService
from .kakao_source_pointers import (
    resolve_pinned_kakao_json_member,
    validate_source_pointer_metadata_batch,
)

DownloadReader = Callable[[ProfileFence, str], ReceivedKakaoDownload]
_RECEIPT_REF = "eom://schemas/kakao-archive/manual-download-v1/1.0"


@dataclass(frozen=True, slots=True)
class AcceptedKakaoRoomConfirmation:
    proof: ManualRoomEvidence
    observation: KakaoRoomObservation
    evidence: ArtifactMemberPointer


def room_confirmation_preview_sha256(proof: ManualRoomEvidence) -> str:
    command = proof.confirmation
    return manual_capture_preview_sha256(
        owner=proof.owner_operator_id,
        binding=command.source_binding_id,
        lease=command.manual_lease_id,
        capture=command.capture_id,
        receipt_sha256=proof.receipt_sha256,
        observation_sha256=proof.observation_sha256,
        room_identity_sha256=proof.source_identity_sha256,
    )


class KakaoRoomIntakeService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        rooms: KakaoRoomService,
        read_download: DownloadReader,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self.artifacts, self.rooms, self._read_download = artifacts, rooms, read_download

    def _context(
        self, actor: ActorContext, command: ConfirmKakaoManualRoom
    ) -> OwnedManualCaptureRun:
        with self._sessions.begin() as session:
            return authorize_owned_manual_capture(session, actor, command)

    @staticmethod
    def _evidence(
        context: OwnedManualCaptureRun,
        command: ConfirmKakaoManualRoom,
        captured: ReceivedKakaoDownload,
    ) -> ManualRoomEvidence:
        receipt, observation = captured.receipt, captured.observation
        if (
            receipt.phase != "RECEIVED"
            or receipt.member is None
            or receipt.capture_id != command.capture_id
            or not captured.receipt_bytes
            or observation is None
            or observation.status != "OBSERVED"
            or observation.document is None
            or captured.observation_bytes is None
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_IDENTITY_UNAVAILABLE")
        method: type[KakaoManualRoomEvidence] | type[KakaoCsvPopupRoomEvidence] = (
            KakaoManualRoomEvidence
        )
        if observation.target.kind == "BLOB":
            method = KakaoCsvPopupRoomEvidence
            keys = observed_csv_popup_room_keys(observation)
            if keys is not None:
                try:
                    csv = read_kakao_csv_messages(captured.payload)
                    if not csv.messages or (csv.source_sha256, csv.source_bytes) != (
                        receipt.member.sha256,
                        receipt.member.size_bytes,
                    ):
                        keys = None
                except ValueError:
                    keys = None
        else:
            keys = observed_manual_room_keys(
                observation.document.path, observation.target.path or ""
            )
        if keys is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_IDENTITY_UNAVAILABLE")
        if keys != (command.expected_channel_key, command.expected_room_key):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_IDENTITY_MISMATCH")
        shared = ("capture_id", "profile_id", "browser_run_id", "fence_epoch", "page_instance_id")
        if any(getattr(receipt, name) != getattr(observation, name) for name in shared):
            raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE")
        result = method(
            owner_operator_id=context.owner,
            confirmation=command,
            request_sha256=kakao_command_sha256(command),
            profile_id=receipt.profile_id,
            browser_run_id=receipt.browser_run_id,
            fence_epoch=receipt.fence_epoch,
            page_instance_id=receipt.page_instance_id,
            capture_started_at=receipt.started_at,
            observed_at=observation.observed_at,
            capture_completed_at=receipt.completed_at,
            payload_sha256=receipt.member.sha256,
            payload_bytes=receipt.member.size_bytes,
            receipt_sha256=sha256_bytes(captured.receipt_bytes),
            observation_sha256=sha256_bytes(captured.observation_bytes),
            source_identity_sha256=manual_room_identity_sha256(*keys),
        )
        context.validate_evidence(result)
        return result

    def _read_model[T: BaseModel](
        self, pointer: ArtifactMemberPointer, schema: str, model: type[T], *, limit: int = 32768
    ) -> T:
        if pointer.schema_ref != schema or pointer.media_type != "application/json":
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        try:
            opened = self.artifacts.open_verified_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                schema_ref=schema,
                media_type="application/json",
                max_bytes=limit,
            )
            with opened.stream as stream:
                raw = stream.read(limit + 1)
            if len(raw) != opened.content_length or sha256_bytes(raw) != pointer.sha256:
                raise ValueError("invalid read")
            return model.model_validate_json(raw)
        except (OSError, ValueError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID") from None

    def _publish(
        self,
        *,
        files: dict[str, bytes],
        primary: str,
        kind: str,
        key: str,
        schemas: dict[str, str],
        request: dict[str, str],
        authorize: Callable[[], None],
    ) -> ArtifactMemberPointer:
        authorize()
        with tempfile.TemporaryDirectory(
            prefix="kakao-room-input.", dir=self.artifacts.settings.staging_root
        ) as folder:
            root = Path(folder)
            for name, raw in files.items():
                with (root / name).open("xb") as stream:
                    stream.write(raw)
            authorize()
            artifact = self.artifacts.commit_file_set(
                files={name: root / name for name in files},
                primary_file=primary,
                artifact_type=kind,
                idempotency_key=key,
                request=request,
                result={"sha256": sha256_bytes(files[primary])},
                file_metadata={
                    name: {"schema_ref": schemas[name], "media_type": "application/json"}
                    for name in files
                },
                expected_file_sha256={name: sha256_bytes(raw) for name, raw in files.items()},
            )
        if artifact.content_hash != sha256_bytes(files[primary]):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        return ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=primary,
            schema_ref=schemas[primary],
            media_type="application/json",
            sha256=artifact.content_hash,
        )

    def get_confirmation(
        self, actor: ActorContext, source_binding_id: str, *, idempotency_key: str
    ) -> AcceptedKakaoRoomConfirmation | None:
        prior = self.rooms.get_admission_evidence(
            actor, source_binding_id, idempotency_key=idempotency_key
        )
        if prior is None:
            return None
        observation = self._read_model(prior, ROOM_OBSERVATION_REF, KakaoRoomObservation)
        source_evidence = observation.source_evidence
        try:
            proof_type = manual_room_evidence_type(source_evidence.schema_ref)
        except ValueError:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID") from None
        proof = self._read_model(source_evidence, source_evidence.schema_ref, proof_type)
        with self._sessions.begin() as session:
            current = authorize_owned_manual_capture(session, actor, proof.confirmation)
            current.validate_evidence(proof)
            if (
                proof.confirmation.source_binding_id,
                observation.source_binding_id,
                observation.source_identity_sha256,
                observation.display_name,
            ) != (
                source_binding_id,
                source_binding_id,
                proof.source_identity_sha256,
                proof.confirmation.display_name,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
            validate_source_pointer_metadata_batch(session, (prior, observation.source_evidence))
        return AcceptedKakaoRoomConfirmation(proof, observation, prior)

    def confirm_room(
        self,
        actor: ActorContext,
        command: ConfirmKakaoManualRoom,
        *,
        idempotency_key: str,
        expected_preview_sha256: str | None = None,
    ) -> KakaoRoomMutation:
        command = ConfirmKakaoManualRoom.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        prior = self.get_confirmation(actor, command.source_binding_id, idempotency_key=key)
        if prior is not None:
            proof, observation, evidence = prior.proof, prior.observation, prior.evidence
            if proof.confirmation != command:
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            if (
                expected_preview_sha256 is not None
                and room_confirmation_preview_sha256(proof) != expected_preview_sha256
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
        else:
            context = self._context(actor, command)
            if context.binding_version != command.expected_binding_version:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            try:
                captured = self._read_download(context.fence, command.capture_id)
            except KakaoDownloadInputError:
                raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE") from None
            proof = self._evidence(context, command, captured)
            if (
                expected_preview_sha256 is not None
                and room_confirmation_preview_sha256(proof) != expected_preview_sha256
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

            def authorize() -> None:
                current = self._context(actor, command)
                current.validate_evidence(proof)
                if current.binding_version != command.expected_binding_version:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

            scope = sha256_bytes(
                canonical_json_bytes(
                    dict(owner=context.owner, binding=command.source_binding_id, key=key)
                )
            )[7:]
            metadata = dict(
                owner=context.owner,
                binding=command.source_binding_id,
                request_sha256=proof.request_sha256,
            )
            assert captured.observation_bytes is not None
            try:
                source = self._publish(
                    files={
                        "proof.json": canonical_json_bytes(proof.model_dump(mode="json")),
                        "download.json": captured.receipt_bytes,
                        "page-observation.json": captured.observation_bytes,
                    },
                    primary="proof.json",
                    kind="kakao-room-intake-evidence",
                    key="kakao:room-source:" + scope,
                    schemas={
                        "proof.json": (
                            CSV_POPUP_ROOM_EVIDENCE_REF
                            if isinstance(proof, KakaoCsvPopupRoomEvidence)
                            else MANUAL_ROOM_EVIDENCE_REF
                        ),
                        "download.json": _RECEIPT_REF,
                        "page-observation.json": MANUAL_PAGE_OBSERVATION_REF,
                    },
                    request=metadata,
                    authorize=authorize,
                )
                observation = KakaoRoomObservation(
                    source_binding_id=command.source_binding_id,
                    proposed_room_id=None,
                    identity_level="MANUAL_CONFIRMED",
                    source_identity_sha256=proof.source_identity_sha256,
                    display_name=command.display_name,
                    observed_at=proof.observed_at,
                    source_evidence=source,
                )
                evidence = self._publish(
                    files={
                        "observation.json": canonical_json_bytes(
                            observation.model_dump(mode="json")
                        )
                    },
                    primary="observation.json",
                    kind="kakao-room-identity",
                    key="kakao:room-identity:" + scope,
                    schemas={"observation.json": ROOM_OBSERVATION_REF},
                    request=metadata | {"source_sha256": source.sha256},
                    authorize=authorize,
                )
            except IdempotencyConflict:
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT") from None

        def authority(
            session: Session,
            current_actor: ActorContext,
            proposed: KakaoRoomObservation,
            pointer: ArtifactMemberPointer,
        ) -> None:
            current = authorize_owned_manual_capture(session, current_actor, command)
            current.validate_evidence(proof)
            if (
                proof.confirmation != command
                or current.owner != proof.owner_operator_id
                or proposed != observation
                or pointer != evidence
                or observation.source_binding_id != command.source_binding_id
                or observation.source_identity_sha256 != proof.source_identity_sha256
                or observation.identity_level != "MANUAL_CONFIRMED"
                or observation.display_name != command.display_name
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
            completed = session.scalar(
                select(KakaoRoomAdmissionRecord.command_id).where(
                    KakaoRoomAdmissionRecord.owner_operator_id == current.owner,
                    KakaoRoomAdmissionRecord.source_binding_id == command.source_binding_id,
                    KakaoRoomAdmissionRecord.idempotency_key == key,
                )
            )
            if completed is None and current.binding_version != command.expected_binding_version:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            lock_kakao_intent(
                session, current.owner, "manual-channel-pin", command.source_binding_id
            )
            pin = session.get(KakaoManualChannelPinRecord, command.source_binding_id)
            channel_hash = manual_channel_identity_sha256(command.expected_channel_key)
            if pin is None:
                session.add(
                    KakaoManualChannelPinRecord(
                        source_binding_id=command.source_binding_id,
                        owner_operator_id=current.owner,
                        channel_key_sha256=channel_hash,
                        evidence_artifact_id=observation.source_evidence.artifact_id,
                        evidence_artifact_revision_id=observation.source_evidence.artifact_revision_id,
                        evidence_sha256=observation.source_evidence.sha256,
                        created_at=datetime.now(UTC),
                    )
                )
            else:
                if pin.owner_operator_id != current.owner or pin.channel_key_sha256 != channel_hash:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_CHANNEL_IDENTITY_MISMATCH")
                resolve_pinned_kakao_json_member(
                    session,
                    artifact_id=pin.evidence_artifact_id,
                    revision_id=pin.evidence_artifact_revision_id,
                    member_path="proof.json",
                    sha256=pin.evidence_sha256,
                    permitted_schemas=MANUAL_ROOM_EVIDENCE_REFS,
                )

        return self.rooms.admit_room(
            actor,
            observation,
            evidence=evidence,
            idempotency_key=key,
            authorize_observation=authority,
        )
