"""Private, bounded materialization adapter for untrusted PDF request bodies."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from eom_api.errors import ApiError

_PDF_PREFIX_LENGTH = 8
_PDF_SIGNATURE = re.compile(rb"^%PDF-[12]\.[0-9]$")
_HWP_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_HWPX_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
DocumentSourceFormat = Literal["PDF", "HWP", "HWPX"]
DocumentSourceMediaType = Literal[
    "application/pdf",
    "application/vnd.hancom.hwp",
    "application/vnd.hancom.hwpx",
]


@dataclass(frozen=True)
class StagedPdfUpload:
    path: Path
    content_length: int
    sha256: str
    source_format: DocumentSourceFormat = "PDF"
    media_type: DocumentSourceMediaType = "application/pdf"


class PdfUploadStager:
    """Write exactly one request body into an API-private single-link file."""

    def __init__(self, root: Path, *, maximum_bytes: int) -> None:
        self.root = root
        self.maximum_bytes = maximum_bytes

    @asynccontextmanager
    async def stage(
        self,
        request: Request,
        *,
        declared_length: int,
        source_format: DocumentSourceFormat = "PDF",
        media_type: DocumentSourceMediaType = "application/pdf",
    ) -> AsyncIterator[StagedPdfUpload]:
        expected_media_type, suffix = {
            "PDF": ("application/pdf", ".pdf"),
            "HWP": ("application/vnd.hancom.hwp", ".hwp"),
            "HWPX": ("application/vnd.hancom.hwpx", ".hwpx"),
        }[source_format]
        if media_type != expected_media_type:
            raise ApiError(
                422,
                "DOCUMENT_REVIEW_UPLOAD_MEDIA_TYPE_MISMATCH",
                "Document upload media type differs",
                "The upload media type must match its immutable source format.",
            )
        if not 8 <= declared_length <= self.maximum_bytes:
            raise ApiError(
                413,
                "API_BODY_TOO_LARGE",
                "PDF upload is outside its bounded size",
                "The PDF byte count must match the declared upload intent.",
            )
        root_descriptor = self._open_root()
        file_descriptor = -1
        name = f"upload-{secrets.token_hex(16)}{suffix}"
        staged_path = self.root / name
        identity: tuple[int, ...] | None = None
        try:
            file_descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
            identity = self._cleanup_identity(os.fstat(file_descriptor))
            digest = hashlib.sha256()
            prefix = bytearray()
            received = 0
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                if received > declared_length or received > self.maximum_bytes:
                    raise ApiError(
                        413,
                        "API_BODY_TOO_LARGE",
                        "PDF upload exceeds its declared size",
                        "The request body contains more bytes than the upload intent permits.",
                    )
                if len(prefix) < _PDF_PREFIX_LENGTH:
                    prefix.extend(chunk[: _PDF_PREFIX_LENGTH - len(prefix)])
                digest.update(chunk)
                await run_in_threadpool(self._write_all, file_descriptor, chunk)
            if received != declared_length:
                raise ApiError(
                    422,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_LENGTH_MISMATCH",
                    "PDF upload length differs",
                    "The uploaded PDF does not match the byte count declared by its intent.",
                )
            if not self._valid_signature(source_format, bytes(prefix)):
                error_code = (
                    "PDF_DOCUMENT_REVIEW_SIGNATURE_INVALID"
                    if source_format == "PDF"
                    else "DOCUMENT_REVIEW_SOURCE_SIGNATURE_INVALID"
                )
                raise ApiError(
                    422,
                    error_code,
                    "Document signature is invalid",
                    "The uploaded bytes do not match the declared document format.",
                )
            await run_in_threadpool(os.fsync, file_descriptor)
            metadata = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or metadata.st_size != received
            ):
                raise ApiError(
                    500,
                    "PDF_DOCUMENT_REVIEW_STAGING_INVALID",
                    "PDF upload staging failed",
                    "The upload could not be materialized with the required file identity.",
                )
            os.close(file_descriptor)
            file_descriptor = -1
            yield StagedPdfUpload(
                path=staged_path,
                content_length=received,
                sha256="sha256:" + digest.hexdigest(),
                source_format=source_format,
                media_type=media_type,
            )
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            try:
                metadata = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
                if identity is not None and self._cleanup_identity(metadata) == identity:
                    os.unlink(name, dir_fd=root_descriptor)
            except FileNotFoundError:
                pass
            finally:
                os.close(root_descriptor)

    def _open_root(self) -> int:
        try:
            descriptor = os.open(
                self.root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise ApiError(
                503,
                "PDF_DOCUMENT_REVIEW_STAGING_UNAVAILABLE",
                "PDF upload staging is unavailable",
                "The private PDF upload area is not ready.",
            ) from exc
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            os.close(descriptor)
            raise ApiError(
                503,
                "PDF_DOCUMENT_REVIEW_STAGING_UNAVAILABLE",
                "PDF upload staging is unavailable",
                "The private PDF upload area has an unsafe identity.",
            )
        return descriptor

    @staticmethod
    def _valid_signature(source_format: DocumentSourceFormat, prefix: bytes) -> bool:
        if source_format == "PDF":
            return _PDF_SIGNATURE.fullmatch(prefix) is not None
        if source_format == "HWP":
            return prefix == _HWP_SIGNATURE
        return prefix.startswith(_HWPX_SIGNATURES)

    @staticmethod
    def _write_all(descriptor: int, chunk: bytes) -> None:
        remaining = memoryview(chunk)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise OSError("PDF staging write made no progress")
            remaining = remaining[written:]

    @staticmethod
    def _cleanup_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_nlink,
        )
