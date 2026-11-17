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

from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
)
from .kakao_archive_models import KakaoChannelBindingRecord
from .kakao_manual_models import KakaoManualSessionRecord


@dataclass(frozen=True, slots=True)
class OwnedManualCaptureRun:
    lease_id: str
    owner: str
    binding_version: int
    fence: ProfileFence
    browser_observed_at: datetime
    absolute_expires_at: datetime
    closed_at: datetime | None
    browser_first_observed_at: datetime | None = None

    def validate_evidence(self, evidence: KakaoManualRoomEvidence) -> None:
        if evidence.owner_operator_id != self.owner or (
            evidence.profile_id,
            evidence.browser_run_id,
            evidence.fence_epoch,
        ) != (self.fence.profile_id, self.fence.browser_run_id, self.fence.fence_epoch):
            raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE")
        self.validate_transfer_interval(evidence.capture_started_at, evidence.capture_completed_at)

    def validate_transfer_interval(self, started_at: datetime, completed_at: datetime) -> None:
        if (
            started_at < (self.browser_first_observed_at or self.browser_observed_at)
            or started_at >= self.absolute_expires_at
            or completed_at < started_at
            or completed_at > datetime.now(UTC)
            or (self.closed_at is not None and completed_at > self.closed_at)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE")


def authorize_owned_manual_capture(
    session: Session, actor: ActorContext, command: ConfirmKakaoManualRoom
) -> OwnedManualCaptureRun:
    return authorize_owned_manual_capture_run(
        session,
        actor,
        source_binding_id=command.source_binding_id,
        manual_lease_id=command.manual_lease_id,
    )


def _context(
    row: KakaoManualSessionRecord, binding: KakaoChannelBindingRecord
) -> OwnedManualCaptureRun:
    if row.browser_observed_at is None or row.browser_invocation_id is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_MANUAL_CAPTURE_UNCONFIRMED")
    return OwnedManualCaptureRun(
        lease_id=row.lease_id,
        owner=row.owner_operator_id,
        binding_version=binding.resource_version,
        fence=ProfileFence(
            schema_version="kakao-profile-fence/1.0",
            profile_id=row.profile_id,
            browser_run_id=row.browser_run_id,
            fence_epoch=row.fence_epoch,
            mode="MANUAL",
        ),
        browser_observed_at=row.browser_observed_at,
        browser_first_observed_at=row.browser_first_observed_at,
        absolute_expires_at=row.absolute_expires_at,
        closed_at=row.closed_at,
    )


def authorize_owned_manual_capture_run(
    session: Session, actor: ActorContext, *, source_binding_id: str, manual_lease_id: str
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
            KakaoManualSessionRecord.lease_id == manual_lease_id,
            KakaoManualSessionRecord.owner_operator_id == owner,
            KakaoManualSessionRecord.source_binding_id == source_binding_id,
            KakaoChannelBindingRecord.owner_operator_id == owner,
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if value is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    row, binding = value
    if binding.state == "RETIRED":
        raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
    return _context(row, binding)


def recent_owned_manual_captures(
    session: Session, actor: ActorContext, source_binding_id: str
) -> tuple[int, tuple[OwnedManualCaptureRun, ...], bool]:
    owner = authorize_kakao_actor(
        session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT, now=datetime.now(UTC), admin_only=True
    )
    _, binding = authorize_kakao_binding_scope(
        session, actor, source_binding_id, PermissionKey.KAKAO_ARCHIVE_COLLECT, lock=False
    )
    rows = tuple(
        session.scalars(
            select(KakaoManualSessionRecord)
            .where(
                KakaoManualSessionRecord.owner_operator_id == owner,
                KakaoManualSessionRecord.source_binding_id == source_binding_id,
                KakaoManualSessionRecord.browser_observed_at.is_not(None),
                KakaoManualSessionRecord.browser_invocation_id.is_not(None),
            )
            .order_by(
                KakaoManualSessionRecord.created_at.desc(), KakaoManualSessionRecord.lease_id.desc()
            )
            .limit(9)
        )
    )
    return (
        binding.resource_version,
        tuple(_context(row, binding) for row in rows[:8]),
        len(rows) > 8,
    )
