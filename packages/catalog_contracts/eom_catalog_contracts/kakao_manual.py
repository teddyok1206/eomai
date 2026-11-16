"""Manual-login requests and owner observations, not channel verification authority."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_archive_binding import KakaoResourceVersion
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

KakaoManualLeaseId = Annotated[str, Field(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]
KakaoProfileId = Annotated[str, Field(pattern=r"^kakaoprofile_[0-9a-f]{32}$")]
KakaoBrowserRunId = Annotated[str, Field(pattern=r"^kakaobrowserrun_[0-9a-f]{32}$")]
BootId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
InvocationId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Phase = Literal["PREPARING", "ACTIVE", "STOPPING", "ENDED", "ERROR"]
ManualError = Literal[
    "START_FAILED",
    "RUNTIME_LOST",
    "GATEWAY_START_FAILED",
    "STOP_UNCONFIRMED",
    "OWNER_UNAVAILABLE",
    "REBOOT_UNCLEAN",
]
EndReason = Literal["USER_ENDED", "EXPIRED", "SESSION_REVOKED", "SOURCE_REVOKED", "RUNTIME_FAILED"]


class KakaoManualStart(FrozenModel):
    schema_version: Literal["kakao-manual-start/1.0"] = "kakao-manual-start/1.0"
    source_binding_id: KakaoBindingId

    @model_validator(mode="after")
    def checked(self) -> Self:
        validate_contract("kakao-manual-session-v1", self.model_dump(mode="json"))
        return self


class KakaoManualRenew(FrozenModel):
    schema_version: Literal["kakao-manual-command/1.0"] = "kakao-manual-command/1.0"
    action: Literal["RENEW"] = "RENEW"
    expected_grant_revision: KakaoResourceVersion

    @model_validator(mode="after")
    def checked(self) -> Self:
        validate_contract("kakao-manual-session-v1", self.model_dump(mode="json"))
        return self


class KakaoManualEnd(FrozenModel):
    schema_version: Literal["kakao-manual-command/1.0"] = "kakao-manual-command/1.0"
    action: Literal["END"] = "END"
    expected_resource_version: KakaoResourceVersion

    @model_validator(mode="after")
    def checked(self) -> Self:
        validate_contract("kakao-manual-session-v1", self.model_dump(mode="json"))
        return self


class KakaoManualSession(FrozenModel):
    schema_version: Literal["kakao-manual-session/1.0"] = "kakao-manual-session/1.0"
    lease_id: KakaoManualLeaseId
    source_binding_id: KakaoBindingId
    phase: Phase
    resource_version: KakaoResourceVersion
    grant_revision: int = Field(strict=True, ge=0, le=2147483647)
    created_at: UtcDatetime
    expires_at: UtcDatetime | None
    absolute_expires_at: UtcDatetime
    ready: bool = Field(strict=True)
    last_error: ManualError | None
    ended_reason: EndReason | None
    closed_at: UtcDatetime | None

    @model_validator(mode="after")
    def checked(self) -> Self:
        if (
            not self.created_at
            < self.absolute_expires_at
            <= self.created_at + timedelta(minutes=20)
        ):
            raise ValueError("KAKAO_REMOTE_DEADLINE_INVALID")
        if (self.grant_revision == 0) != (self.expires_at is None):
            raise ValueError("KAKAO_REMOTE_GRANT_INVALID")
        if (
            self.expires_at is not None
            and not self.created_at < self.expires_at <= self.absolute_expires_at
        ):
            raise ValueError("KAKAO_REMOTE_DEADLINE_INVALID")
        if self.ready and (
            self.phase != "ACTIVE" or self.grant_revision == 0 or self.closed_at is not None
        ):
            raise ValueError("KAKAO_REMOTE_READY_INVALID")
        if (self.phase == "ENDED") != (self.closed_at is not None):
            raise ValueError("KAKAO_REMOTE_CLOSURE_INVALID")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ValueError("KAKAO_REMOTE_CLOSURE_INVALID")
        validate_contract("kakao-manual-session-v1", self.model_dump(mode="json"))
        return self


class KakaoManualMutation(FrozenModel):
    session: KakaoManualSession
    replayed: bool = Field(strict=True)


class KakaoManualFreshProfile(FrozenModel):
    schema_version: Literal["kakao-manual-fresh-profile/1.0"] = "kakao-manual-fresh-profile/1.0"
    profile_id: KakaoProfileId
    observed_at: UtcDatetime
    boot_id: BootId
    never_used: bool = Field(strict=True)
    profile_empty: bool = Field(strict=True)
    browser_stopped: bool = Field(strict=True)
    gateway_stopped: bool = Field(strict=True)
    profile_lock_released: bool = Field(strict=True)

    @model_validator(mode="after")
    def checked(self) -> Self:
        validate_contract("kakao-manual-execution-v1", self.model_dump(mode="json"))
        return self


class _RuntimePins(FrozenModel):
    lease_id: KakaoManualLeaseId
    profile_id: KakaoProfileId
    browser_run_id: KakaoBrowserRunId
    command_sha256: Sha256
    fence_epoch: KakaoResourceVersion
    gateway_epoch: KakaoResourceVersion


class KakaoManualRuntimeObservation(_RuntimePins):
    schema_version: Literal["kakao-manual-runtime-observation/1.0"] = (
        "kakao-manual-runtime-observation/1.0"
    )
    observed_at: UtcDatetime
    boot_id: BootId
    invocation_id: InvocationId
    main_pid: int = Field(strict=True, ge=1, le=2147483647)
    started_monotonic_us: int = Field(strict=True, ge=1, le=9223372036854775807)
    browser_running: bool = Field(strict=True)
    profile_locked: bool = Field(strict=True)
    gateway_running: bool = Field(strict=True)
    gateway_invocation_id: InvocationId | None

    @model_validator(mode="after")
    def checked(self) -> Self:
        if self.gateway_running != (self.gateway_invocation_id is not None):
            raise ValueError("KAKAO_REMOTE_GATEWAY_OBSERVATION_INVALID")
        validate_contract("kakao-manual-execution-v1", self.model_dump(mode="json"))
        return self


class KakaoManualClosureObservation(_RuntimePins):
    schema_version: Literal["kakao-manual-closure-observation/1.0"] = (
        "kakao-manual-closure-observation/1.0"
    )
    observed_at: UtcDatetime
    kind: Literal["STOPPED", "PRE_READY_FAILED", "REBOOT_UNCLEAN"]
    dispatch_boot_id: BootId
    observed_boot_id: BootId
    browser_stopped: bool = Field(strict=True)
    gateway_stopped: bool = Field(strict=True)
    profile_lock_released: bool = Field(strict=True)

    @model_validator(mode="after")
    def checked(self) -> Self:
        if self.kind == "REBOOT_UNCLEAN" and (
            self.dispatch_boot_id is None or self.dispatch_boot_id == self.observed_boot_id
        ):
            raise ValueError("KAKAO_REMOTE_REBOOT_OBSERVATION_INVALID")
        validate_contract("kakao-manual-execution-v1", self.model_dump(mode="json"))
        return self


class KakaoManualIntent(_RuntimePins):
    schema_version: Literal["kakao-manual-intent/1.0"] = "kakao-manual-intent/1.0"
    source_binding_id: KakaoBindingId
    owner_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    dispatch_boot_id: BootId
    identity_session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    phase: Phase
    resource_version: KakaoResourceVersion
    grant_revision: int = Field(strict=True, ge=0, le=2147483647)
    created_at: UtcDatetime
    authorized_at: UtcDatetime | None
    expires_at: UtcDatetime | None
    absolute_expires_at: UtcDatetime
    browser: KakaoManualRuntimeObservation | None

    @model_validator(mode="after")
    def checked(self) -> Self:
        if (self.grant_revision == 0) != (self.authorized_at is None and self.expires_at is None):
            raise ValueError("KAKAO_REMOTE_GRANT_INVALID")
        if self.grant_revision and (self.authorized_at is None or self.expires_at is None):
            raise ValueError("KAKAO_REMOTE_GRANT_INVALID")
        if (
            not self.created_at
            < self.absolute_expires_at
            <= self.created_at + timedelta(minutes=20)
        ):
            raise ValueError("KAKAO_REMOTE_DEADLINE_INVALID")
        if (
            self.authorized_at is not None
            and self.expires_at is not None
            and not (
                self.created_at <= self.authorized_at < self.expires_at <= self.absolute_expires_at
                and self.expires_at <= self.authorized_at + timedelta(seconds=30)
            )
        ):
            raise ValueError("KAKAO_REMOTE_DEADLINE_INVALID")
        if self.browser and any(
            getattr(self, field) != getattr(self.browser, field)
            for field in _RuntimePins.model_fields
        ):
            raise ValueError("KAKAO_REMOTE_OBSERVATION_PIN_MISMATCH")
        validate_contract("kakao-manual-execution-v1", self.model_dump(mode="json"))
        return self
