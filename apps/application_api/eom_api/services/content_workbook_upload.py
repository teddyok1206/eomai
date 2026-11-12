"""One bounded XLSX materialization at the existing private Catalog socket."""

from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.content_workbook_import import PrepareContentWorkbookRequest


def send_workbook_upload(
    command: PrepareContentWorkbookRequest,
    content: bytes,
    *,
    socket_path: Path,
    validate_socket: Callable[[], None],
    read_response: Callable[[socket.socket], bytes],
    connect_timeout: float,
    response_timeout: float,
) -> dict[str, object]:
    if (
        len(content) != command.content_length
        or "sha256:" + hashlib.sha256(content).hexdigest() != command.sha256
    ):
        raise ValueError("workbook bytes differ from their request identity")
    encoded = json.dumps(
        command.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        raise ValueError("workbook request header exceeds its bound")
    validate_socket()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(connect_timeout)
        connection.connect(str(socket_path))
        connection.settimeout(response_timeout)
        connection.sendall(encoded + b"\n")
        connection.sendall(content)
        connection.shutdown(socket.SHUT_WR)
        value: object = json.loads(read_response(connection))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("workbook response is not an object")
    return value
