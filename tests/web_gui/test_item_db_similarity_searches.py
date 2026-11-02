"""Independent Web transport: owned history and completed GET reads, no numerical starts."""

from unittest.mock import AsyncMock

import httpx
import pytest
from eom_web_gui.gateways import GatewayError
from eom_web_gui.item_db_similarity_contracts import (
    ItemDbSearchAnchorResult,
    ItemDbSearchHistory,
    ItemDbSearchView,
    ItemDbSimilarityListSubmission,
)

from tests.unit.test_item_db_similarity_application import flow as flow
from tests.unit.test_item_db_similarity_searches import search_case as search_case
from tests.web_gui.helpers import login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_item_db_similarity import gateway_for

BASE = "/studio/api/v1/item-db/similarity/searches"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_recent_history_requires_session_and_returns_no_query_execution(search_case):
    client, gateway = make_client()
    view = ItemDbSearchView.model_validate(search_case.record.view().model_dump(mode="json"))
    gateway.item_db_similarity_list_recent = AsyncMock(
        return_value=ItemDbSearchHistory(values=(view,), next_cursor=None)
    )
    with client:
        assert client.get(BASE).status_code == 401
        login(client)
        response = client.get(BASE)
    assert response.status_code == 200
    assert response.json()["values"][0]["search_id"] == search_case.record.search_id
    gateway.item_db_similarity_list_recent.assert_awaited_once()


def test_submit_and_check_use_csrf_and_only_submit_has_idempotency_key(search_case):
    client, gateway = make_client()
    view = ItemDbSearchView.model_validate(search_case.record.view().model_dump(mode="json"))
    gateway.item_db_similarity_list_submit = AsyncMock(return_value=view)
    gateway.item_db_similarity_list_check = AsyncMock(return_value=view)
    raw = search_case.body.model_dump(mode="json")
    with client:
        session = login(client)
        assert client.post(BASE, json=raw).status_code == 403
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": search_case.record.idempotency_key,
        }
        assert (
            client.post(BASE, json=raw | {"actor_id": "not-authority"}, headers=headers).status_code
            == 422
        )
        assert client.post(BASE, json=raw, headers=headers).status_code == 200
        path = BASE + f"/{view.search_id}/check"
        assert client.post(path).status_code == 403
        assert client.post(path, headers={"X-CSRF-Token": session["csrf_token"]}).status_code == 200
    gateway.item_db_similarity_list_submit.assert_awaited_once()
    gateway.item_db_similarity_list_check.assert_awaited_once()


@pytest.mark.anyio
async def test_completed_gateway_reads_are_get_and_same_selector(search_case):
    case = search_case
    result = ItemDbSearchAnchorResult.model_validate(
        case.app.read_result(case.flow.context, case.record.search_id, 0).model_dump(mode="json")
    )
    calls = []

    def response(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=_single(result.model_dump(mode="json")))

    gateway = gateway_for(response)
    try:
        assert (
            await gateway.item_db_similarity_list_result(_session(), case.record.search_id, 0)
            == result
        )
        assert (
            await gateway.item_db_similarity_list_result(_session(), case.record.search_id, 0)
            == result
        )
    finally:
        await gateway.close()
    assert (
        calls
        == [("GET", f"/api/v1/item-db/similarity/searches/{case.record.search_id}/results/0")] * 2
    )


@pytest.mark.anyio
async def test_gateway_rejects_a_result_for_a_different_search(search_case):
    case = search_case
    raw = case.app.read_result(case.flow.context, case.record.search_id, 0).model_dump(mode="json")
    raw["search_id"] = "dbsearch_" + "f" * 32
    gateway = gateway_for(lambda _request: httpx.Response(200, json=_single(raw)))
    try:
        with pytest.raises(GatewayError) as raised:
            await gateway.item_db_similarity_list_result(_session(), case.record.search_id, 0)
    finally:
        await gateway.close()
    assert raised.value.code == "ITEM_DB_SIMILARITY_RESPONSE_INVALID"


def test_web_accepts_one_or_many_sources_but_not_unbounded_or_empty_lists(search_case):
    raw = search_case.body.model_dump(mode="json")
    assert ItemDbSimilarityListSubmission.model_validate(raw).top_k == 5
    for changes in (
        {"selections": []},
        {"selections": raw["selections"] * 33},
        {"top_k": 0},
        {"top_k": True},
    ):
        with pytest.raises(ValueError):
            ItemDbSimilarityListSubmission.model_validate(raw | changes)
