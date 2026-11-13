"""Synthetic streaming, integrity and response-lifetime tests; no live files or HTTP."""

from __future__ import annotations

import asyncio
import hashlib
import tracemalloc

import anyio
import httpx
import pytest
from eom_web_gui import downloads
from eom_web_gui.downloads import VerifiedDownloadBody, download_response
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from starlette.requests import ClientDisconnect

from tests.web_gui.test_gateway import _session


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Body(httpx.AsyncByteStream):
    def __init__(self, size, *, fail=False):
        self.size = size
        self.fail = fail
        self.sent = 0
        self.closed = False

    async def __aiter__(self):
        remaining = self.size
        while remaining:
            size = min(remaining, 65536)
            chunk = b"PK\x03\x04" + b"x" * (size - 4) if self.sent == 0 else b"x" * size
            self.sent += size
            remaining -= size
            yield chunk
            if self.fail:
                raise httpx.ReadError("synthetic interrupted download")

    async def aclose(self):
        self.closed = True


def digest(size):
    value = hashlib.sha256()
    remaining = size
    first = True
    while remaining:
        count = min(remaining, 65536)
        value.update(b"PK\x03\x04" + b"x" * (count - 4) if first else b"x" * count)
        first = False
        remaining -= count
    return "sha256:" + value.hexdigest()


def gateway_for(size, *, headers=None, fail=False):
    streams = []

    def handle(request):
        assert request.headers["accept-encoding"] == "identity"
        stream = Body(size, fail=fail)
        streams.append(stream)
        return httpx.Response(
            200,
            stream=stream,
            headers={
                "Content-Type": "application/vnd.hancom.hwpx",
                "Content-Disposition": 'attachment; filename="test.hwpx"',
                "Content-Length": str(size),
                "ETag": digest(size),
                **(headers or {}),
            },
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://synthetic-api",
        observability_url="http://synthetic-observe",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handle),
    )
    return gateway, streams


async def get(gateway):
    return await gateway.download_curated_hwpx(
        _session(), "assembly_" + "a" * 32, "hwpxbuild_" + "b" * 32
    )


async def deliver(body, *, fail=None):
    response = download_response(body, media_type="application/vnd.hancom.hwpx", headers={})
    total = 0

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        nonlocal total
        if fail is not None:
            raise fail
        if message["type"] == "http.response.body":
            total += len(message.get("body", b""))

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    return total


@pytest.mark.anyio
async def test_large_download_is_spooled_verified_and_closed_after_delivery():
    gateway, streams = gateway_for(3 * 1024**2)
    try:
        value = await get(gateway)
        assert isinstance(value.content, VerifiedDownloadBody)
        assert not value.content.closed and streams[0].closed
        assert await deliver(value.content) == 3 * 1024**2
        assert value.content.closed
        # The permit belongs to the response; closing twice cannot over-release.
        value.content.close()
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_small_download_preserves_bytes_and_releases_capacity():
    gateway, streams = gateway_for(4096)
    try:
        value = await get(gateway)
        assert isinstance(value.content, bytes) and value.content.startswith(b"PK\x03\x04")
        assert streams[0].closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        {"ETag": "sha256:" + "0" * 64},
        {"ETag": "bad"},
        {"Content-Length": "12"},
        {"Content-Length": "9" * 100},
        {"Content-Length": str(257 * 1024**2)},
        {"Content-Type": "text/html"},
        {"Content-Encoding": "gzip"},
    ],
)
async def test_invalid_metadata_or_bytes_close_stream_and_return_capacity(headers):
    gateway, streams = gateway_for(2 * 1024**2, headers=headers)
    try:
        with pytest.raises(GatewayError, match="HWPX_DOWNLOAD_RESPONSE_INVALID"):
            await get(gateway)
        assert streams[0].closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_upstream_interruption_closes_spool_and_preserves_retryable_error():
    gateway, streams = gateway_for(3 * 1024**2, fail=True)
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_UNAVAILABLE"):
            await get(gateway)
        assert streams[0].closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [OSError("synthetic disconnect"), asyncio.CancelledError()])
async def test_downstream_disconnect_or_cancellation_closes_response_spool(failure):
    gateway, _ = gateway_for(2 * 1024**2)
    try:
        value = await get(gateway)
        assert isinstance(value.content, VerifiedDownloadBody)
        with pytest.raises((ClientDisconnect, asyncio.CancelledError)):
            await deliver(value.content, fail=failure)
        assert value.content.closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_anyio_cancelled_scope_still_finishes_upstream_cleanup():
    closed = False

    class ClosingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"synthetic"

        async def aclose(self):
            nonlocal closed
            await anyio.sleep(0)
            closed = True

    gateway = HttpApplicationGateway(
        application_api_url="http://synthetic-api",
        observability_url="http://synthetic-observe",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=ClosingBody())),
    )
    try:
        with anyio.CancelScope() as scope:
            async with gateway._download(_session(), "/synthetic"):
                scope.cancel()
                await anyio.sleep(0)
        assert closed
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_concurrent_large_spools_hold_capacity_until_client_finishes(monkeypatch):
    monkeypatch.setattr(downloads, "DOWNLOAD_ADMISSION_SECONDS", 0.01)
    gateway, streams = gateway_for(2 * 1024**2)
    held = []
    try:
        held = list(await asyncio.gather(get(gateway), get(gateway)))
        assert all(isinstance(item.content, VerifiedDownloadBody) for item in held)
        with pytest.raises(GatewayError, match="DOWNLOAD_CAPACITY_BUSY"):
            await get(gateway)
        assert all(stream.closed for stream in streams)
        await deliver(held[0].content)
        third = await get(gateway)
        held.append(third)
    finally:
        for item in held:
            if isinstance(item.content, VerifiedDownloadBody):
                item.content.close()
        await gateway.close()


@pytest.mark.anyio
async def test_two_large_downloads_have_size_independent_python_memory():
    gateway, _ = gateway_for(16 * 1024**2)
    held = []
    tracemalloc.start()
    try:
        held = list(await asyncio.gather(get(gateway), get(gateway)))
        _, peak = tracemalloc.get_traced_memory()
        # Two 16MiB files must not become two in-memory response payloads.
        assert peak < 12 * 1024**2, peak
        assert await deliver(held[0].content) == 16 * 1024**2
        assert await deliver(held[1].content) == 16 * 1024**2
    finally:
        tracemalloc.stop()
        for item in held:
            if isinstance(item.content, VerifiedDownloadBody):
                item.content.close()
        await gateway.close()
