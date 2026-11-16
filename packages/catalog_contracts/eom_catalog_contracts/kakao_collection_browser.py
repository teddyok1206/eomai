"""Owner-only browser lifetime metadata; never public/worker execution authority."""

from typing import Literal, Self

from pydantic import Field, StrictBool, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_archive_binding import KakaoResourceVersion
from .kakao_collection import KakaoRunId
from .kakao_manual import BootId, InvocationId, KakaoBrowserRunId, KakaoProfileId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

BrowserPhase = Literal["PREPARING", "RUNNING", "STOPPING", "CLOSED"]
BrowserError = Literal["START_FAILED", "RUNTIME_LOST", "OWNER_UNAVAILABLE", "REBOOT_UNCLEAN"]
BrowserClosure = Literal["STOPPED", "PRE_READY_FAILED", "REBOOT_UNCLEAN"]
RuntimeBrowserError = Literal["START_FAILED", "RUNTIME_LOST", "REBOOT_UNCLEAN"]


class KakaoCollectionBrowserIntent(FrozenModel):
    schema_version: Literal["kakao-collection-browser-intent/1.0"] = (
        "kakao-collection-browser-intent/1.0"
    )
    run_id: KakaoRunId
    source_binding_id: KakaoBindingId
    profile_id: KakaoProfileId
    browser_run_id: KakaoBrowserRunId
    fence_epoch: KakaoResourceVersion
    epoch_number: KakaoResourceVersion
    command_sha256: Sha256
    dispatch_boot_id: BootId
    phase: BrowserPhase
    resource_version: KakaoResourceVersion
    created_at: UtcDatetime
    closed_at: UtcDatetime | None
    browser_invocation_id: InvocationId | None
    browser_pid: int | None = Field(strict=True, ge=1, le=2147483647)
    browser_monotonic_us: int | None = Field(strict=True, ge=1, le=9223372036854775807)
    browser_observed_at: UtcDatetime | None
    last_error: BrowserError | None

    @model_validator(mode="after")
    def consistent_lifetime(self) -> Self:
        values = (
            self.browser_invocation_id,
            self.browser_pid,
            self.browser_monotonic_us,
            self.browser_observed_at,
        )
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("KAKAO_COLLECTION_BROWSER_HANDLE_INVALID")
        if self.phase == "RUNNING" and self.browser_invocation_id is None:
            raise ValueError("KAKAO_COLLECTION_BROWSER_HANDLE_INVALID")
        if (
            (self.phase == "CLOSED") != (self.closed_at is not None)
            or (self.closed_at is not None and self.closed_at < self.created_at)
            or (self.browser_observed_at is not None and self.browser_observed_at < self.created_at)
        ):
            raise ValueError("KAKAO_COLLECTION_BROWSER_TIME_INVALID")
        validate_contract("kakao-collection-browser-v1", self.model_dump(mode="json"))
        return self


class KakaoCollectionBrowserObservation(FrozenModel):
    schema_version: Literal["kakao-collection-browser-observation/1.0"] = (
        "kakao-collection-browser-observation/1.0"
    )
    profile_id: KakaoProfileId
    browser_run_id: KakaoBrowserRunId
    fence_epoch: KakaoResourceVersion
    command_sha256: Sha256
    dispatch_boot_id: BootId
    observed_boot_id: BootId
    observed_at: UtcDatetime
    kind: Literal["RUNNING", "STOPPED", "PRE_READY_FAILED", "REBOOT_UNCLEAN"]
    profile_locked: StrictBool
    gateway_stopped: StrictBool
    invocation_id: InvocationId | None
    main_pid: int | None = Field(strict=True, ge=1, le=2147483647)
    started_monotonic_us: int | None = Field(strict=True, ge=1, le=9223372036854775807)
    runtime_error: RuntimeBrowserError | None = None

    @model_validator(mode="after")
    def consistent_observation(self) -> Self:
        values = (self.invocation_id, self.main_pid, self.started_monotonic_us)
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("KAKAO_COLLECTION_BROWSER_HANDLE_INVALID")
        if self.kind in {"RUNNING", "STOPPED"} and self.invocation_id is None:
            raise ValueError("KAKAO_COLLECTION_BROWSER_HANDLE_INVALID")
        if self.kind == "RUNNING" and self.runtime_error is not None:
            raise ValueError("KAKAO_COLLECTION_BROWSER_RUNNING_ERROR_INVALID")
        if (self.kind == "REBOOT_UNCLEAN") != (self.observed_boot_id != self.dispatch_boot_id):
            raise ValueError("KAKAO_COLLECTION_BROWSER_BOOT_INVALID")
        validate_contract("kakao-collection-browser-v1", self.model_dump(mode="json"))
        return self
