"""Session/CSRF BFF and API-only pinned-query echo; no live credentials or model."""

from unittest.mock import AsyncMock

import httpx
import pytest
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.item_db_similarity_contracts import (
    ItemDbSimilarityResult,
    ItemDbSimilaritySubmission,
)

from tests.unit.test_item_db_similarity_selection import selected_case
from tests.web_gui.helpers import login, make_client
from tests.web_gui.test_gateway import _session, _single

PATH = "/studio/api/v1/item-db/similarity"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def gateway_for(handler):
    return HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
        observability_transport=httpx.MockTransport(handler),
    )


def case():
    selected = selected_case()
    submission = ItemDbSimilaritySubmission(
        selection=selected.selection.model_dump(mode="json"),
        pinned_query=selected.query.model_dump(mode="json"),
    )
    result = ItemDbSimilarityResult(
        schema_version="item-db-similarity-view/1.0",
        status="PENDING",
        phase="WAITING_FOR_RESOURCE",
        candidates=(),
        pinned_query=selected.query.model_dump(mode="json"),
        search_snapshot_sha256=selected.result.search_snapshot_sha256,
        message="계산 순서를 기다리고 있습니다.",
        error_code=None,
    )
    return selected, submission, result


def test_bff_requires_session_csrf_key_and_forwards_one_exact_original_query():
    selected, submission, result = case()
    client, gateway = make_client()
    gateway.item_db_similarity_search = AsyncMock(return_value=result)
    with client:
        assert client.post(PATH, json=submission.model_dump(mode="json")).status_code == 401
        session = login(client)
        assert client.post(PATH, json=submission.model_dump(mode="json")).status_code == 403
        headers = {"X-CSRF-Token": session["csrf_token"]}
        assert (
            client.post(PATH, json=submission.model_dump(mode="json"), headers=headers).status_code
            == 422
        )
        headers["Idempotency-Key"] = selected.key
        response = client.post(PATH, json=submission.model_dump(mode="json"), headers=headers)
    assert response.status_code == 200
    assert response.json() == result.model_dump(mode="json")
    gateway.item_db_similarity_search.assert_awaited_once()
    assert gateway.item_db_similarity_search.call_args.args[1:] == (submission, selected.key)


@pytest.mark.anyio
async def test_gateway_forwards_fixed_api_path_capture_token_and_same_query_key():
    selected, submission, result = case()
    calls = []

    def respond(request):
        import json

        calls.append(request)
        assert request.url.path == "/api/v1/item-db/similarity"
        assert request.headers["Idempotency-Key"] == selected.key
        assert json.loads(request.content) == submission.model_dump(mode="json")
        return httpx.Response(202, json=_single(result.model_dump(mode="json")))

    gateway = gateway_for(respond)
    try:
        assert (
            await gateway.item_db_similarity_search(_session(), submission, selected.key) == result
        )
    finally:
        await gateway.close()
    assert len(calls) == 1


@pytest.mark.anyio
async def test_gateway_rejects_a_different_search_pin_without_auto_replay():
    selected, submission, result = case()
    body = result.model_dump(mode="json")
    body["pinned_query"]["idempotency_key"] = "different-search-key"
    gateway = gateway_for(lambda _request: httpx.Response(200, json=_single(body)))
    try:
        with pytest.raises(GatewayError) as raised:
            await gateway.item_db_similarity_search(_session(), submission, selected.key)
    finally:
        await gateway.close()
    assert raised.value.code == "ITEM_DB_SIMILARITY_RESPONSE_INVALID"
