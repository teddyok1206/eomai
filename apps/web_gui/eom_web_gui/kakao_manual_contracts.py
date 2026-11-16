"""Small browser values; runtime handles and login credentials never cross the BFF."""

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_web_gui.contracts import UtcDatetime, WebModel
from eom_web_gui.kakao_archive_contracts import ResourceVersion

LeaseId = Annotated[str, Field(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]


class ManualStart(WebModel):
    schema_version: Literal["kakao-manual-start/1.0"]
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")


class ManualRenew(WebModel):
    schema_version: Literal["kakao-manual-command/1.0"]
    action: Literal["RENEW"]
    expected_grant_revision: ResourceVersion


class ManualEnd(WebModel):
    schema_version: Literal["kakao-manual-command/1.0"]
    action: Literal["END"]
    expected_resource_version: ResourceVersion


ManualCommand = Annotated[ManualRenew | ManualEnd, Field(discriminator="action")]


class ManualSession(WebModel):
    schema_version: Literal["kakao-manual-session/1.0"]
    lease_id: LeaseId
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    phase: Literal["PREPARING", "ACTIVE", "STOPPING", "ENDED", "ERROR"]
    resource_version: ResourceVersion
    grant_revision: int = Field(strict=True, ge=0, le=2147483647)
    created_at: UtcDatetime
    expires_at: UtcDatetime | None
    absolute_expires_at: UtcDatetime
    ready: bool = Field(strict=True)
    last_error: (
        Literal[
            "START_FAILED",
            "RUNTIME_LOST",
            "GATEWAY_START_FAILED",
            "STOP_UNCONFIRMED",
            "OWNER_UNAVAILABLE",
            "REBOOT_UNCLEAN",
        ]
        | None
    )
    ended_reason: (
        Literal["USER_ENDED", "EXPIRED", "SESSION_REVOKED", "SOURCE_REVOKED", "RUNTIME_FAILED"]
        | None
    )
    closed_at: UtcDatetime | None

    @model_validator(mode="after")
    def safe_display(self) -> Self:
        if (
            not self.created_at
            < self.absolute_expires_at
            <= self.created_at + timedelta(minutes=20)
        ):
            raise ValueError("invalid manual deadline")
        if (self.grant_revision == 0) != (self.expires_at is None):
            raise ValueError("invalid manual grant")
        if (
            self.expires_at is not None
            and not self.created_at < self.expires_at <= self.absolute_expires_at
        ):
            raise ValueError("invalid manual expiry")
        if self.ready and (
            self.phase != "ACTIVE" or not self.grant_revision or self.closed_at is not None
        ):
            raise ValueError("invalid manual ready")
        if (self.phase == "ENDED") != (self.closed_at is not None):
            raise ValueError("invalid manual closure")
        return self


class ManualMutation(WebModel):
    session: ManualSession
    replayed: bool = Field(strict=True)
