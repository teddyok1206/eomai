"""Independent download cancellation, byte-prefix and authentication edge cases."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from unittest.mock import Mock

import anyio
import httpx
import pytest
from eom_web_gui import downloads
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway

from tests.web_gui.test_gateway import _session, _single, _token_data


@pytest.fixture
def anyio_backend():
    return "asyncio"


class ChunkedBody(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...], *, stall: bool = False) -> None:
        self.parts = chunks
        self.closed = False
        self.stall = stall
        self.receiving = asyncio.Event()
        self.cancel_scope = None

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.parts[0]
        self.receiving.set()
        if self.cancel_scope is not None:
            self.cancel_scope.cancel()
            await anyio.sleep(0)
        if self.stall:
            await asyncio.Event().wait()
        for chunk in self.parts[1:]:
            yield chunk

    async def aclose(self) -> None:
        # A synchronous fake close would not expose an AnyIO level-cancellation leak.
        await anyio.sleep(0)
        self.closed = True


def gateway_for(handler):
    return HttpApplicationGateway(
        application_api_url="http://synthetic-api",
        observability_url="http://synthetic-observe",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )


def response_for(body: ChunkedBody, *, declared_length: int | None = None) -> httpx.Response:
    payload = b"".join(body.parts)
    return httpx.Response(
        200,
        stream=body,
        headers={
            "Content-Type": "application/vnd.hancom.hwpx",
            "Content-Disposition": 'attachment; filename="synthetic.hwpx"',
            "Content-Length": str(len(payload) if declared_length is None else declared_length),
            "ETag": "sha256:" + hashlib.sha256(payload).hexdigest(),
        },
    )


async def get(gateway, session=None):
    return await gateway.download_curated_hwpx(
        session or _session(), "assembly_" + "a" * 32, "hwpxbuild_" + "b" * 32
    )


@pytest.mark.anyio
async def test_task_cancel_during_receiving_closes_spool_upstream_and_permit(monkeypatch):
    body = ChunkedBody((b"PK\x03\x04" + b"x" * (65536 - 4), b"last"), stall=True)
    gateway = gateway_for(lambda _: response_for(body))
    original = downloads.tempfile.SpooledTemporaryFile
    opened = []

    def spool(**kwargs):
        value = original(**kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(downloads.tempfile, "SpooledTemporaryFile", spool)
    pending = asyncio.create_task(get(gateway))
    try:
        await asyncio.wait_for(body.receiving.wait(), 2)
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY - 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert opened and all(value.closed for value in opened)
        assert body.closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await gateway.close()


@pytest.mark.anyio
async def test_anyio_level_cancel_during_receiving_closes_resources(monkeypatch):
    body = ChunkedBody((b"PK\x03\x04" + b"x" * (65536 - 4), b"last"))
    gateway = gateway_for(lambda _: response_for(body))
    original = downloads.tempfile.SpooledTemporaryFile
    opened = []

    def spool(**kwargs):
        value = original(**kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(downloads.tempfile, "SpooledTemporaryFile", spool)
    try:
        with anyio.CancelScope() as scope:
            body.cancel_scope = scope
            await get(gateway)
        assert opened and all(value.closed for value in opened)
        assert body.closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_cancel_while_capacity_is_owned_does_not_release_another_downloads_permit():
    body = ChunkedBody((b"PK\x03\x04", b"synthetic"))
    seen = asyncio.Event()

    def handle(_):
        seen.set()
        return response_for(body)

    gateway = gateway_for(handle)
    for _ in range(downloads.DOWNLOAD_CONCURRENCY):
        await gateway._download_slots.acquire()
    pending = asyncio.create_task(get(gateway))
    try:
        await asyncio.wait_for(seen.wait(), 2)
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert body.closed
        assert gateway._download_slots._value == 0
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        for _ in range(downloads.DOWNLOAD_CONCURRENCY):
            gateway._download_slots.release()
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["split-prefix", "wrong-prefix", "truncated"])
async def test_prefix_and_truncated_bytes_are_verified_before_response_handoff(case):
    chunks = (b"P", b"K", b"\x03", b"\x04", b"synthetic-payload")
    if case == "wrong-prefix":
        chunks = (b"bad!", b"synthetic-payload")
    body = ChunkedBody(chunks)
    declared = len(b"".join(chunks)) + (case == "truncated")
    gateway = gateway_for(lambda _: response_for(body, declared_length=declared))
    try:
        if case == "split-prefix":
            assert (await get(gateway)).content == b"".join(chunks)
        else:
            with pytest.raises(GatewayError, match="HWPX_DOWNLOAD_RESPONSE_INVALID"):
                await get(gateway)
        assert body.closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("second_unauthorized", [False, True])
async def test_streamed_401_is_closed_before_single_refresh_and_read_replay(second_unauthorized):
    calls = []
    denied = []
    succeeded = ChunkedBody((b"PK\x03\x04", b"synthetic-payload"))

    def handle(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/api/v1/auth/refresh":
            assert denied and denied[0].closed
            return httpx.Response(200, json=_single(_token_data("eom_at_TEST_ONLY_ROTATED")))
        assert request.method == "GET" and request.headers["accept-encoding"] == "identity"
        if not denied or second_unauthorized:
            body = ChunkedBody((json.dumps({"error_code": "AUTH_ACCESS_TOKEN_EXPIRED"}).encode(),))
            denied.append(body)
            return httpx.Response(401, stream=body, headers={"Content-Type": "application/json"})
        assert request.headers["authorization"] == "Bearer eom_at_TEST_ONLY_ROTATED"
        return response_for(succeeded)

    gateway = gateway_for(handle)
    session = _session()
    try:
        if second_unauthorized:
            with pytest.raises(GatewayError, match="AUTH_ACCESS_TOKEN_EXPIRED"):
                await get(gateway, session)
        else:
            assert (await get(gateway, session)).content == b"".join(succeeded.parts)
            assert succeeded.closed
        assert all(body.closed for body in denied)
        assert [method for method, _, _ in calls] == ["GET", "POST", "GET"]
        assert session.tokens.access_token == "eom_at_TEST_ONLY_ROTATED"
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_error_body_cap_prevents_error_decoding_from_buffering_arbitrary_bytes():
    body = ChunkedBody((b"x" * (downloads.ERROR_BODY_MAX_BYTES + 1),))
    handle = Mock(return_value=httpx.Response(503, stream=body))
    gateway = gateway_for(handle)
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await get(gateway)
        assert handle.call_count == 1 and body.closed
        assert gateway._download_slots._value == downloads.DOWNLOAD_CONCURRENCY
    finally:
        await gateway.close()
