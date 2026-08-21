"""Application API adapter for the private HWPX manager streaming socket."""

from __future__ import annotations

import hashlib
import json
import socket
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import (
    HwpxManagerDownloadRequest,
    HwpxManagerDownloadResponse,
    validate_contract,
)
from eom_hwpx_manager.download_server import MANAGER_SOCKET, MAX_HEADER_BYTES
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

CONNECT_TIMEOUT_SECONDS = 5.0
STREAM_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ProxiedHwpxDownload:
    connection: socket.socket
    filename: str
    content_length: int
    sha256: str

    def iter_chunks(self) -> Iterator[bytes]:
        digest = hashlib.sha256()
        remaining = self.content_length
        try:
            while remaining:
                chunk = self.connection.recv(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("HWPX manager stream ended before its declared size")
                remaining -= len(chunk)
                digest.update(chunk)
                yield chunk
            if self.connection.recv(1):
                raise RuntimeError("HWPX manager stream exceeded its declared size")
            if "sha256:" + digest.hexdigest() != self.sha256:
                raise RuntimeError("HWPX manager stream failed end-to-end SHA-256 validation")
        finally:
            self.connection.close()


class HwpxDownloadClient:
    def __init__(self, socket_path: Path = MANAGER_SOCKET) -> None:
        self.socket_path = socket_path

    def download(self, build_id: str) -> ProxiedHwpxDownload:
        request = HwpxManagerDownloadRequest(build_id=build_id)
        payload = request.model_dump(mode="json")
        validate_contract("manager-download", payload, definition="request")
        try:
            metadata = self.socket_path.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX manager download boundary is unavailable",
            ) from exc
        if not stat.S_ISSOCK(metadata.st_mode) or self.socket_path.is_symlink():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX manager download boundary is invalid",
            )
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            raw = self._read_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("manager-download", value, definition="response")
            response = HwpxManagerDownloadResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_manager_error(response.error_code)
            assert response.filename is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            connection.settimeout(STREAM_TIMEOUT_SECONDS)
            return ProxiedHwpxDownload(
                connection=connection,
                filename=response.filename,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except HwpxManagerError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX manager download response is unavailable",
            ) from exc

    @staticmethod
    def _read_header(connection: socket.socket) -> bytes:
        value = bytearray()
        while len(value) <= MAX_HEADER_BYTES:
            chunk = connection.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                return bytes(value)
            value.extend(chunk)
        raise ValueError("HWPX manager header is absent or exceeds its fixed bound")

    @staticmethod
    def _raise_manager_error(error_code: str | None) -> None:
        try:
            code = HwpxManagerErrorCode(str(error_code))
        except ValueError:
            code = HwpxManagerErrorCode.HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE
        raise HwpxManagerError(code, "HWPX manager refused the download request")
