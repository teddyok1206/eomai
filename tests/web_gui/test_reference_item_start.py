"""Closed Web/API reply adapter and pending draft behavior, no live/model calls."""

from __future__ import annotations

import json

import httpx
import pytest
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.reference_item_contracts import ReferenceItemStartReply

from tests.api.test_reference_item_async_start import accepted, pending
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_request_default_resolution import _draft, _submit


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_api_reply_contract_is_consumable_without_api_runtime_dependency():
    for value in (pending(), accepted()):
        payload = value.model_dump(mode="json")
        assert ReferenceItemStartReply.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.anyio
@pytest.mark.parametrize("enabled,variation", [(False, True), (True, True), (True, False)])
async def test_only_explicitly_enabled_reference_requests_use_new_operation(enabled, variation):
    requests = []
    payload = (
        {"educational_retrieval": {"schema_version": "educational-retrieval-requirement/2.0"}}
        if variation
        else {}
    )

    def handler(request):
        requests.append(request)
        assert request.headers["idempotency-key"] == "same-reference-key"
        assert json.loads(request.content) == payload
        assert request.url.path == (
            "/api/v1/workflows/reference-starts" if enabled and variation else "/api/v1/workflows"
        )
        return httpx.Response(
            202,
            json=_single(
                pending().model_dump(mode="json")
                if enabled and variation
                else accepted().command.model_dump(mode="json")
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        reference_item_start_enabled=enabled,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await gateway.start_workflow(_session(), payload, "same-reference-key")
        assert result == (
            pending().model_dump(mode="json")
            if enabled and variation
            else accepted().command.model_dump(mode="json")
        )
        assert len(requests) == 1
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_enabled_reference_route_never_falls_back_after_invalid_reply():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(
            202,
            json=_single(
                pending().model_dump(mode="json")
                | {"command": accepted().command.model_dump(mode="json")}
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        reference_item_start_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.start_workflow(
                _session(),
                {
                    "educational_retrieval": {
                        "schema_version": "educational-retrieval-requirement/2.0"
                    }
                },
                "same-reference-key",
            )
        assert seen == ["/api/v1/workflows/reference-starts"]
    finally:
        await gateway.close()


def test_bff_never_replays_pending_as_accepted_and_retains_original_key():
    class PendingGateway(FakeGateway):
        def __init__(self):
            super().__init__()
            self.graph_grounding_available = True
            self.observed = []

        async def start_workflow(self, session, payload, idempotency_key):
            self.observed.append((payload, idempotency_key))
            if len(self.observed) < 3:
                return pending().model_dump(mode="json")
            return await super().start_workflow(session, payload, idempotency_key)

    gateway = PendingGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        headers = {"X-CSRF-Token": login(client)["csrf_token"]}
        draft = _draft(
            client, headers, "variation", "같은 핵심 착상을 활용하되 조건을 다르게 구성해주세요."
        )
        for _ in range(2):
            result = _submit(client, headers, draft)
            assert result["preparation_status"] == "PENDING" and result["command"] is None
        accepted_result = _submit(client, headers, draft)
        replay = _submit(client, headers, draft)
        assert accepted_result["command"] is not None and replay["replayed"] is True
        assert len(gateway.observed) == 3
        assert all(row == gateway.observed[0] for row in gateway.observed)
