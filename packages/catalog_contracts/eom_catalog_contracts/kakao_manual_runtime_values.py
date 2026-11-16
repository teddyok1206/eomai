"""Optional pure mappings for installed Kakao runtime consumers, not proxy authority.

The base Catalog DTO module does not import this module or require the optional
Kakao worker-contract wheel. Both runtime consumers reuse the exact small values.
"""

from eom_kakao_archive_contracts.kakao_remote import GatewayLeaseGrant, ProfileFence

from .kakao_manual import KakaoManualIntent


def manual_profile_fence(intent: KakaoManualIntent) -> ProfileFence:
    return ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=intent.profile_id,
        browser_run_id=intent.browser_run_id,
        fence_epoch=intent.fence_epoch,
        mode="MANUAL",
    )


def recorded_manual_gateway_grant(intent: KakaoManualIntent) -> GatewayLeaseGrant:
    """Exact recorded window, including closed history; never a fresh permission grant."""
    if intent.expires_at is None or intent.authorized_at is None or not intent.grant_revision:
        raise ValueError("KAKAO_MANUAL_GRANT_MISSING")
    return GatewayLeaseGrant(
        schema_version="kakao-remote-gateway-grant/1.0",
        lease_id=intent.lease_id,
        source_binding_id=intent.source_binding_id,
        profile_id=intent.profile_id,
        fence_epoch=intent.fence_epoch,
        gateway_epoch=intent.gateway_epoch,
        grant_revision=intent.grant_revision,
        issued_at=intent.created_at,
        authorized_at=intent.authorized_at,
        expires_at=intent.expires_at,
        absolute_expires_at=intent.absolute_expires_at,
    )
