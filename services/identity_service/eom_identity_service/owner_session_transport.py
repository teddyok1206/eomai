"""Genuine capture export and admitted held-peer import; no installed provider supplied."""

from __future__ import annotations

import os
import re
import socket
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import current_thread
from typing import Protocol, cast
from weakref import ReferenceType, ref

from eom_operator_identity.owner_session_capture import (
    OwnerSessionCaptureRequest,
    OwnerSessionCaptureResponse,
    owner_session_capture_request_sha256,
    parse_owner_session_capture_response,
    validate_owner_session_capture_response,
)

from eom_identity_service.authenticated_session_fence import (
    AuthenticatedOperatorSession,
    _capture_values,
    _CapturedValues,
    _new_authenticated_capture,
)

OWNER_SESSION_TRANSPORT_SECONDS = 10


class OwnerSessionTransportError(ValueError):
    """Only a fixed content-free code can cross the boundary."""

    def __init__(self, code: str) -> None:
        if code not in {
            "OWNER_SESSION_EXPORT_INVALID",
            "OWNER_SESSION_OBSERVATION_INVALID",
            "OWNER_SESSION_PROVIDER_UNAVAILABLE",
            "OWNER_SESSION_TRANSPORT_EXPIRED",
            "OWNER_SESSION_TRANSPORT_UNAVAILABLE",
            "OWNER_SESSION_AUTHENTICATION_DENIED",
        }:
            code = "OWNER_SESSION_TRANSPORT_UNAVAILABLE"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedIdentityProviderPin:
    """Trusted existing API release/config pins; neither a new entity nor admission."""

    source_commit: str
    wheel_sha256: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None
        ):
            raise OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE")
        for value in (self.wheel_sha256, self.configuration_sha256):
            if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE")


class IdentityOwnerSessionProviderAdmission(Protocol):
    """Mandatory actual protected process/provider/config observer, not a DTO echo.

    A source callback is not installed admission. Trusted root composition must
    bind the actual API peer/release/config and protected key ownership separately.
    No default, boolean grant, key reader or installer exists here.
    """

    def assert_current(
        self, *, source_commit: str, wheel_sha256: str, configuration_sha256: str
    ) -> None: ...


def assert_identity_provider_current(
    pin: FixedIdentityProviderPin, admission: IdentityOwnerSessionProviderAdmission
) -> None:
    """Call mandatory actual installed admission against the exact configured pins."""
    if type(pin) is not FixedIdentityProviderPin or admission is None:
        raise OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE")
    pin.__post_init__()
    try:
        returned = cast(Callable[..., object], admission.assert_current)(
            source_commit=pin.source_commit,
            wheel_sha256=pin.wheel_sha256,
            configuration_sha256=pin.configuration_sha256,
        )
        if returned is not None:
            raise ValueError("admission assertions must not return grants")
    except Exception:
        raise OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE") from None


def export_owner_session_capture(
    request: OwnerSessionCaptureRequest, capture: AuthenticatedOperatorSession
) -> OwnerSessionCaptureResponse:
    """Read a genuine Identity-created capture only, after the existing HMAC path."""
    try:
        request_sha = owner_session_capture_request_sha256(request)
        values = _capture_values(capture)
        return OwnerSessionCaptureResponse(
            schema_version="operator-owner-session-capture-response/1.0",
            request_sha256=request_sha,
            observed_at=datetime.now(UTC),
            operator_id=values.operator_id,
            session_id=values.session_id,
            access_token_id=values.token_id,
            verifier_digest=values.verifier_hash,
            issued_at=values.issued_at,
            access_expires_at=values.access_expires_at,
            authenticated_at=values.authenticated_at,
            absolute_expires_at=values.absolute_expires_at,
            idle_expires_at=values.idle_expires_at,
            refresh_generation=values.refresh_generation,
        )
    except Exception:
        raise OwnerSessionTransportError("OWNER_SESSION_EXPORT_INVALID") from None


def _socket_epoch(connection: socket.socket) -> tuple[object, ...]:
    if not isinstance(connection, socket.socket):
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
    metadata = os.fstat(connection.fileno())
    peer, local = connection.getpeername(), connection.getsockname()
    if (
        connection.family != socket.AF_INET
        or connection.type != socket.SOCK_STREAM
        or not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or peer != ("127.0.0.1", 8765)
        or not isinstance(local, tuple)
        or len(local) != 2
        or local[0] != "127.0.0.1"
        or type(local[1]) is not int
        or not 0 < local[1] <= 65535
    ):
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
    return (
        connection.fileno(),
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        peer,
        local,
    )


@dataclass(slots=True, repr=False)
class _ObservationOrigin:
    observation: ReferenceType[OwnerSessionTransportObservation]
    request: OwnerSessionCaptureRequest
    response: OwnerSessionCaptureResponse
    response_identity: tuple[object, ...]
    connection: socket.socket
    epoch: tuple[object, ...]
    pin: FixedIdentityProviderPin
    pin_identity: tuple[str, str, str]
    admission: IdentityOwnerSessionProviderAdmission
    verify_peer: Callable[[socket.socket], None]
    started_at: datetime
    deadline: float
    thread: object
    used: bool = False


class OwnerSessionTransportObservation:
    """Opaque one-use live observation, not a serializable received response or grant."""

    __slots__ = ("__weakref__", "_origin")
    _origin: _ObservationOrigin

    def __init__(self) -> None:
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("owner-session observation is immutable")

    def __repr__(self) -> str:
        return "<OwnerSessionTransportObservation>"


def _response_identity(response: OwnerSessionCaptureResponse) -> tuple[object, ...]:
    return tuple(getattr(response, name) for name in type(response).model_fields)


def _current(origin: _ObservationOrigin) -> None:
    assert_identity_provider_current(origin.pin, origin.admission)
    returned = cast(Callable[..., object], origin.verify_peer)(origin.connection)
    if (
        returned is not None
        or origin.pin_identity
        != (origin.pin.source_commit, origin.pin.wheel_sha256, origin.pin.configuration_sha256)
        or current_thread() is not origin.thread
        or _socket_epoch(origin.connection) != origin.epoch
        or _response_identity(origin.response) != origin.response_identity
    ):
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
    checked = validate_owner_session_capture_response(origin.request, origin.response)
    now = datetime.now(UTC)
    if (
        origin.started_at.utcoffset() != timedelta(0)
        or not origin.started_at <= checked.observed_at <= now
        or (now - origin.started_at).total_seconds() > OWNER_SESSION_TRANSPORT_SECONDS
        or time.monotonic() >= origin.deadline
        or now
        >= min(checked.access_expires_at, checked.idle_expires_at, checked.absolute_expires_at)
    ):
        raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_EXPIRED")


def observe_owner_session_transport(
    *,
    request: OwnerSessionCaptureRequest,
    response_raw: bytes,
    connection: socket.socket,
    pin: FixedIdentityProviderPin,
    admission: IdentityOwnerSessionProviderAdmission,
    verify_peer: Callable[[socket.socket], None],
    started_at: datetime,
    deadline: float,
) -> OwnerSessionTransportObservation:
    """Actual adapter observation only; all configured observers are mandatory.

    Python construction provenance is not cryptographic/unforgeable security;
    independently installed provider/peer admission is still required.
    """
    try:
        assert_identity_provider_current(pin, admission)
        epoch = _socket_epoch(connection)
        verify_peer(connection)
        request = OwnerSessionCaptureRequest.model_validate(request)
        response = validate_owner_session_capture_response(
            request, parse_owner_session_capture_response(response_raw)
        )
        if (
            type(started_at) is not datetime
            or started_at.utcoffset() != timedelta(0)
            or type(deadline) is not float
            or not time.monotonic() < deadline
            or deadline - time.monotonic() > OWNER_SESSION_TRANSPORT_SECONDS
        ):
            raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_EXPIRED")
        observation = object.__new__(OwnerSessionTransportObservation)
        origin = _ObservationOrigin(
            ref(observation),
            request,
            response,
            _response_identity(response),
            connection,
            epoch,
            pin,
            (pin.source_commit, pin.wheel_sha256, pin.configuration_sha256),
            admission,
            verify_peer,
            started_at,
            deadline,
            current_thread(),
        )
        _current(origin)
        object.__setattr__(observation, "_origin", origin)
        return observation
    except OwnerSessionTransportError:
        raise
    except Exception:
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID") from None


def import_owner_session_capture(
    observation: OwnerSessionTransportObservation,
) -> AuthenticatedOperatorSession:
    """Consume the exact independently admitted live observation; a DTO cannot mint."""
    try:
        if type(observation) is not OwnerSessionTransportObservation:
            raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
        origin = getattr(observation, "_origin", None)
        if type(origin) is not _ObservationOrigin or origin.observation() is not observation:
            raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
        # One caller thread, one use. No reusable transport approval escapes.
        if origin.used:
            raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID")
        origin.used = True
        _current(origin)
        reply = origin.response
        return _new_authenticated_capture(
            _CapturedValues(
                reply.operator_id,
                reply.session_id,
                reply.access_token_id,
                reply.verifier_digest,
                reply.issued_at,
                reply.access_expires_at,
                reply.authenticated_at,
                reply.absolute_expires_at,
                reply.idle_expires_at,
                reply.refresh_generation,
            )
        )
    except OwnerSessionTransportError:
        raise
    except Exception:
        raise OwnerSessionTransportError("OWNER_SESSION_OBSERVATION_INVALID") from None
