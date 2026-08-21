"""Private Unix-socket streaming boundary for validated HWPX artifacts."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import socketserver
import stat
import struct
from pathlib import Path
from typing import Any, cast

from eom_hwpx_contracts import (
    HwpxManagerDownloadRequest,
    HwpxManagerDownloadResponse,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from eom_hwpx_manager.application_service import HwpxApplicationService
from eom_hwpx_manager.errors import HwpxManagerError

MANAGER_SOCKET = Path("/run/eom-hwpx-api/manager.sock")
MAX_HEADER_BYTES = 4096
SOCKET_MODE = 0o660
RUNTIME_DIRECTORY_MODE = 0o750


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = True


class _DownloadHandler(socketserver.StreamRequestHandler):
    server: HwpxDownloadServer

    def handle(self) -> None:
        if not self.server.peer_is_allowed(self.request):
            return
        raw = self.rfile.readline(MAX_HEADER_BYTES + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_HEADER_BYTES:
            self.server.write_error(self.wfile, "HWPX_DOWNLOAD_REQUEST_INVALID")
            return
        try:
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("manager-download", value, definition="request")
            request = HwpxManagerDownloadRequest.model_validate(value)
        except (UnicodeError, ValueError, json.JSONDecodeError, JsonSchemaValidationError):
            self.server.write_error(self.wfile, "HWPX_DOWNLOAD_REQUEST_INVALID")
            return
        try:
            download = self.server.service.secure_download(request.build_id)
        except HwpxManagerError as exc:
            self.server.write_error(self.wfile, exc.code.value)
            return
        header = HwpxManagerDownloadResponse(
            status="OK",
            filename=download.filename,
            content_length=download.content_length,
            sha256=download.sha256,
        )
        self.server.write_header(self.wfile, header)
        chunks = download.iter_chunks()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
        finally:
            chunks.close()


class HwpxDownloadServer(_ThreadingUnixServer):
    """Closed-protocol server; only the fixed Application API UID may connect."""

    def __init__(
        self,
        service: HwpxApplicationService,
        *,
        socket_path: Path = MANAGER_SOCKET,
        allowed_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.service = service
        self.socket_path = socket_path
        self.allowed_uid = pwd.getpwnam("eom-api").pw_uid if allowed_uid is None else allowed_uid
        self.expected_gid = grp.getgrnam("eom-api").gr_gid if expected_gid is None else expected_gid
        self._validate_runtime_directory()
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("HWPX manager socket path is not fresh")
        super().__init__(str(socket_path), _DownloadHandler)
        socket_path.chmod(SOCKET_MODE)
        metadata = socket_path.lstat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != SOCKET_MODE
        ):
            self.server_close()
            raise RuntimeError("HWPX manager socket metadata mismatch")

    def _validate_runtime_directory(self) -> None:
        parent = self.socket_path.parent
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or parent.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIRECTORY_MODE
        ):
            raise RuntimeError("HWPX manager runtime directory contract mismatch")

    def peer_is_allowed(self, connection: socket.socket) -> bool:
        try:
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            if not isinstance(raw, bytes):
                return False
            _pid, uid, _gid = cast(tuple[int, int, int], struct.unpack("3i", raw))
        except (OSError, struct.error):
            return False
        return uid == self.allowed_uid

    def handle_error(self, _request: object, _client_address: object) -> None:
        # A disconnected local client must not emit paths, payloads, or a traceback to the journal.
        return

    @staticmethod
    def write_header(stream: Any, value: HwpxManagerDownloadResponse) -> None:
        payload = value.model_dump(mode="json", exclude_none=True)
        validate_contract("manager-download", payload, definition="response")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        if len(encoded) + 1 > MAX_HEADER_BYTES:
            raise RuntimeError("HWPX manager response header exceeded its fixed bound")
        stream.write(encoded + b"\n")

    @classmethod
    def write_error(cls, stream: Any, error_code: str) -> None:
        cls.write_header(
            stream,
            HwpxManagerDownloadResponse(status="ERROR", error_code=error_code),
        )

    def server_close(self) -> None:
        super().server_close()
        try:
            metadata = self.socket_path.lstat()
        except OSError:
            return
        if (
            stat.S_ISSOCK(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and metadata.st_gid == self.expected_gid
        ):
            self.socket_path.unlink()
