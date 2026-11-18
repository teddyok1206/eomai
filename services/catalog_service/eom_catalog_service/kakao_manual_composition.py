"""Optional fixed manual runtime; feature-off imports no Kakao worker/OS implementation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from eom_catalog_contracts.kakao_manual import (
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualRuntimeObservation,
)
from sqlalchemy import Engine

from .kakao_archive_authorization import KakaoArchiveError

if TYPE_CHECKING:
    from .kakao_browser_history import closed_kakao_browser_pin
    from .kakao_manual_coordinator import KakaoManualCoordinator
    from .kakao_manual_dispatch import KakaoManualApplication


@dataclass(frozen=True, slots=True)
class ManualRuntimeConfiguration:
    profile_id: str
    browser_template_sha256: str
    browser_driver_sha256: str
    gateway_template_sha256: str
    gateway_supervisor_sha256: str
    initial_profile_manifest_sha256: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"kakaoprofile_[0-9a-f]{32}", self.profile_id) is None or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            for value in (
                self.browser_template_sha256,
                self.browser_driver_sha256,
                self.gateway_template_sha256,
                self.gateway_supervisor_sha256,
                self.initial_profile_manifest_sha256,
            )
        ):
            raise ValueError("KAKAO_MANUAL_CONFIGURATION_INVALID")


@dataclass(frozen=True, slots=True)
class ManualRuntimeComposition:
    application: KakaoManualApplication
    coordinator: KakaoManualCoordinator


def build_kakao_manual_runtime(
    engine: Engine, environment: Mapping[str, str]
) -> ManualRuntimeComposition | None:
    if environment.get("EOM_KAKAO_MANUAL_MODE", "DISABLED") == "DISABLED":
        return None
    if environment.get("EOM_KAKAO_MANUAL_MODE") != "ENABLED":
        raise ValueError("KAKAO_MANUAL_CONFIGURATION_INVALID")
    fields = {
        "profile_id": "EOM_KAKAO_PROFILE_ID",
        "browser_template_sha256": "EOM_KAKAO_BROWSER_TEMPLATE_SHA256",
        "browser_driver_sha256": "EOM_KAKAO_BROWSER_DRIVER_SHA256",
        "gateway_template_sha256": "EOM_KAKAO_GATEWAY_TEMPLATE_SHA256",
        "gateway_supervisor_sha256": "EOM_KAKAO_GATEWAY_SUPERVISOR_SHA256",
        "initial_profile_manifest_sha256": "EOM_KAKAO_INITIAL_PROFILE_MANIFEST_SHA256",
    }
    if any(not environment.get(key) for key in fields.values()):
        return None  # No partial, guessed or source-Git pin activates a runtime.
    configuration = ManualRuntimeConfiguration(
        **{name: environment[key] for name, key in fields.items()}
    )
    from eom_orchestrator.kakao_browser_runtime import FixedKakaoBrowserRuntime
    from eom_orchestrator.kakao_gateway_runtime import FixedKakaoGatewayRuntime
    from eom_orchestrator.kakao_manual_runtime import FixedKakaoManualRuntime
    from eom_orchestrator.kakao_profile_observation import InstalledKakaoProfileObserver

    from .kakao_manual_coordinator import KakaoManualCoordinator
    from .kakao_manual_dispatch import KakaoManualApplication
    from .kakao_manual_service import KakaoManualService

    service = KakaoManualService(engine, profile_id=configuration.profile_id)
    browser = FixedKakaoBrowserRuntime(
        configuration.browser_template_sha256, configuration.browser_driver_sha256
    )
    gateway = FixedKakaoGatewayRuntime(
        configuration.gateway_template_sha256, configuration.gateway_supervisor_sha256
    )
    profile = InstalledKakaoProfileObserver(
        configuration.profile_id, configuration.initial_profile_manifest_sha256, browser, gateway
    )

    def assert_current(intent: KakaoManualIntent) -> None:
        actual = service.get_intent(intent.lease_id)
        if actual != intent:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

    def predecessor(intent: KakaoManualIntent, epoch: int) -> KakaoManualIntent:
        result = service.get_predecessor_intent(intent, fence_epoch=epoch)
        if result is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_FENCE_STALE")
        return result

    runtime = FixedKakaoManualRuntime(
        browser,
        gateway,
        profile,
        assert_current,
        predecessor,
        resolve_auto_predecessor=lambda current, prior: closed_kakao_browser_pin(
            engine, current, prior
        ),
    )

    def observe_profile() -> KakaoManualFreshProfile:
        try:
            return runtime.observe_profile()
        except (ValueError, OSError, KeyError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE") from None

    def observe_runtime(intent: KakaoManualIntent) -> KakaoManualRuntimeObservation:
        try:
            return runtime.observe_runtime(intent)
        except (ValueError, OSError, KeyError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE") from None

    return ManualRuntimeComposition(
        KakaoManualApplication(service, observe_profile, observe_runtime),
        KakaoManualCoordinator(service, runtime),
    )
