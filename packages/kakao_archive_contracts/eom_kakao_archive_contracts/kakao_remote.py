"""Private remote values and rules, never a source of operator authority.

Only the authenticated owner builds CurrentRemoteAuthority and runtime observations.
They are not public request fields or worker output. The gateway receives the smaller
GatewayLeaseGrant without Identity sessions, bearer tokens or filesystem locations.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import AfterValidator, Field, StrictBool, model_validator

from .render import BindingId, FrozenModel, canonical_bytes

SCHEMA_SHA256 = "9a597d9da6b7283a89b34c97853197ef3f7413d656b9faed0cb802368d7258eb"
LEASE_TTL = timedelta(seconds=30)
LEASE_MAX_LIFETIME = timedelta(minutes=20)
AUTHORITY_MAX_AGE = timedelta(seconds=5)
REMOTE_ROOT = "/studio/admin/remote/"
WEBSOCKET_PATH = REMOTE_ROOT + "websockify"
Epoch = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
LeaseId = Annotated[str, Field(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]
ProfileId = Annotated[str, Field(pattern=r"^kakaoprofile_[0-9a-f]{32}$")]
BrowserRunId = Annotated[str, Field(pattern=r"^kakaobrowserrun_[0-9a-f]{32}$")]
OperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
IdentitySessionId = Annotated[str, Field(pattern=r"^apisession_[0-9a-f]{32}$")]
RuntimeMode = Literal["STOPPED", "AUTO", "PAUSING", "MANUAL", "AUTH_REQUIRED", "ERROR"]
SchemaKind = Literal[
    "lease", "authority", "runtime", "request", "grant", "revocation", "profile", "stop"
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("KAKAO_REMOTE_UTC_REQUIRED")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


class _LeaseWindow(FrozenModel):
    lease_id: LeaseId
    source_binding_id: BindingId
    profile_id: ProfileId
    fence_epoch: Epoch
    gateway_epoch: Epoch
    grant_revision: Epoch
    issued_at: UtcDatetime
    authorized_at: UtcDatetime
    expires_at: UtcDatetime
    absolute_expires_at: UtcDatetime

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if not (
            self.issued_at <= self.authorized_at < self.expires_at <= self.absolute_expires_at
            and self.absolute_expires_at <= self.issued_at + LEASE_MAX_LIFETIME
            and self.expires_at <= self.authorized_at + LEASE_TTL
        ):
            raise ValueError("KAKAO_REMOTE_LEASE_WINDOW_INVALID")
        return self


class RemoteLease(_LeaseWindow):
    schema_version: Literal["kakao-remote-lease/1.0"]
    operator_id: OperatorId
    identity_session_id: IdentitySessionId
    state: Literal["ACTIVE", "REVOKED", "EXPIRED"]
    ended_at: UtcDatetime | None

    @model_validator(mode="after")
    def terminal_state(self) -> Self:
        if (self.state == "ACTIVE") != (self.ended_at is None):
            raise ValueError("KAKAO_REMOTE_LEASE_STATE_INVALID")
        if self.ended_at is not None and self.ended_at < self.issued_at:
            raise ValueError("KAKAO_REMOTE_LEASE_STATE_INVALID")
        if self.state == "EXPIRED" and self.ended_at != self.expires_at:
            raise ValueError("KAKAO_REMOTE_LEASE_STATE_INVALID")
        return self


class CurrentRemoteAuthority(FrozenModel):
    """Server-derived current Identity/source result; never deserialize from a browser."""

    schema_version: Literal["kakao-remote-authority/1.0"]
    operator_id: OperatorId
    identity_session_id: IdentitySessionId
    source_binding_id: BindingId
    binding_owner_operator_id: OperatorId
    operator_active: StrictBool
    session_active: StrictBool
    is_admin: StrictBool
    remote_permission: StrictBool
    source_active: StrictBool
    source_access: StrictBool
    checked_at: UtcDatetime


class RemoteRuntime(FrozenModel):
    """Owner-observed runtime, not a browser-worker assertion that control is allowed."""

    schema_version: Literal["kakao-remote-runtime/1.0"]
    source_binding_id: BindingId
    profile_id: ProfileId
    mode: RuntimeMode
    fence_epoch: Epoch
    gateway_epoch: Epoch
    browser_run_id: BrowserRunId
    process_state: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    profile_locked: StrictBool
    available: StrictBool


class RemoteRequest(FrozenModel):
    schema_version: Literal["kakao-remote-request/1.0"]
    method: str = Field(min_length=1, max_length=16)
    path: str = Field(min_length=1, max_length=512)
    protocol: str = Field(min_length=1, max_length=16)
    origin: str | None = Field(min_length=1, max_length=256)
    upgrade: str | None = Field(max_length=64)
    connection: str | None = Field(max_length=128)
    websocket_version: str | None = Field(max_length=16)
    websocket_key: str | None = Field(max_length=64)


class GatewayLeaseGrant(_LeaseWindow):
    schema_version: Literal["kakao-remote-gateway-grant/1.0"]


class GatewayRevocation(FrozenModel):
    schema_version: Literal["kakao-remote-gateway-revocation/1.0"]
    lease_id: LeaseId
    fence_epoch: Epoch
    gateway_epoch: Epoch
    grant_revision: Epoch
    reason: Literal[
        "USER_ENDED",
        "LOGOUT",
        "SESSION_REVOKED",
        "ROLE_REVOKED",
        "SOURCE_REVOKED",
        "OWNER_UNAVAILABLE",
        "RUNTIME_LOST",
    ]


def gateway_execution_digest(grant: GatewayLeaseGrant) -> str:
    """Pin one immutable gateway execution; heartbeat revisions never change its identity."""
    values = grant.model_dump(
        mode="json", exclude={"schema_version", "grant_revision", "authorized_at", "expires_at"}
    )
    return "sha256:" + hashlib.sha256(canonical_bytes(values)).hexdigest()


class ProfileFence(FrozenModel):
    schema_version: Literal["kakao-profile-fence/1.0"]
    profile_id: ProfileId
    browser_run_id: BrowserRunId
    fence_epoch: Epoch
    mode: Literal["AUTO", "PAUSING", "MANUAL", "AUTH_REQUIRED", "ERROR"]


class ProfileStopReceipt(FrozenModel):
    """The runtime owner must observe all flags; a worker's self-report is insufficient."""

    schema_version: Literal["kakao-profile-stop-receipt/1.0"]
    profile_id: ProfileId
    browser_run_id: BrowserRunId
    fence_epoch: Epoch
    process_stopped: StrictBool
    profile_lock_released: StrictBool
    gateway_stopped: StrictBool
    checkpoint_committed: StrictBool
    observed_at: UtcDatetime


class RemoteAuthorizationError(PermissionError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class RemoteTransportPolicy(FrozenModel):
    """Installed gateway inventory, not user-supplied paths or upstreams."""

    expected_origin: str
    static_paths: frozenset[str] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        origin = urlsplit(self.expected_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
            or any(char.isspace() for char in self.expected_origin)
        ):
            raise ValueError("KAKAO_REMOTE_ORIGIN_CONFIG_INVALID")
        for path in self.static_paths:
            if (
                not path.startswith(REMOTE_ROOT)
                or path == WEBSOCKET_PATH
                or any(part in {"", ".", ".."} for part in path[len(REMOTE_ROOT) :].split("/"))
                or any(char in path for char in "?#%\\\x00\r\n")
            ):
                raise ValueError("KAKAO_REMOTE_ASSET_CONFIG_INVALID")
        return self


def _current_lease(
    lease: RemoteLease, authority: CurrentRemoteAuthority, runtime: RemoteRuntime, now: datetime
) -> None:
    _utc(now)
    if not authority.operator_active or not authority.session_active:
        raise RemoteAuthorizationError("KAKAO_REMOTE_AUTHENTICATION_REQUIRED", 401)
    if not timedelta(0) <= now - authority.checked_at <= AUTHORITY_MAX_AGE:
        raise RemoteAuthorizationError("KAKAO_REMOTE_AUTHORITY_STALE", 503)
    if (
        not authority.is_admin
        or not authority.remote_permission
        or not authority.source_active
        or not authority.source_access
        or authority.binding_owner_operator_id != authority.operator_id
        or lease.operator_id != authority.operator_id
        or lease.identity_session_id != authority.identity_session_id
        or lease.source_binding_id != authority.source_binding_id
    ):
        raise RemoteAuthorizationError("KAKAO_REMOTE_PERMISSION_DENIED", 403)
    if not runtime.available or runtime.process_state == "UNKNOWN":
        raise RemoteAuthorizationError("KAKAO_REMOTE_RUNTIME_UNAVAILABLE", 503)
    if (
        lease.state != "ACTIVE"
        or not lease.authorized_at <= now < lease.expires_at
        or runtime.mode != "MANUAL"
        or runtime.process_state != "RUNNING"
        or not runtime.profile_locked
        or (lease.source_binding_id, lease.profile_id, lease.fence_epoch, lease.gateway_epoch)
        != (
            runtime.source_binding_id,
            runtime.profile_id,
            runtime.fence_epoch,
            runtime.gateway_epoch,
        )
    ):
        raise RemoteAuthorizationError("KAKAO_REMOTE_LEASE_UNAVAILABLE", 403)


def authorize_remote_request(
    lease: RemoteLease,
    authority: CurrentRemoteAuthority,
    runtime: RemoteRuntime,
    request: RemoteRequest,
    policy: RemoteTransportPolicy,
    *,
    now: datetime,
) -> None:
    """Return only on admission. HTTP adapters map rejection to non-2xx, never false/200."""
    _current_lease(lease, authority, runtime, now)
    if request.method != "GET" or any(
        ord(char) < 32 or ord(char) == 127
        for value in request.model_dump(exclude={"schema_version"}).values()
        if value is not None
        for char in value
    ):
        raise RemoteAuthorizationError("KAKAO_REMOTE_TRANSPORT_DENIED", 403)
    if request.path == WEBSOCKET_PATH:
        try:
            key = base64.b64decode(request.websocket_key or "", validate=True)
        except (ValueError, binascii.Error):
            key = b""
        if (
            request.protocol != "HTTP/1.1"
            or request.origin != policy.expected_origin
            or (request.upgrade or "").lower() != "websocket"
            or "upgrade"
            not in {part.strip().lower() for part in (request.connection or "").split(",")}
            or request.websocket_version != "13"
            or len(key) != 16
        ):
            raise RemoteAuthorizationError("KAKAO_REMOTE_TRANSPORT_DENIED", 403)
    elif (
        request.path not in policy.static_paths
        or request.origin not in {None, policy.expected_origin}
        or request.upgrade
        or request.websocket_key
        or request.websocket_version
        or "upgrade" in {part.strip().lower() for part in (request.connection or "").split(",")}
    ):
        raise RemoteAuthorizationError("KAKAO_REMOTE_TRANSPORT_DENIED", 403)


def renew_remote_lease(
    lease: RemoteLease, authority: CurrentRemoteAuthority, runtime: RemoteRuntime, *, now: datetime
) -> RemoteLease:
    _current_lease(lease, authority, runtime, now)
    return RemoteLease.model_validate(
        {
            **lease.model_dump(),
            "grant_revision": lease.grant_revision + 1,
            "authorized_at": now,
            "expires_at": min(now + LEASE_TTL, lease.absolute_expires_at),
        }
    )


def end_remote_lease(lease: RemoteLease, *, now: datetime) -> RemoteLease:
    _utc(now)
    if lease.state != "ACTIVE":
        return lease
    expired = now >= lease.expires_at
    return RemoteLease.model_validate(
        {
            **lease.model_dump(),
            "state": "EXPIRED" if expired else "REVOKED",
            "ended_at": lease.expires_at if expired else now,
        }
    )


def gateway_grant(lease: RemoteLease) -> GatewayLeaseGrant:
    if lease.state != "ACTIVE":
        raise ValueError("KAKAO_REMOTE_LEASE_ENDED")
    return GatewayLeaseGrant.model_validate(
        {
            **lease.model_dump(exclude={"operator_id", "identity_session_id", "state", "ended_at"}),
            "schema_version": "kakao-remote-gateway-grant/1.0",
        }
    )


_HANDOFFS = {
    "AUTO": frozenset({"STOPPED"}),
    "PAUSING": frozenset({"MANUAL", "STOPPED"}),
    "MANUAL": frozenset({"AUTO", "STOPPED"}),
    "AUTH_REQUIRED": frozenset({"MANUAL", "STOPPED"}),
    "ERROR": frozenset({"STOPPED"}),
}


def validate_profile_handoff(
    prior: ProfileFence,
    stopped: ProfileStopReceipt,
    *,
    target_mode: Literal["AUTO", "MANUAL", "STOPPED"],
    next_fence: int,
    now: datetime,
) -> None:
    """Physical exclusion only; caller still owns current authorization, intent and probe.

    This never starts a browser or declares that Kakao login/channel verification passed.
    AUTO must enter PAUSING before it can hand off to MANUAL.
    """
    _utc(now)
    if target_mode not in _HANDOFFS[prior.mode]:
        raise ValueError("KAKAO_PROFILE_TRANSITION_INVALID")
    if type(next_fence) is not int or not prior.fence_epoch < next_fence <= 2147483647:
        raise ValueError("KAKAO_PROFILE_FENCE_INVALID")
    if (
        (prior.profile_id, prior.browser_run_id, prior.fence_epoch)
        != (stopped.profile_id, stopped.browser_run_id, stopped.fence_epoch)
        or not stopped.process_stopped
        or not stopped.profile_lock_released
        or stopped.observed_at > now
        or (prior.mode in {"AUTO", "PAUSING"} and not stopped.checkpoint_committed)
        or (prior.mode == "MANUAL" and not stopped.gateway_stopped)
    ):
        raise ValueError("KAKAO_PROFILE_PRIOR_STOP_UNCONFIRMED")


@lru_cache(maxsize=8)
def _validator(kind: SchemaKind) -> Draft202012Validator:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/private-remote-runtime-v1.schema.json")
        .read_bytes()
    )
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise ValueError("KAKAO_REMOTE_SCHEMA_HASH_MISMATCH")
    schema: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    schema.pop("oneOf")
    schema["$ref"] = "#/$defs/" + kind
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_remote_contract(kind: SchemaKind, value: object) -> None:
    try:
        _validator(kind).validate(value)
    except ValidationError as exc:
        raise ValueError("KAKAO_REMOTE_SCHEMA_INVALID") from exc
