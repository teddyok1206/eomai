"""Metadata access to an owned historical capture; never remote lease authorization.

A fresh current session may confirm its owner's previous download. This does not
renew the original session, open a browser or change a failed/ended lease.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.kakao_room_intake import ConfirmKakaoManualRoom, KakaoManualRoomEvidence
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_actor
from .kakao_archive_models import KakaoChannelBindingRecord
from .kakao_manual_models import KakaoManualSessionRecord


@dataclass(frozen=True, slots=True)
class OwnedManualCaptureRun:
    owner: str
    binding_version: int
    fence: ProfileFence
    browser_observed_at: datetime
    absolute_expires_at: datetime
    closed_at: datetime | None

    def validate_evidence(self, evidence: KakaoManualRoomEvidence) -> None:
        if (
            evidence.owner_operator_id != self.owner
            or (evidence.profile_id, evidence.browser_run_id, evidence.fence_epoch)
            != (self.fence.profile_id, self.fence.browser_run_id, self.fence.fence_epoch)
            or evidence.capture_started_at < self.browser_observed_at
            or evidence.capture_started_at >= self.absolute_expires_at
            or evidence.capture_completed_at > datetime.now(UTC)
            or (self.closed_at is not None and evidence.capture_completed_at > self.closed_at)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE")


def authorize_owned_manual_capture(
    session: Session, actor: ActorContext, command: ConfirmKakaoManualRoom
) -> OwnedManualCaptureRun:
    # Intake is an explicit administrator action, unlike an ordinary history read.
    owner = authorize_kakao_actor(
        session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT, now=datetime.now(UTC), admin_only=True
    )
    value = session.execute(
        select(KakaoManualSessionRecord, KakaoChannelBindingRecord)
        .join(
            KakaoChannelBindingRecord,
            KakaoChannelBindingRecord.source_binding_id
            == KakaoManualSessionRecord.source_binding_id,
        )
        .where(
            KakaoManualSessionRecord.lease_id == command.manual_lease_id,
            KakaoManualSessionRecord.owner_operator_id == owner,
            KakaoManualSessionRecord.source_binding_id == command.source_binding_id,
            KakaoChannelBindingRecord.owner_operator_id == owner,
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if value is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    row, binding = value
    if binding.state == "RETIRED":
        raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
    if row.browser_observed_at is None or row.browser_invocation_id is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNCONFIRMED")
    return OwnedManualCaptureRun(
        owner=owner,
        binding_version=binding.resource_version,
        fence=ProfileFence(
            schema_version="kakao-profile-fence/1.0",
            profile_id=row.profile_id,
            browser_run_id=row.browser_run_id,
            fence_epoch=row.fence_epoch,
            mode="MANUAL",
        ),
        browser_observed_at=row.browser_observed_at,
        absolute_expires_at=row.absolute_expires_at,
        closed_at=row.closed_at,
    )
