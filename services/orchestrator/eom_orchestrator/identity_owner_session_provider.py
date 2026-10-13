"""One fixed authenticated API exchange before owner SQL; no key or admission default."""

from __future__ import annotations

import http.client
import os
import secrets
import socket
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.owner_session_transport import (
    OWNER_SESSION_TRANSPORT_SECONDS,
    FixedIdentityProviderPin,
    IdentityOwnerSessionProviderAdmission,
    OwnerSessionTransportError,
    assert_identity_provider_current,
    import_owner_session_capture,
    observe_owner_session_transport,
)
from eom_operator_identity.owner_session_capture import (
    MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
    OwnerSessionCaptureRequest,
    owner_session_capture_bytes,
)

from eom_orchestrator.inference_transfer_control_auth import (
    read_control_bearer_fd,
    require_fixed_api_peer_socket,
)
from eom_orchestrator.inference_transfer_control_invocation import (
    require_inference_transfer_control_owner,
)

_HOST = "127.0.0.1"
_PORT = 8765
_PATH = "/api/v1/auth/owner-session-capture"


@dataclass(frozen=True, slots=True)
class FixedIdentityOwnerSessionProvider:
    """Root-configured existing release/config pins and mandatory actual admission.

    Tests' callbacks/sockets establish source order only. An actual protected
    installed provider/config observer must be composed before production use.
    """

    pin: FixedIdentityProviderPin
    admission: IdentityOwnerSessionProviderAdmission

    def __post_init__(self) -> None:
        if type(self.pin) is not FixedIdentityProviderPin or self.admission is None:
            raise OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE")
        self.pin.__post_init__()

    def capture_access_from_fd(self, descriptor: int) -> AuthenticatedOperatorSession:
        """Consume exactly one inherited FD and one exchange; never refresh/cache/reconnect."""
        connection: http.client.HTTPConnection | None = None
        peer: socket.socket | None = None
        consumed = False
        try:
            require_inference_transfer_control_owner()
            assert_identity_provider_current(self.pin, self.admission)
            consumed = True
            # The supported FD reader owns close on both success and failure.
            bearer = read_control_bearer_fd(descriptor)
            started_at, began = datetime.now(UTC), time.monotonic()
            deadline = began + OWNER_SESSION_TRANSPORT_SECONDS
            request = OwnerSessionCaptureRequest(
                schema_version="operator-owner-session-capture-request/1.0",
                request_id="ownercapture_" + secrets.token_hex(16),
                nonce=secrets.token_hex(32),
                purpose="LOCAL_EMBEDDING_OPERATOR_SEED",
            )
            body = owner_session_capture_bytes(request)
            connection = http.client.HTTPConnection(
                _HOST, _PORT, timeout=OWNER_SESSION_TRANSPORT_SECONDS
            )
            connection.connect()
            peer = connection.sock
            if peer is None:
                raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_UNAVAILABLE")
            require_fixed_api_peer_socket(peer)
            assert_identity_provider_current(self.pin, self.admission)

            def remaining() -> None:
                value = deadline - time.monotonic()
                if value <= 0:
                    raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_EXPIRED")
                peer.settimeout(value)

            remaining()
            connection.request(
                "POST",
                _PATH,
                body=body,
                headers={
                    "Authorization": "Bearer " + bearer.get_secret_value(),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Connection": "keep-alive",
                },
            )
            # Drop the operation's bearer reference; no persistence or refresh.
            del bearer
            remaining()
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise OwnerSessionTransportError("OWNER_SESSION_AUTHENTICATION_DENIED")
            size = response.getheader("Content-Length", "")
            if (
                response.status != 200
                or response.getheader("Content-Type", "").split(";")[0].strip().lower()
                != "application/json"
                or response.getheader("Connection", "").strip().lower() == "close"
                or response.getheader("Transfer-Encoding") is not None
                or len(size) > 10
                or not size.isascii()
                or not size.isdigit()
                or not 0 < int(size) <= MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES
                or connection.sock is not peer
            ):
                raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_UNAVAILABLE")
            remaining()
            raw = response.read(MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES + 1)
            remaining()
            if type(raw) is not bytes or len(raw) != int(size):
                raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_UNAVAILABLE")
            observed = observe_owner_session_transport(
                request=request,
                response_raw=raw,
                connection=peer,
                pin=self.pin,
                admission=self.admission,
                verify_peer=require_fixed_api_peer_socket,
                started_at=started_at,
                deadline=deadline,
            )
            capture = import_owner_session_capture(observed)
            remaining()
            return capture
        except OwnerSessionTransportError:
            raise
        except Exception:
            raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_UNAVAILABLE") from None
        finally:
            cleanup_failed = False
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    cleanup_failed = True
            if peer is not None:
                try:
                    peer.close()
                except Exception:
                    cleanup_failed = True
            if not consumed and type(descriptor) is int and descriptor >= 3:
                with suppress(OSError):
                    os.close(descriptor)
            if cleanup_failed:
                raise OwnerSessionTransportError("OWNER_SESSION_TRANSPORT_UNAVAILABLE") from None
