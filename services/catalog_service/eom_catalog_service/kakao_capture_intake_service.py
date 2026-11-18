"""Expose bounded receipt metadata and confirm a room through its existing owner.

No browser actions, payload listing, source adoption or collection activation.
Readers are composition-owned local input adapters, never paths supplied by clients.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from eom_catalog_contracts.kakao_capture_intake import (
    ConfirmKakaoManualCapture,
    KakaoManualCaptureItem,
    KakaoManualCapturePage,
    manual_capture_preview_sha256,
)
from eom_catalog_contracts.kakao_room_intake import (
    ConfirmKakaoManualRoom,
    manual_room_identity_sha256,
    observed_manual_room_keys,
)
from eom_catalog_contracts.kakao_rooms import KakaoRoomMutation
from eom_identifiers import sha256_bytes
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.kakao_download_inputs import (
    KakaoDownloadInputError,
    KakaoDownloadMetadata,
    ReceivedKakaoDownload,
)
from sqlalchemy import Engine

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_archive_commands import validate_kakao_idempotency_key
from .kakao_csv_parser import read_kakao_csv_messages
from .kakao_manual_capture_access import (
    OwnedManualCaptureRun,
    authorize_owned_manual_capture_run,
    recent_owned_manual_captures,
)
from .kakao_photo_alignment import KakaoPhotoOccurrence, infer_kakao_photo_occurrence
from .kakao_room_intake import DownloadReader, KakaoRoomIntakeService

MetadataReader = Callable[[ProfileFence, str], KakaoDownloadMetadata]
CaptureIdsReader = Callable[[ProfileFence], tuple[tuple[str, ...], bool]]


def _observed_keys(metadata: KakaoDownloadMetadata) -> tuple[str, str] | None:
    observed = metadata.observation
    if observed is None or observed.status != "OBSERVED" or observed.document is None:
        return None
    return observed_manual_room_keys(observed.document.path, observed.target.path or "")


def _preview(
    run: OwnedManualCaptureRun, binding: str, metadata: KakaoDownloadMetadata
) -> KakaoManualCaptureItem:
    receipt = metadata.receipt
    fields = dict(
        manual_lease_id=run.lease_id,
        capture_id=metadata.started.capture_id,
        started_at=metadata.started.started_at,
        completed_at=None if receipt is None else receipt.completed_at,
        size_bytes=None if receipt is None or receipt.member is None else receipt.member.size_bytes,
        preview_sha256=None,
    )
    if receipt is None:
        state = "NOT_RECEIVED"
    elif receipt.phase != "RECEIVED":
        state = "TRANSFER_FAILED"
    elif metadata.observation is None:
        state = "NO_OBSERVATION"
    else:
        run.validate_transfer_interval(receipt.started_at, receipt.completed_at)
        keys = _observed_keys(metadata)
        if keys is None or metadata.receipt_bytes is None or metadata.observation_bytes is None:
            state = "ROOM_IDENTITY_UNAVAILABLE"
        else:
            state = "ROOM_IDENTITY_OBSERVED"
            fields["preview_sha256"] = manual_capture_preview_sha256(
                owner=run.owner,
                binding=binding,
                lease=run.lease_id,
                capture=receipt.capture_id,
                receipt_sha256=sha256_bytes(metadata.receipt_bytes),
                observation_sha256=sha256_bytes(metadata.observation_bytes),
                room_identity_sha256=manual_room_identity_sha256(*keys),
            )
    return KakaoManualCaptureItem.model_validate(fields | dict(state=state))


class KakaoCaptureIntakeService:
    def __init__(
        self,
        engine: Engine,
        *,
        intake: KakaoRoomIntakeService,
        read_download: DownloadReader,
        read_metadata: MetadataReader,
        list_capture_ids: CaptureIdsReader,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._read_download = read_download
        self.intake, self.read_metadata, self.list_capture_ids = (
            intake,
            read_metadata,
            list_capture_ids,
        )

    def inspect_photo_occurrence(
        self,
        actor: ActorContext,
        *,
        source_binding_id: str,
        manual_lease_id: str,
        csv_capture_id: str,
        photo_capture_id: str,
    ) -> KakaoPhotoOccurrence | None:
        """Internal read of two exact owned captures; no source publication or workflow."""

        def context() -> OwnedManualCaptureRun:
            with self._sessions.begin() as session:
                return authorize_owned_manual_capture_run(
                    session,
                    actor,
                    source_binding_id=source_binding_id,
                    manual_lease_id=manual_lease_id,
                )

        run = context()
        if csv_capture_id == photo_capture_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

        def read(capture_id: str) -> ReceivedKakaoDownload:
            try:
                captured = self._read_download(run.fence, capture_id)
            except KakaoDownloadInputError:
                raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE") from None
            run.validate_transfer_interval(
                captured.receipt.started_at, captured.receipt.completed_at
            )
            return captured

        csv = read(csv_capture_id)
        photo = read(photo_capture_id)
        occurrence = None
        if (
            csv.observation is not None
            and photo.observation is not None
            and csv.observation.target.kind == "BLOB"
            and photo.observation.target.kind == "SAME_ORIGIN_PATH"
        ):
            try:
                messages = read_kakao_csv_messages(csv.payload)
            except ValueError:
                raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE") from None
            occurrence = infer_kakao_photo_occurrence(
                messages,
                csv_receipt=csv.receipt,
                csv_observation=csv.observation,
                photo_receipt=photo.receipt,
                photo_observation=photo.observation,
            )
        if context() != run:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return occurrence

    def list_captures(self, actor: ActorContext, source_binding_id: str) -> KakaoManualCapturePage:
        with self._sessions.begin() as session:
            version, runs, truncated = recent_owned_manual_captures(
                session, actor, source_binding_id
            )
        items: list[KakaoManualCaptureItem] = []
        for run in runs:
            if len(items) == 50:
                truncated = True
                break
            try:
                ids, limited = self.list_capture_ids(run.fence)
            except KakaoDownloadInputError:
                truncated = True
                continue
            truncated |= limited
            for capture_id in ids:
                if len(items) == 50:
                    truncated = True
                    break
                try:
                    metadata = self.read_metadata(run.fence, capture_id)
                    item = _preview(run, source_binding_id, metadata)
                except (KakaoDownloadInputError, KakaoArchiveError):
                    item = KakaoManualCaptureItem(
                        manual_lease_id=run.lease_id,
                        capture_id=capture_id,
                        started_at=None,
                        completed_at=None,
                        size_bytes=None,
                        state="INPUT_UNAVAILABLE",
                        preview_sha256=None,
                    )
                items.append(item)
        with self._sessions.begin() as session:
            current_version, current_runs, current_truncated = recent_owned_manual_captures(
                session, actor, source_binding_id
            )
            if version != current_version or runs != current_runs:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            truncated |= current_truncated
        items.sort(
            key=lambda item: (item.started_at or datetime.min.replace(tzinfo=UTC), item.capture_id),
            reverse=True,
        )
        return KakaoManualCapturePage(
            source_binding_id=source_binding_id,
            binding_resource_version=version,
            items=tuple(items),
            truncated=truncated,
        )

    def confirm_capture(
        self, actor: ActorContext, command: ConfirmKakaoManualCapture, *, idempotency_key: str
    ) -> KakaoRoomMutation:
        command = ConfirmKakaoManualCapture.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        prior = self.intake.get_confirmation(actor, command.source_binding_id, idempotency_key=key)
        if prior is not None:
            private = prior.proof.confirmation
            if (
                private.manual_lease_id,
                private.capture_id,
                private.display_name,
                private.expected_binding_version,
            ) != (
                command.manual_lease_id,
                command.capture_id,
                command.display_name,
                command.expected_binding_version,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
        else:
            with self._sessions.begin() as session:
                run = authorize_owned_manual_capture_run(
                    session,
                    actor,
                    source_binding_id=command.source_binding_id,
                    manual_lease_id=command.manual_lease_id,
                )
            try:
                metadata = self.read_metadata(run.fence, command.capture_id)
            except KakaoDownloadInputError:
                raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE") from None
            preview = _preview(run, command.source_binding_id, metadata)
            keys = _observed_keys(metadata)
            if preview.preview_sha256 != command.expected_preview_sha256 or keys is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            private = ConfirmKakaoManualRoom(
                source_binding_id=command.source_binding_id,
                manual_lease_id=command.manual_lease_id,
                capture_id=command.capture_id,
                expected_channel_key=keys[0],
                expected_room_key=keys[1],
                display_name=command.display_name,
                expected_binding_version=command.expected_binding_version,
            )
        return self.intake.confirm_room(
            actor,
            private,
            idempotency_key=key,
            expected_preview_sha256=command.expected_preview_sha256,
        )
