"""Resolve the exact closed lifetime referenced by protected shared browser input."""

from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_collection_browser_models import KakaoCollectionBrowserRecord
from .kakao_manual_models import KakaoManualSessionRecord, KakaoProfileRuntimeRecord

_STALE = "KAKAO_ARCHIVE_REMOTE_FENCE_STALE"


def closed_kakao_browser_pin(
    engine: Engine, current: ProfileFence, previous: ProfileFence
) -> tuple[str, str]:
    if (
        current.profile_id != previous.profile_id
        or current.fence_epoch <= previous.fence_epoch
        or current.mode not in {"MANUAL", "AUTO"}
        or previous.mode not in {"MANUAL", "AUTO"}
    ):
        raise KakaoArchiveError(_STALE)
    with build_session_factory(engine).begin() as session:
        profile = session.scalar(
            select(KakaoProfileRuntimeRecord).where(KakaoProfileRuntimeRecord.slot_key == "primary")
        )
        if (
            profile is None
            or profile.profile_id != current.profile_id
            or profile.fence_epoch != current.fence_epoch
            or profile.mode != current.mode
        ):
            raise KakaoArchiveError(_STALE)
        if current.mode == "MANUAL":
            lease = (
                None
                if profile.current_lease_id is None
                else session.get(KakaoManualSessionRecord, profile.current_lease_id)
            )
            if lease is None or lease.browser_run_id != current.browser_run_id:
                raise KakaoArchiveError(_STALE)
        elif profile.current_collection_browser_run_id != current.browser_run_id:
            raise KakaoArchiveError(_STALE)

        if previous.mode == "MANUAL":
            old_manual = session.scalar(
                select(KakaoManualSessionRecord).where(
                    KakaoManualSessionRecord.profile_id == previous.profile_id,
                    KakaoManualSessionRecord.fence_epoch == previous.fence_epoch,
                )
            )
            if (
                old_manual is None
                or old_manual.browser_run_id != previous.browser_run_id
                or old_manual.owner_operator_id != profile.owner_operator_id
                or old_manual.phase != "ENDED"
                or old_manual.closed_at is None
            ):
                raise KakaoArchiveError(_STALE)
            return old_manual.command_sha256, old_manual.dispatch_boot_id

        old_auto = session.get(KakaoCollectionBrowserRecord, previous.browser_run_id)
        if (
            old_auto is None
            or old_auto.profile_id != previous.profile_id
            or old_auto.fence_epoch != previous.fence_epoch
            or old_auto.owner_operator_id != profile.owner_operator_id
            or old_auto.phase != "CLOSED"
            or old_auto.closed_at is None
        ):
            raise KakaoArchiveError(_STALE)
        return old_auto.command_sha256, old_auto.dispatch_boot_id
