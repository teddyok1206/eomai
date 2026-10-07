"""Bounded private chat socket transport shared by owner and worker adapters.

One EOF-delimited JSON line per direction; no pipelining or automatic replay.
It contains neither command dispatch nor conversation/queue business rules.
"""

from __future__ import annotations

import json
import math
import os
import socket
import stat
import struct
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, cast

from eom_identifiers import canonical_json_bytes

OWNER_REQUEST_LIMIT = 256000
OWNER_REPLY_LIMIT = 16 * 1048576
OWNER_SOCKET = Path("/run/eom-general-chat/owner.sock")
OWNER_RPC_TIMEOUT = 45.0
WORKER_FRAME_LIMIT = 256000
WORKER_PROBE_TIMEOUT = 5.0
WORKER_EXECUTE_TIMEOUT = 945.0


class ChatTransportError(RuntimeError):
    def __init__(self, kind: Literal["UNAVAILABLE", "INVALID"]):
        self.kind = kind
        super().__init__("GENERAL_CHAT_TRANSPORT_" + kind)


def chat_peer_uid(connection: socket.socket) -> int:
    try:
        value = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        if not isinstance(value, bytes):
            raise ValueError()
        _pid, uid, _gid = struct.unpack("3i", value)
        return int(uid)
    except (OSError, ValueError, struct.error):
        raise ChatTransportError("INVALID") from None


@dataclass(frozen=True, slots=True)
class ChatSocketEndpoint:
    path: Path
    owner_uid: int
    group_gid: int

    def require_parent(self) -> None:
        try:
            parent = self.path.parent.lstat()
            if (
                not self.path.is_absolute()
                or ".." in self.path.parts
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != self.owner_uid
                or parent.st_gid != self.group_gid
                or stat.S_IMODE(parent.st_mode) != 0o750
            ):
                raise ChatTransportError("INVALID")
        except FileNotFoundError:
            raise ChatTransportError("UNAVAILABLE") from None
        except OSError:
            raise ChatTransportError("INVALID") from None

    def require_socket(self) -> None:
        self.require_parent()
        try:
            node = self.path.lstat()
            if (
                not stat.S_ISSOCK(node.st_mode)
                or node.st_uid != self.owner_uid
                or node.st_gid != self.group_gid
                or stat.S_IMODE(node.st_mode) != 0o660
            ):
                raise ChatTransportError("INVALID")
        except FileNotFoundError:
            raise ChatTransportError("UNAVAILABLE") from None
        except OSError:
            raise ChatTransportError("INVALID") from None


def receive_chat_frame(connection: socket.socket, *, limit: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ChatTransportError("UNAVAILABLE")
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(min(65536, limit + 1 - size))
        except (OSError, TimeoutError):
            raise ChatTransportError("UNAVAILABLE") from None
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ChatTransportError("INVALID")
        chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload.endswith(b"\n") or b"\n" in payload[:-1]:
        raise ChatTransportError("INVALID")
    return payload[:-1]


def send_chat_frame(
    connection: socket.socket, payload: bytes, *, limit: int, deadline: float
) -> None:
    if not payload or len(payload) + 1 > limit or b"\n" in payload:
        raise ChatTransportError("INVALID")
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ChatTransportError("UNAVAILABLE")
    connection.settimeout(remaining)
    try:
        connection.sendall(payload + b"\n")
        connection.shutdown(socket.SHUT_WR)
    except OSError:
        raise ChatTransportError("UNAVAILABLE") from None


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise ChatTransportError("INVALID")
        value[key] = member
    return value


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ChatTransportError("INVALID")
    return number


def _no_constant(_: str) -> object:
    raise ChatTransportError("INVALID")


def decode_chat_frame(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_fields,
            parse_constant=_no_constant,
            parse_float=_finite_float,
        )
        if not isinstance(value, dict):
            raise ChatTransportError("INVALID")
        return cast(dict[str, object], value)
    except (ValueError, UnicodeError, RecursionError):
        raise ChatTransportError("INVALID") from None


def exchange_chat_frame(
    endpoint: ChatSocketEndpoint,
    document: dict[str, object],
    *,
    request_limit: int,
    reply_limit: int,
    timeout: float,
) -> dict[str, object]:
    endpoint.require_socket()
    deadline = monotonic() + timeout
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(max(0.001, deadline - monotonic()))
            connection.connect(str(endpoint.path))
            if chat_peer_uid(connection) != endpoint.owner_uid:
                raise ChatTransportError("INVALID")
            send_chat_frame(
                connection, canonical_json_bytes(document), limit=request_limit, deadline=deadline
            )
            payload = receive_chat_frame(connection, limit=reply_limit, deadline=deadline)
    except OSError:
        raise ChatTransportError("UNAVAILABLE") from None
    return decode_chat_frame(payload)


def bind_chat_listener(endpoint: ChatSocketEndpoint, *, backlog: int) -> socket.socket:
    endpoint.require_parent()
    if os.geteuid() != endpoint.owner_uid:
        raise ChatTransportError("INVALID")
    # Never overwrite/unlink a stale or another process's endpoint during startup.
    if endpoint.path.exists() or endpoint.path.is_symlink():
        raise ChatTransportError("INVALID")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(endpoint.path))
        os.chown(endpoint.path, -1, endpoint.group_gid)
        endpoint.path.chmod(0o660)
        endpoint.require_socket()
        listener.listen(backlog)
        listener.settimeout(0.25)
        return listener
    except BaseException:
        listener.close()
        raise
