"""Bounded progress of the single accepted manual intent; never renews authority."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Literal, Protocol

from eom_catalog_contracts.kakao_manual import (
    KakaoManualClosureObservation,
    KakaoManualIntent,
    KakaoManualRuntimeObservation,
    ManualError,
)

from .kakao_archive_authorization import KakaoArchiveError

if TYPE_CHECKING:
    from .kakao_manual_service import KakaoManualService


class ManualRuntime(Protocol):
    def ensure_browser(self, intent: KakaoManualIntent) -> None: ...
    def ensure_gateway(self, intent: KakaoManualIntent) -> None: ...
    def observe_browser(self, intent: KakaoManualIntent) -> KakaoManualRuntimeObservation: ...
    def observe_runtime(self, intent: KakaoManualIntent) -> KakaoManualRuntimeObservation: ...
    def deliver_grant(self, intent: KakaoManualIntent) -> None: ...
    def close(self, intent: KakaoManualIntent) -> KakaoManualClosureObservation: ...


Tick = Literal["IDLE", "WAITING", "ACTIVE", "ENDED", "ERROR"]


class KakaoManualCoordinator:
    def __init__(self, service: KakaoManualService, runtime: ManualRuntime) -> None:
        self.service, self.runtime = service, runtime
        self._tick = threading.Lock()

    def advance_once(self) -> Tick:
        if not self._tick.acquire(blocking=False):
            return "WAITING"
        current = None
        try:
            current = self.service.get_current_intent()
            if current is None:
                return "IDLE"
            current = self.service.reconcile_authority(current.lease_id)
            if current.phase == "PREPARING":
                if not current.grant_revision:
                    self.runtime.ensure_browser(current)
                    current = self.service.prepare_gateway(
                        current.lease_id, observe_browser=self.runtime.observe_browser
                    )
                self.runtime.ensure_gateway(current)
                self.service.accept_ready(
                    current.lease_id, observe_runtime=self.runtime.observe_runtime
                )
                return "ACTIVE"
            if current.phase == "ACTIVE":
                # Only deliver the already committed UI renewal. This loop never
                # invokes renew_session or computes a later grant deadline.
                self.runtime.deliver_grant(current)
                self.runtime.observe_runtime(current)
                return "ACTIVE"
            if current.phase in {"STOPPING", "ERROR"}:
                self.service.accept_closed(current.lease_id, observe_stopped=self.runtime.close)
                return "ENDED"
            return "IDLE"
        except KakaoArchiveError as error:
            if error.code in {
                "KAKAO_ARCHIVE_PRECONDITION_FAILED",
                "KAKAO_ARCHIVE_REMOTE_FENCE_STALE",
                "KAKAO_ARCHIVE_REMOTE_LEASE_EXPIRED",
                "KAKAO_ARCHIVE_PERMISSION_DENIED",
                "KAKAO_ARCHIVE_BINDING_RETIRED",
            }:
                return "WAITING"  # Current authority/CAS is re-read on the next bounded tick.
            raise
        except (ValueError, OSError, KeyError) as error:
            code = getattr(error, "code", "")
            if (
                code.endswith("CONTROL_BUSY")
                or code.endswith("OBSERVATION_BUSY")
                or code.endswith("START_UNCERTAIN")
                or code.endswith("START_PENDING")
            ):
                return "WAITING"  # Observe the original dispatch; never re-launch a staged run.
            if current is None or current.phase == "ERROR":
                return "ERROR"
            failure: ManualError = (
                "REBOOT_UNCLEAN"
                if "REBOOT" in code
                else "STOP_UNCONFIRMED"
                if current.phase == "STOPPING"
                else "RUNTIME_LOST"
                if current.phase == "ACTIVE"
                else "GATEWAY_START_FAILED"
                if current.grant_revision
                else "START_FAILED"
            )
            try:
                self.service.fail_session(
                    current.lease_id,
                    expected_resource_version=current.resource_version,
                    error=failure,
                )
            except KakaoArchiveError as conflict:
                if conflict.code not in {
                    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
                    "KAKAO_ARCHIVE_REMOTE_FENCE_STALE",
                }:
                    raise
            return "ERROR"
        finally:
            self._tick.release()
