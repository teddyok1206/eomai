"""Real use cases and monotonic rules; synthetic authentication and service ports."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services.item_db_similarity_searches import ItemDbSimilaritySearchApplication
from eom_api.services.item_db_similarity_state import (
    ItemDbSimilaritySearchSnapshot,
    merge_item_db_search_children,
)
from eom_api.services.pagination import PageResult
from eom_api_contracts.item_db_similarity import ItemDbSimilarityListInput
from eom_catalog_contracts.item_db_similarity_selection_v2 import ItemDbSimilaritySelectionReplyV2
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    ReferenceQueryPrepareRequestV4,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey

from tests.unit.test_item_db_similarity_application import flow as flow
from tests.unit.test_item_db_similarity_application import query_reply


@pytest.fixture
def search_case(flow):
    body = ItemDbSimilarityListInput(selections=(flow.value.selection,))
    record = ItemDbSimilaritySearchSnapshot(
        search_id="dbsearch_" + "1" * 32,
        operator_id=flow.authentication.operator.operator_id,
        idempotency_key=flow.value.key,
        intent_sha256=content_sha256(body),
        input=body,
        query=flow.value.query,
        children=query_reply(flow.value, ready=True).children,
        state="READY",
        device="CUDA",
        error_code=None,
        created_at=datetime.now(UTC),
    )
    store = Mock()
    store.get.return_value = store.admit.return_value = record
    app = ItemDbSimilaritySearchApplication(
        store, flow.selector, flow.queries, flow.results, flow.metadata
    )
    return NS(**locals())


def test_completed_result_reread_has_no_execution_dependency(search_case):
    case = search_case
    first = case.app.read_result(case.flow.context, case.record.search_id, 0)
    second = case.app.read_result(case.flow.context, case.record.search_id, 0)
    assert first == second and first.candidates
    assert first.search_id == case.record.search_id
    case.flow.queries.prepare.assert_not_called()
    case.flow.selector.resolve.assert_not_called()
    case.store.observe.assert_not_called()
    assert case.flow.results.read_public.call_count == 2
    assert all(
        call.args == (case.flow.authentication, case.record.children[0].selection)
        for call in case.flow.results.read_public.call_args_list
    )


def test_completed_check_and_submit_replay_never_offer_query(search_case):
    case = search_case
    assert case.app.check(case.flow.context, case.record.search_id).status == "READY"
    assert (
        case.app.submit(
            case.flow.context, case.body, idempotency_key=case.record.idempotency_key
        ).status
        == "READY"
    )
    case.flow.queries.prepare.assert_not_called()
    case.store.observe.assert_not_called()


def test_pending_result_read_cannot_accidentally_start_search(search_case):
    case = search_case
    case.store.get.return_value = replace(case.record, children=(), state="PENDING")
    with pytest.raises(ApiError) as raised:
        case.app.read_result(case.flow.context, case.record.search_id, 0)
    assert raised.value.error_code == "ITEM_DB_SIMILARITY_RESULT_PENDING"
    case.flow.queries.prepare.assert_not_called()
    case.flow.results.read_public.assert_not_called()


@pytest.mark.parametrize("ordinal", (-1, 1, 32))
def test_unknown_input_ordinal_does_not_read_another_source(search_case, ordinal):
    case = search_case
    with pytest.raises(ApiError) as raised:
        case.app.read_result(case.flow.context, case.record.search_id, ordinal)
    assert raised.value.status == 404
    case.flow.results.read_public.assert_not_called()


def test_recent_records_are_scoped_to_actual_operator(search_case):
    case = search_case
    case.store.list_recent.return_value = PageResult((case.record,), None, False)
    page = case.app.recent(case.flow.context, limit=20, cursor=None)
    assert page.data == (case.record.view(),)
    case.store.list_recent.assert_called_once_with(case.record.operator_id, limit=20, cursor=None)
    case.flow.queries.prepare.assert_not_called()
    case.flow.results.read_public.assert_not_called()


def test_read_requires_current_permissions_before_history_or_result(search_case):
    case = search_case
    auth = replace(
        case.flow.authentication,
        permissions=frozenset(
            permission
            for permission in case.flow.authentication.permissions
            if permission != PermissionKey.CONTENT_INTAKE_READ
        ),
    )
    context = replace(case.flow.context, authentication=auth)
    with pytest.raises(ApiError) as raised:
        case.app.read_result(context, case.record.search_id, 0)
    assert raised.value.status == 403
    case.store.get.assert_not_called()


def test_late_pending_observation_cannot_erase_completed_selector(search_case):
    case = search_case
    old = case.record.children[0]
    pending = old.model_copy(update={"state": "PENDING", "selection": None})
    assert merge_item_db_search_children((old,), (pending,), case.record.query) == (old,)


@pytest.mark.parametrize("change", ("workflow", "source", "completion"))
def test_completed_child_cannot_be_rebound_to_another_result(search_case, change):
    case = search_case
    old = case.record.children[0]
    changed = old.model_copy(
        update={"workflow_id": "workflow_" + "f" * 32}
        if change == "workflow"
        else {"source_item_revision_id": "itemrev_" + "f" * 32}
        if change == "source"
        else {"state": "FAILED", "selection": None}
    )
    with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
        merge_item_db_search_children((old,), (changed,), case.record.query)


def test_failed_child_is_not_reinterpreted_as_success(search_case):
    case = search_case
    completed = case.record.children[0]
    failed = completed.model_copy(update={"state": "FAILED", "selection": None})
    with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
        merge_item_db_search_children((failed,), (completed,), case.record.query)


def test_two_source_check_offers_one_existing_batch_and_defers_heavy_result_reads(search_case):
    case = search_case
    second = case.body.selections[0].model_copy(update={"item_revision_id": "itemrev_" + "f" * 32})
    body = ItemDbSimilarityListInput(selections=(*case.body.selections, second), top_k=10)
    raw = case.record.query.model_dump(mode="json", exclude={"request_sha256"})
    raw.update(
        source_item_revision_ids=[value.item_revision_id for value in body.selections], top_k=10
    )
    query = ReferenceQueryPrepareRequestV4.model_validate(
        raw | {"request_sha256": content_sha256(raw)}
    )
    pending = replace(case.record, input=body, query=query, children=(), state="PENDING")
    case.store.get.return_value = pending
    reply = query_reply(case.flow.value, ready=True).model_dump(mode="json")
    reply.update(request_sha256=query.request_sha256, workflow_id=None, selection=None)
    child = reply["children"][0]
    reply["children"] = [
        child,
        dict(
            child,
            ordinal=1,
            source_item_revision_id=second.item_revision_id,
            workflow_id="workflow_" + "e" * 32,
            selection=dict(child["selection"], workflow_id="workflow_" + "e" * 32),
        ),
    ]
    result = ReferenceQueryPrepareReplyV4.model_validate(reply)
    case.flow.queries.prepare.return_value = result
    case.store.observe.return_value = replace(pending, children=result.children, state="READY")
    assert case.app.check(case.flow.context, case.record.search_id).status == "READY"
    case.flow.queries.prepare.assert_called_once_with(
        case.flow.context, query, idempotency_key=case.record.idempotency_key
    )
    case.flow.results.read_public.assert_not_called()
    case.flow.metadata.selected_production_item_candidates.assert_not_called()


def test_unprepared_list_is_visible_as_unavailable_and_never_starts_native_work(search_case):
    case = search_case
    pending = replace(case.record, query=None, children=(), state="PREPARING")
    unavailable = replace(pending, state="UNAVAILABLE", error_code="ITEM_DB_SIMILARITY_NOT_INDEXED")
    case.store.admit.return_value = case.store.get.return_value = pending
    case.store.capture_unavailable.return_value = unavailable

    def resolve(request):
        return ItemDbSimilaritySelectionReplyV2(
            schema_version="item-db-similarity-selection-reply/2.0",
            operation="RESOLVE_ITEM_DB_SIMILARITY_LIST",
            status="UNAVAILABLE",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request),
            result=None,
            error_code="ITEM_DB_SIMILARITY_NOT_INDEXED",
        )

    case.flow.selector.resolve_many = Mock(side_effect=resolve)
    assert (
        case.app.submit(
            case.flow.context, case.body, idempotency_key=case.record.idempotency_key
        ).status
        == "UNAVAILABLE"
    )
    assert case.app.check(case.flow.context, case.record.search_id).status == "UNAVAILABLE"
    case.flow.queries.prepare.assert_not_called()
    case.flow.results.read_public.assert_not_called()
