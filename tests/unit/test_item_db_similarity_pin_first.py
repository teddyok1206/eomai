"""Bounded backport of main61737b84 tests; no model, DB mutation or operator impersonation."""

import pytest
from eom_api.errors import ApiError
from eom_api_contracts.item_db_similarity import ItemDbSimilarityInput

from tests.unit.test_item_db_similarity_application import flow as flow


def test_initial_preparing_pin_is_delivered_before_native_work(flow):
    body = ItemDbSimilarityInput(selection=flow.value.selection)
    one = flow.app.search(flow.context, body, idempotency_key=flow.value.key)
    assert (one.status, one.phase) == ("PENDING", "PREPARING")
    assert one.pinned_query == flow.value.query
    flow.queries.prepare.assert_not_called()
    replay = ItemDbSimilarityInput(selection=body.selection, pinned_query=one.pinned_query)
    assert flow.app.search(flow.context, replay, idempotency_key=flow.value.key).status == "READY"
    flow.queries.prepare.assert_called_once_with(
        flow.context, flow.value.query, idempotency_key=flow.value.key
    )


def test_lost_first_response_does_not_orphan_a_native_search(flow):
    body = ItemDbSimilarityInput(selection=flow.value.selection)
    one = flow.app.search(flow.context, body, idempotency_key=flow.value.key)
    assert flow.app.search(flow.context, body, idempotency_key=flow.value.key) == one
    flow.queries.prepare.assert_not_called()


def test_timeout_after_pinning_replays_original_scope_and_key(flow):
    flow.queries.prepare.side_effect = ApiError(
        503, "REFERENCE_QUERY_PREPARE_UNAVAILABLE", "Unavailable", "Synthetic timeout"
    )
    with pytest.raises(ApiError):
        flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key)
    flow.queries.prepare.side_effect = None
    assert (
        flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key).status == "READY"
    )
    assert all(
        call.args[1] == flow.value.query and call.kwargs["idempotency_key"] == flow.value.key
        for call in flow.queries.prepare.call_args_list
    )
