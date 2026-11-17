"""Public/Web projection alignment and exact-source/binary response rejection."""

import hashlib

import httpx
import pytest
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_concept_contracts import ConceptCreate

from tests.unit.test_kakao_concept_rpc import cases
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(gateway, req):
    if req.operation == "START_KAKAO_CONCEPT":
        return await gateway.kakao_concept_start(
            _session(),
            ConceptCreate.model_validate(req.command.model_dump(mode="json")),
            req.idempotency_key,
        )
    if req.operation == "READ_KAKAO_CONCEPT":
        return await gateway.kakao_concept_read(_session(), req.source_binding_id, req.task_id)
    return await gateway.kakao_concept_list(_session(), req.source_binding_id)


@pytest.mark.anyio
@pytest.mark.parametrize("req,result", cases())
async def test_exact_public_projection_and_read_never_post(req, result):
    requests = []

    def response(req):
        requests.append(req)
        return httpx.Response(200, json=_single(result.model_dump(mode="json")))

    gateway = http_gateway(response)
    try:
        assert (await call(gateway, req)).model_dump(mode="json") == result.model_dump(mode="json")
        assert len(requests) == 1
        assert requests[0].method == ("POST" if req.operation == "START_KAKAO_CONCEPT" else "GET")
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("req,result", cases())
async def test_unrelated_binding_rejected(req, result):
    raw = result.model_dump(mode="json")
    (raw["items"][0] if "items" in raw else raw["task"])["source_binding_id"] = (
        "kakaobinding_" + "f" * 32
    )
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(raw)))
    try:
        with pytest.raises(GatewayError):
            await call(gateway, req)
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_exact_png_download_hash(corrupt):
    raw = b"\x89PNG\r\n\x1a\nsynthetic-binary-transport-only"
    sha = "sha256:" + hashlib.sha256(raw).hexdigest()
    gateway = http_gateway(
        lambda _: httpx.Response(
            200,
            content=raw + (b"x" if corrupt else b""),
            headers={
                "Content-Type": "image/png",
                "Content-Disposition": "inline",
                "ETag": '"' + sha + '"',
            },
        )
    )
    task = cases()[1][1].task
    try:
        if corrupt:
            with pytest.raises(GatewayError):
                await gateway.kakao_concept_page(
                    _session(), task.source_binding_id, task.task_id, "E1P1"
                )
        else:
            assert (
                await gateway.kakao_concept_page(
                    _session(), task.source_binding_id, task.task_id, "E1P1"
                )
            ).content == raw
    finally:
        await gateway.close()
