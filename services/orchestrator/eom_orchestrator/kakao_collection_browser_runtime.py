"""Observe/close one stored collection epoch using fixed installed OS adapters.

No browser launch or selector is exposed here. Source admission and current-owner
checks remain with Catalog; this adapter never reads DB/NAS or credentials.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.kakao_collection_browser import (
    KakaoCollectionBrowserIntent as Intent,
)
from eom_catalog_contracts.kakao_collection_browser import (
    KakaoCollectionBrowserObservation as Observation,
)
from eom_catalog_contracts.kakao_collection_browser import RuntimeBrowserError
from eom_kakao_archive_contracts.kakao_remote import ProfileFence

from .kakao_browser_runtime import BrowserRunHandle, ClosedBrowserDispatch, FixedKakaoBrowserRuntime
from .kakao_gateway_runtime import FixedKakaoGatewayRuntime
from .kakao_profile_observation import profile_lock_released


class KakaoCollectionBrowserRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "KAKAO_COLLECTION_BROWSER_" + code
        super().__init__(self.code)


def collection_profile_fence(intent: Intent) -> ProfileFence:
    return ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=intent.profile_id,
        browser_run_id=intent.browser_run_id,
        fence_epoch=intent.fence_epoch,
        mode="AUTO",
    )


@dataclass(frozen=True, slots=True)
class FixedKakaoCollectionBrowserRuntime:
    browser: FixedKakaoBrowserRuntime
    gateway: FixedKakaoGatewayRuntime

    def _dispatch(self, intent: Intent) -> BrowserRunHandle | ClosedBrowserDispatch:
        return self.browser.observe_dispatch(
            collection_profile_fence(intent),
            command_sha256=intent.command_sha256,
            dispatched_boot_id=intent.dispatch_boot_id,
        )

    @staticmethod
    def _known_execution(intent: Intent, actual: BrowserRunHandle | ClosedBrowserDispatch) -> None:
        if isinstance(actual, ClosedBrowserDispatch) and actual.reason == "REBOOT_UNCLEAN":
            return  # The fixed OS adapter proved a different boot; the old process cannot survive.
        if intent.browser_invocation_id is not None and (
            actual.invocation_id != intent.browser_invocation_id
            or actual.started_monotonic_us != intent.browser_monotonic_us
            or (isinstance(actual, BrowserRunHandle) and actual.main_pid != intent.browser_pid)
        ):
            raise KakaoCollectionBrowserRuntimeError("EXECUTION_CHANGED")

    def observe_running(self, intent: Intent) -> Observation:
        if intent.phase not in {"PREPARING", "RUNNING"}:
            raise KakaoCollectionBrowserRuntimeError("RUNNING_NOT_REQUESTED")
        observed_at = datetime.now(UTC)
        actual = self._dispatch(intent)
        if not isinstance(actual, BrowserRunHandle):
            raise KakaoCollectionBrowserRuntimeError("ATTEMPT_CLOSED")
        self._known_execution(intent, actual)
        gateway = self.gateway.observe_idle()
        if (
            gateway.boot_id != actual.boot_id
            or actual.boot_id != intent.dispatch_boot_id
            or profile_lock_released()
        ):
            raise KakaoCollectionBrowserRuntimeError("RUNNING_UNCONFIRMED")
        return Observation(
            profile_id=intent.profile_id,
            browser_run_id=intent.browser_run_id,
            fence_epoch=intent.fence_epoch,
            command_sha256=intent.command_sha256,
            dispatch_boot_id=intent.dispatch_boot_id,
            observed_boot_id=actual.boot_id,
            observed_at=min(observed_at, gateway.observed_at),
            kind="RUNNING",
            profile_locked=True,
            gateway_stopped=True,
            invocation_id=actual.invocation_id,
            main_pid=actual.main_pid,
            started_monotonic_us=actual.started_monotonic_us,
        )

    def close(self, intent: Intent) -> Observation:
        if intent.phase != "STOPPING":
            raise KakaoCollectionBrowserRuntimeError("STOP_NOT_REQUESTED")
        # AUTO never owns a viewer grant. An unexpected live MANUAL gateway must
        # be reconciled by its own owner, not stopped as this collection's process.
        self.gateway.observe_idle()
        failure: RuntimeBrowserError | None = None
        stage = self.browser.observe_stage(collection_profile_fence(intent))
        if stage.staged:
            actual = self._dispatch(intent)
            self._known_execution(intent, actual)
            if isinstance(actual, BrowserRunHandle):
                self.browser.stop(actual)
            final = self._dispatch(intent)
            if not isinstance(final, ClosedBrowserDispatch):
                raise KakaoCollectionBrowserRuntimeError("STOP_UNCONFIRMED")
            self._known_execution(intent, final)
            if final.unit_result != "success" or (final.main_exit_code, final.main_exit_status) != (
                1,
                0,
            ):
                failure = (
                    "RUNTIME_LOST" if intent.browser_invocation_id is not None else "START_FAILED"
                )
        else:
            if intent.browser_invocation_id is not None:
                raise KakaoCollectionBrowserRuntimeError("INPUT_LOST")
            # A never-staged reservation still needs actual unit/cgroup closure.
            self.browser.observe_idle()
        observed_at = datetime.now(UTC)
        if not profile_lock_released():
            raise KakaoCollectionBrowserRuntimeError("STOP_UNCONFIRMED")
        gateway = self.gateway.observe_idle()
        boot = self.browser.boot_identity()
        if gateway.boot_id != boot:
            raise KakaoCollectionBrowserRuntimeError("BOOT_CHANGED")
        return Observation(
            profile_id=intent.profile_id,
            browser_run_id=intent.browser_run_id,
            fence_epoch=intent.fence_epoch,
            command_sha256=intent.command_sha256,
            dispatch_boot_id=intent.dispatch_boot_id,
            observed_boot_id=boot,
            observed_at=min(observed_at, gateway.observed_at),
            kind="REBOOT_UNCLEAN"
            if boot != intent.dispatch_boot_id
            else "STOPPED"
            if intent.browser_invocation_id is not None
            else "PRE_READY_FAILED",
            profile_locked=False,
            gateway_stopped=True,
            invocation_id=intent.browser_invocation_id,
            main_pid=intent.browser_pid,
            started_monotonic_us=intent.browser_monotonic_us,
            runtime_error="REBOOT_UNCLEAN" if boot != intent.dispatch_boot_id else failure,
        )
