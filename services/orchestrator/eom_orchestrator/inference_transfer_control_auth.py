"""FD-only authentication against the fixed installed Application API.

The reverse connected TCP socket UID is checked before an Authorization header
is sent. A successful loopback HTTP response, listener or caller-supplied ID is
not independently trusted as the API service identity.
"""

from __future__ import annotations

import http.client
import json
import os
import pwd
import re
import socket
import stat
import time
from contextlib import suppress
from typing import Any

from eom_api_contracts.auth import CurrentOperator
from eom_api_contracts.common import SingleResponse
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import SecretStr

from eom_orchestrator.control_service import ControlPlaneError

_API_HOST = "127.0.0.1"
_API_PORT = 8765
_AUTH_PATH = "/api/v1/auth/me"
_TOKEN_BYTES = 512
_REPLY_BYTES = 64 * 1024
_TCP_TABLE_BYTES = 4 * 1024 * 1024
_TCP_TABLE_ROWS = 16384
_TCP_ATTEMPTS = 5
_TOKEN_PATTERN = re.compile(r"eom_at_[A-Za-z0-9_.-]+", re.ASCII)
_CURRENT_OPERATOR_SCHEMA = SingleResponse[CurrentOperator].model_json_schema()
_CURRENT_OPERATOR_VALIDATOR = Draft202012Validator(
    _CURRENT_OPERATOR_SCHEMA, format_checker=FormatChecker()
)


def read_control_bearer_fd(descriptor: int) -> SecretStr:
    """Consume a bounded inherited FD; never accept a pathname or token argument.

    Pipes must already contain their complete token and EOF. Nonblocking reads
    prevent a stalled producer from hanging a privileged owner indefinitely.
    A regular FD is accepted only when privately owned by the actual owner.
    """
    if type(descriptor) is not int or descriptor < 3:
        raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "credential FD is invalid")
    try:
        metadata = os.fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            if (
                metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 0 < metadata.st_size <= _TOKEN_BYTES
            ):
                raise ValueError("credential file boundary differs")
        elif not stat.S_ISFIFO(metadata.st_mode):
            raise ValueError("credential FD type is unsupported")
        os.set_inheritable(descriptor, False)
        os.set_blocking(descriptor, False)
        chunks: list[bytes] = []
        remaining = _TOKEN_BYTES + 1
        while remaining:
            member = os.read(descriptor, remaining)
            if not member:
                break
            chunks.append(member)
            remaining -= len(member)
        payload = b"".join(chunks)
        if len(payload) > _TOKEN_BYTES:
            raise ValueError("credential FD exceeds its bound")
        token = payload.removesuffix(b"\n").decode("ascii")
        if _TOKEN_PATTERN.fullmatch(token) is None:
            raise ValueError("credential FD content is invalid")
        return SecretStr(token)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_AUTHORIZATION_REQUIRED", "credential FD is unavailable or invalid"
        ) from exc
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _tcp_endpoint(endpoint: tuple[str, int]) -> str:
    host, port = endpoint
    if host != _API_HOST or not 0 < port <= 65535:
        raise ValueError("non-loopback TCP endpoint")
    return socket.inet_aton(host)[::-1].hex().upper() + f":{port:04X}"


def _reverse_tcp_uid(raw: bytes, *, local: str, remote: str) -> int | None:
    """Lookup one exact established reverse four-tuple in bounded kernel data."""
    if len(raw) > _TCP_TABLE_BYTES:
        raise ValueError("TCP table byte bound exceeded")
    lines = raw.decode("ascii").splitlines()
    if not lines or len(lines) > _TCP_TABLE_ROWS + 1:
        raise ValueError("TCP table row bound exceeded")
    if "local_address" not in lines[0] or "rem_address" not in lines[0]:
        raise ValueError("TCP table header differs")
    matches: list[int] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10:
            raise ValueError("TCP table row is incomplete")
        if fields[1] == remote and fields[2] == local and fields[3] == "01":
            uid = int(fields[7])
            if uid < 0 or int(fields[9]) <= 0:
                raise ValueError("TCP peer identity is incomplete")
            matches.append(uid)
    if len(matches) > 1:
        raise ValueError("connected peer identity is ambiguous")
    return matches[0] if matches else None


def _require_api_peer_socket(connection: socket.socket) -> None:
    try:
        if connection.family != socket.AF_INET or connection.type != socket.SOCK_STREAM:
            raise ValueError("API socket type differs")
        local_address = connection.getsockname()
        remote_address = connection.getpeername()
        if remote_address != (_API_HOST, _API_PORT):
            raise ValueError("API peer endpoint differs")
        local = _tcp_endpoint(local_address)
        remote = _tcp_endpoint(remote_address)
        expected = pwd.getpwnam("eom-api").pw_uid
        if expected <= 0:
            raise ValueError("API UID is invalid")
        for attempt in range(_TCP_ATTEMPTS):
            descriptor = os.open("/proc/net/tcp", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                chunks: list[bytes] = []
                remaining = _TCP_TABLE_BYTES + 1
                while remaining:
                    member = os.read(descriptor, min(remaining, 64 * 1024))
                    if not member:
                        break
                    chunks.append(member)
                    remaining -= len(member)
            finally:
                os.close(descriptor)
            actual = _reverse_tcp_uid(b"".join(chunks), local=local, remote=remote)
            if actual is not None:
                if actual != expected:
                    raise ValueError("API connected socket UID differs")
                return
            if attempt + 1 < _TCP_ATTEMPTS:
                time.sleep(0.01)
        raise ValueError("API connected socket identity unavailable")
    except (KeyError, OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ControlPlaneError(
            "CONTROL_AUTH_SERVICE_UNAVAILABLE", "fixed API connected peer is unavailable"
        ) from exc


def require_fixed_api_peer_socket(connection: socket.socket) -> None:
    """Supported peer proof for the fixed official API, before any secret bytes."""
    _require_api_peer_socket(connection)


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = member
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON constant")


class FixedApiControlPrincipalReader:
    """Existing official authentication only; no refresh, login or implicit retry."""

    def __init__(self, bearer: SecretStr) -> None:
        token = bearer.get_secret_value()
        if len(token) > _TOKEN_BYTES or _TOKEN_PATTERN.fullmatch(token) is None:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "credential is invalid")
        self._bearer = bearer

    def read(self) -> CurrentOperator:
        connection = http.client.HTTPConnection(_API_HOST, _API_PORT, timeout=10.0)
        try:
            connection.connect()
            if connection.sock is None:
                raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "API socket absent")
            _require_api_peer_socket(connection.sock)
            connection.request(
                "GET",
                _AUTH_PATH,
                headers={
                    "Authorization": "Bearer " + self._bearer.get_secret_value(),
                    "Accept": "application/json",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "authentication denied")
            if (
                response.status != 200
                or response.getheader("Content-Type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                raise ValueError("API authentication response is unavailable")
            payload = response.read(_REPLY_BYTES + 1)
            if not payload or len(payload) > _REPLY_BYTES:
                raise ValueError("API authentication response exceeds its bound")
            raw = json.loads(
                payload, object_pairs_hook=_json_object, parse_constant=_reject_constant
            )
            _CURRENT_OPERATOR_VALIDATOR.validate(raw)
            return SingleResponse[CurrentOperator].model_validate(raw).data
        except ControlPlaneError:
            raise
        except Exception as exc:
            # Neither exception text, response content nor token reaches callers.
            raise ControlPlaneError(
                "CONTROL_AUTH_SERVICE_UNAVAILABLE", "official authentication is unavailable"
            ) from exc
        finally:
            connection.close()
