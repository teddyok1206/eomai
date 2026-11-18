"""Compose fixed OS adapters for one exact Catalog-owned manual intent; no DB access."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from eom_catalog_contracts.kakao_manual import (
    KakaoManualClosureObservation,
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualRuntimeObservation,
)
from eom_catalog_contracts.kakao_manual_runtime_values import (
    manual_profile_fence as profile_fence,
)
from eom_catalog_contracts.kakao_manual_runtime_values import (
    recorded_manual_gateway_grant as recorded_grant,
)
from eom_kakao_archive_contracts.kakao_remote import (
    GatewayLeaseGrant,
    GatewayRevocation,
    ProfileFence,
)

from .kakao_browser_runtime import BrowserRunHandle, ClosedBrowserDispatch, FixedKakaoBrowserRuntime
from .kakao_gateway_runtime import ClosedGatewayDispatch, FixedKakaoGatewayRuntime, GatewayRunHandle
from .kakao_profile_observation import InstalledKakaoProfileObserver, profile_lock_released


class KakaoManualRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedKakaoManualRuntime:
    browser: FixedKakaoBrowserRuntime
    gateway: FixedKakaoGatewayRuntime
    profile: InstalledKakaoProfileObserver
    assert_current: Callable[[KakaoManualIntent], None]
    resolve_predecessor: Callable[[KakaoManualIntent, int], KakaoManualIntent]
    _observation_lock: threading.Lock = field(
        default_factory=threading.Lock, compare=False, repr=False
    )
    resolve_auto_predecessor: Callable[[ProfileFence, ProfileFence], tuple[str, str]] | None = None

    def observe_profile(self) -> KakaoManualFreshProfile:
        return self.profile.observe()

    def _browser_dispatch(
        self, intent: KakaoManualIntent
    ) -> BrowserRunHandle | ClosedBrowserDispatch:
        return self.browser.observe_dispatch(
            profile_fence(intent),
            command_sha256=intent.command_sha256,
            dispatched_boot_id=intent.dispatch_boot_id,
        )

    def _prior_browser(
        self, intent: KakaoManualIntent, observed: ProfileFence | None
    ) -> ClosedBrowserDispatch | None:
        if observed is None:
            idle = self.browser.observe_idle()
            if not idle.never_dispatched:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_BROWSER_PRIOR_UNKNOWN")
            return None
        if observed.mode == "AUTO" and self.resolve_auto_predecessor is not None:
            digest, boot = self.resolve_auto_predecessor(profile_fence(intent), observed)
            closed = self.browser.observe_dispatch(
                observed, command_sha256=digest, dispatched_boot_id=boot
            )
        else:
            prior = self.resolve_predecessor(intent, observed.fence_epoch)
            if profile_fence(prior) != observed:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_PREDECESSOR_MISMATCH")
            closed = self._browser_dispatch(prior)
        if not isinstance(closed, ClosedBrowserDispatch):
            raise KakaoManualRuntimeError("KAKAO_MANUAL_PREDECESSOR_RUNNING")
        return closed

    def ensure_browser(self, intent: KakaoManualIntent) -> None:
        """Only genuinely un-staged input can start; a staged closed attempt cannot retry."""
        fence = profile_fence(intent)
        stage = self.browser.observe_stage(fence)
        if stage.staged:
            existing = self._browser_dispatch(intent)
            if not isinstance(existing, BrowserRunHandle):
                raise KakaoManualRuntimeError("KAKAO_MANUAL_BROWSER_ATTEMPT_CLOSED")
            return
        prior = self._prior_browser(intent, stage.current_fence)
        if self.browser.boot_identity() != intent.dispatch_boot_id:
            raise KakaoManualRuntimeError("KAKAO_MANUAL_REBOOT_UNCLEAN")
        self.browser.start(fence, prior=prior, assert_current=lambda _: self.assert_current(intent))

    def _prior_gateway(
        self, intent: KakaoManualIntent, value: GatewayLeaseGrant | GatewayRevocation | None
    ) -> ClosedGatewayDispatch | None:
        if value is None:
            if not self.gateway.observe_idle().never_dispatched:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_PRIOR_UNKNOWN")
            return None
        prior = self.resolve_predecessor(intent, value.fence_epoch)
        if value.lease_id != prior.lease_id or value.gateway_epoch != prior.gateway_epoch:
            raise KakaoManualRuntimeError("KAKAO_MANUAL_PREDECESSOR_MISMATCH")
        # The protected grant may be an earlier acknowledged revision of that same
        # predecessor. Never substitute another lease or silently issue a later grant.
        grant = value if isinstance(value, GatewayLeaseGrant) else recorded_grant(prior)
        closed = self.gateway.observe_for_stop(grant, dispatched_boot_id=prior.dispatch_boot_id)
        if not isinstance(closed, ClosedGatewayDispatch):
            raise KakaoManualRuntimeError("KAKAO_MANUAL_PREDECESSOR_RUNNING")
        return closed

    def _running_browser(self, intent: KakaoManualIntent) -> BrowserRunHandle:
        run = self._browser_dispatch(intent)
        if not isinstance(run, BrowserRunHandle) or profile_lock_released():
            raise KakaoManualRuntimeError("KAKAO_MANUAL_BROWSER_NOT_RUNNING")
        return run

    def ensure_gateway(self, intent: KakaoManualIntent) -> None:
        desired = recorded_grant(intent)
        value = self.gateway.observe_grant()
        if value is not None and value.lease_id == intent.lease_id:
            if not isinstance(value, GatewayLeaseGrant) or value != desired:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_GRANT_MISMATCH")
            result = self.gateway.observe_dispatch(
                value, dispatched_boot_id=intent.dispatch_boot_id
            )
            if not isinstance(result, GatewayRunHandle):
                raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_ATTEMPT_CLOSED")
            return
        prior = self._prior_gateway(intent, value)
        browser = self._running_browser(intent)
        self.gateway.start(
            desired,
            browser,
            prior=prior,
            assert_current=lambda _: self.assert_current(intent),
            observe_browser=self.browser.observe_run,
        )

    def _observation(
        self, intent: KakaoManualIntent, *, gateway_required: bool
    ) -> KakaoManualRuntimeObservation:
        # Parallel noVNC assets and UI heartbeats share one observer. Serialize
        # only this short read boundary, not DB authority or OS write control.
        if not self._observation_lock.acquire(timeout=2):
            raise KakaoManualRuntimeError("KAKAO_MANUAL_OBSERVATION_BUSY")
        try:
            return self._observe_current(intent, gateway_required=gateway_required)
        finally:
            self._observation_lock.release()

    def _observe_current(
        self, intent: KakaoManualIntent, *, gateway_required: bool
    ) -> KakaoManualRuntimeObservation:
        browser = self._running_browser(intent)
        gateway = None
        if gateway_required:
            desired = recorded_grant(intent)
            if self.gateway.observe_grant() != desired or datetime.now(UTC) >= desired.expires_at:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_GRANT_MISMATCH")
            gateway = self.gateway.observe_dispatch(
                desired, dispatched_boot_id=intent.dispatch_boot_id
            )
            if not isinstance(gateway, GatewayRunHandle):
                raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_NOT_RUNNING")
        else:
            self.gateway.observe_idle()
        return KakaoManualRuntimeObservation(
            lease_id=intent.lease_id,
            profile_id=intent.profile_id,
            browser_run_id=intent.browser_run_id,
            command_sha256=intent.command_sha256,
            fence_epoch=intent.fence_epoch,
            gateway_epoch=intent.gateway_epoch,
            observed_at=datetime.now(UTC),
            boot_id=browser.boot_id,
            invocation_id=browser.invocation_id,
            main_pid=browser.main_pid,
            started_monotonic_us=browser.started_monotonic_us,
            browser_running=True,
            profile_locked=True,
            gateway_running=gateway is not None,
            gateway_invocation_id=gateway.invocation_id if gateway is not None else None,
        )

    def observe_browser(self, intent: KakaoManualIntent) -> KakaoManualRuntimeObservation:
        return self._observation(intent, gateway_required=False)

    def observe_runtime(self, intent: KakaoManualIntent) -> KakaoManualRuntimeObservation:
        return self._observation(intent, gateway_required=True)

    def deliver_grant(self, intent: KakaoManualIntent) -> None:
        """Publish an already authorized revision; this never computes a new expiry."""
        desired, value = recorded_grant(intent), self.gateway.observe_grant()
        if not isinstance(value, GatewayLeaseGrant) or value.lease_id != intent.lease_id:
            raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_GRANT_MISMATCH")
        if value == desired:
            return
        run = self.gateway.observe_dispatch(value, dispatched_boot_id=intent.dispatch_boot_id)
        if not isinstance(run, GatewayRunHandle):
            raise KakaoManualRuntimeError("KAKAO_MANUAL_GATEWAY_NOT_RUNNING")
        self.gateway.renew(
            run,
            desired,
            self._running_browser(intent),
            assert_current=lambda _: self.assert_current(intent),
            observe_browser=self.browser.observe_run,
        )

    def close(self, intent: KakaoManualIntent) -> KakaoManualClosureObservation:
        """Gateway/viewers first; then browser and actual profile lock. No false flush claim."""
        value = self.gateway.observe_grant()
        if value is not None and value.lease_id == intent.lease_id:
            grant = value if isinstance(value, GatewayLeaseGrant) else recorded_grant(intent)
            run = self.gateway.observe_for_stop(grant, dispatched_boot_id=intent.dispatch_boot_id)
            if isinstance(run, GatewayRunHandle):
                reason = {
                    "USER_ENDED": "USER_ENDED",
                    "SESSION_REVOKED": "SESSION_REVOKED",
                    "SOURCE_REVOKED": "SOURCE_REVOKED",
                    "RUNTIME_FAILED": "RUNTIME_LOST",
                    "EXPIRED": "EXPIRED",
                    None: "OWNER_UNAVAILABLE",
                }[intent.ended_reason]
                self.gateway.stop(
                    run,
                    GatewayRevocation.model_validate(
                        {
                            "schema_version": "kakao-remote-gateway-revocation/1.0",
                            "lease_id": intent.lease_id,
                            "fence_epoch": intent.fence_epoch,
                            "gateway_epoch": intent.gateway_epoch,
                            "grant_revision": intent.grant_revision,
                            "reason": reason,
                        }
                    ),
                )
            if not isinstance(
                self.gateway.observe_for_stop(grant, dispatched_boot_id=intent.dispatch_boot_id),
                ClosedGatewayDispatch,
            ):
                raise KakaoManualRuntimeError("KAKAO_MANUAL_STOP_UNCONFIRMED")
        else:
            self._prior_gateway(intent, value)
        stage = self.browser.observe_stage(profile_fence(intent))
        if stage.staged:
            browser = self._browser_dispatch(intent)
            if isinstance(browser, BrowserRunHandle):
                self.browser.stop(browser)
            if not isinstance(self._browser_dispatch(intent), ClosedBrowserDispatch):
                raise KakaoManualRuntimeError("KAKAO_MANUAL_STOP_UNCONFIRMED")
        else:
            self._prior_browser(intent, stage.current_fence)
            if intent.browser is not None:
                raise KakaoManualRuntimeError("KAKAO_MANUAL_BROWSER_INPUT_LOST")
        if not profile_lock_released():
            raise KakaoManualRuntimeError("KAKAO_MANUAL_STOP_UNCONFIRMED")
        self.gateway.observe_idle()
        boot = self.browser.boot_identity()
        if self.gateway.boot_identity() != boot:
            raise KakaoManualRuntimeError("KAKAO_MANUAL_REBOOT_UNCLEAN")
        return KakaoManualClosureObservation(
            lease_id=intent.lease_id,
            profile_id=intent.profile_id,
            browser_run_id=intent.browser_run_id,
            command_sha256=intent.command_sha256,
            fence_epoch=intent.fence_epoch,
            gateway_epoch=intent.gateway_epoch,
            dispatch_boot_id=intent.dispatch_boot_id,
            observed_boot_id=boot,
            observed_at=datetime.now(UTC),
            kind="REBOOT_UNCLEAN"
            if boot != intent.dispatch_boot_id
            else "PRE_READY_FAILED"
            if intent.browser is None
            else "STOPPED",
            browser_stopped=True,
            gateway_stopped=True,
            profile_lock_released=True,
        )
