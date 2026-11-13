"""Bounded verified HTTP materialization and response-owned temporary spool lifetime."""

from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
from collections.abc import AsyncIterator, Callable
from typing import BinaryIO, cast

import anyio
import httpx
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response, StreamingResponse
from starlette.types import Receive, Scope, Send

DOWNLOAD_CHUNK_BYTES = 64 * 1024
DOWNLOAD_MEMORY_BYTES = 1024 * 1024
DOWNLOAD_CONCURRENCY = 2
DOWNLOAD_ADMISSION_SECONDS = 5.0
ERROR_BODY_MAX_BYTES = 64 * 1024


class DownloadInvalid(ValueError):
    """Upstream bytes did not satisfy the declared download boundary."""


class DownloadCapacityBusy(RuntimeError):
    """Existing download spools own the bounded capacity; no new work was created."""


async def close_download_response(response: httpx.Response) -> None:
    """Finish socket cleanup under level cancellation; never launch an orphan close task."""
    if not response.is_closed:
        with anyio.fail_after(5.0, shield=True):
            await response.aclose()


class VerifiedDownloadBody:
    """A local, already-verified materialization; the HTTP response owns its close."""

    def __init__(self, stream: BinaryIO, size: int, release: Callable[[], None]) -> None:
        self._stream = stream
        self._size = size
        self._release = release
        self._closed = False

    def __len__(self) -> int:
        return self._size

    @property
    def closed(self) -> bool:
        return self._closed

    async def chunks(self) -> AsyncIterator[bytes]:
        while chunk := await run_in_threadpool(self._stream.read, DOWNLOAD_CHUNK_BYTES):
            yield chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.close()
        finally:
            self._release()


type DownloadContent = bytes | VerifiedDownloadBody


async def bounded_error_response(response: httpx.Response) -> httpx.Response:
    """Keep existing error decoding without letting an error body bypass the byte bound."""
    body = bytearray()
    try:
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise DownloadInvalid("encoded error body is not supported")
        async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
            if len(body) + len(chunk) > ERROR_BODY_MAX_BYTES:
                raise DownloadInvalid("upstream error body exceeds limit")
            body.extend(chunk)
        return httpx.Response(response.status_code, headers=response.headers, content=bytes(body))
    finally:
        await close_download_response(response)


async def read_verified_download(
    response: httpx.Response,
    *,
    slots: asyncio.BoundedSemaphore,
    maximum_bytes: int,
    minimum_bytes: int = 1,
    expected_length: int | None = None,
    expected_sha256: str | None = None,
    prefixes: tuple[bytes, ...] = (),
) -> DownloadContent:
    """Verify once, then hand one bounded materialization to its response owner."""
    declared = response.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal() or len(declared) > 12:
            raise DownloadInvalid("invalid content length")
        parsed = int(declared)
        if expected_length is not None and parsed != expected_length:
            raise DownloadInvalid("pinned content length differs")
        expected_length = parsed
    if expected_length is not None and not minimum_bytes <= expected_length <= maximum_bytes:
        raise DownloadInvalid("content length outside limit")
    if (
        expected_sha256 is not None
        and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256) is None
    ):
        raise DownloadInvalid("invalid expected hash")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise DownloadInvalid("encoded download is not the canonical byte stream")
    try:
        await asyncio.wait_for(slots.acquire(), DOWNLOAD_ADMISSION_SECONDS)
    except TimeoutError as error:
        raise DownloadCapacityBusy from error
    stream: BinaryIO | None = None
    handed_off = False
    try:
        # Ownership transfers to the ASGI response only after complete validation.
        stream = cast(BinaryIO, tempfile.SpooledTemporaryFile(max_size=DOWNLOAD_MEMORY_BYTES))  # noqa: SIM115
        digest = hashlib.sha256()
        prefix = bytearray()
        prefix_size = max((len(value) for value in prefixes), default=0)
        received = 0
        async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
            received += len(chunk)
            if received > maximum_bytes or (
                expected_length is not None and received > expected_length
            ):
                raise DownloadInvalid("download exceeds declared limit")
            if len(prefix) < prefix_size:
                prefix.extend(chunk[: prefix_size - len(prefix)])
            digest.update(chunk)
            await run_in_threadpool(stream.write, chunk)
        if (
            not minimum_bytes <= received <= maximum_bytes
            or (expected_length is not None and received != expected_length)
            or (prefixes and not any(prefix.startswith(value) for value in prefixes))
            or (expected_sha256 is not None and "sha256:" + digest.hexdigest() != expected_sha256)
        ):
            raise DownloadInvalid("download bytes differ")
        # Complete upstream cleanup while this function still owns the spool.
        # A cancellation during close must not lose a handed-off capacity permit.
        await close_download_response(response)
        await run_in_threadpool(stream.seek, 0)
        if received <= DOWNLOAD_MEMORY_BYTES:
            return stream.read()
        body = VerifiedDownloadBody(stream, received, slots.release)
        handed_off = True
        return body
    finally:
        if not handed_off:
            try:
                if stream is not None:
                    stream.close()
            finally:
                slots.release()


class _VerifiedDownloadResponse(StreamingResponse):
    def __init__(
        self, body: VerifiedDownloadBody, *, media_type: str, headers: dict[str, str]
    ) -> None:
        self._body = body
        super().__init__(body.chunks(), media_type=media_type, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._body.close()


def download_response(
    content: DownloadContent, *, media_type: str, headers: dict[str, str]
) -> Response:
    """Small fake/real replies stay bytes; large validated spools stream with cleanup."""
    bounded_headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        **headers,
        "Content-Length": str(len(content)),
    }
    if isinstance(content, bytes):
        return Response(content=content, media_type=media_type, headers=bounded_headers)
    try:
        return _VerifiedDownloadResponse(content, media_type=media_type, headers=bounded_headers)
    except BaseException:
        content.close()
        raise
