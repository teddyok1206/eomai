"""List protocol first: exact order, bounded cardinality, duplicate and replay fences."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts.item_db_similarity_selection import ItemDbGraphSelection
from eom_catalog_contracts.item_db_similarity_selection_v2 import (
    ItemDbSimilarityPreparedSelectionV2,
    ItemDbSimilaritySelectionReplyV2,
    ItemDbSimilaritySelectionRequestV2,
    validate_item_db_similarity_selection_reply_v2,
)
from eom_identifiers import content_sha256

from tests.unit.test_item_db_similarity_selection import ERRORS, selected_case


def list_case(count=2):
    value = selected_case()
    request = value.request.model_dump(mode="json", exclude={"selection"})
    selections = [
        value.selection.model_copy(
            update={"item_revision_id": "itemrev_" + f"{ordinal + 1:032x}"}
        ).model_dump(mode="json")
        for ordinal in range(count)
    ]
    request.update(
        schema_version="item-db-similarity-selection-request/2.0",
        operation="RESOLVE_ITEM_DB_SIMILARITY_LIST",
        selections=selections,
        pinned_query=None,
    )
    return value, request


@pytest.mark.parametrize("count", (1, 2, 32))
def test_list_has_one_shared_original_query(count):
    value, raw = list_case(count)
    request = ItemDbSimilaritySelectionRequestV2.model_validate(raw)
    query = value.query.model_dump(mode="json", exclude={"request_sha256"})
    query["source_item_revision_ids"] = [s.item_revision_id for s in request.selections]
    query["request_sha256"] = content_sha256(query)
    prepared = ItemDbSimilarityPreparedSelectionV2.model_validate(
        dict(
            selection_sha256=content_sha256(request.selections),
            anchors=[
                dict(
                    item_id=s.item_id,
                    item_revision_id=s.item_revision_id,
                    item_manifest_sha256=s.item_manifest_sha256,
                )
                for s in request.selections
            ],
            query=query,
            search_snapshot_sha256=value.result.search_snapshot_sha256,
        )
    )
    reply = ItemDbSimilaritySelectionReplyV2(
        schema_version="item-db-similarity-selection-reply/2.0",
        operation="RESOLVE_ITEM_DB_SIMILARITY_LIST",
        status="READY",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request),
        result=prepared,
        error_code=None,
    )
    validate_item_db_similarity_selection_reply_v2(request, reply)
    replay = ItemDbSimilaritySelectionRequestV2.model_validate(raw | {"pinned_query": query})
    validate_item_db_similarity_selection_reply_v2(
        replay, reply.model_copy(update={"request_sha256": content_sha256(replay)})
    )
    if count > 1:
        with pytest.raises(ERRORS):
            ItemDbSimilaritySelectionRequestV2.model_validate(
                raw | {"selections": list(reversed(raw["selections"])), "pinned_query": query}
            )


@pytest.mark.parametrize("count", (0, 33))
def test_list_cardinality_is_closed(count):
    _value, raw = list_case(count)
    with pytest.raises(ERRORS):
        ItemDbSimilaritySelectionRequestV2.model_validate(raw)


@pytest.mark.parametrize("top_k", (0, 65, True, "5"))
def test_top_k_is_strict_and_bounded(top_k):
    _value, raw = list_case()
    with pytest.raises(ERRORS):
        ItemDbSimilaritySelectionRequestV2.model_validate(raw | {"top_k": top_k})


def test_same_revision_with_different_pointer_metadata_is_still_duplicate():
    _value, raw = list_case(1)
    duplicate = dict(raw["selections"][0], graph_snapshot_sha256="sha256:" + "f" * 64)
    with pytest.raises(ERRORS):
        ItemDbSimilaritySelectionRequestV2.model_validate(
            raw | {"selections": [raw["selections"][0], duplicate]}
        )


def test_legacy_selection_contract_is_still_closed():
    value, _raw = list_case(1)
    assert isinstance(value.selection, ItemDbGraphSelection)
    assert value.request.schema_version == "item-db-similarity-selection-request/1.0"


def test_list_failure_observation_never_records_source_or_exception_prose(caplog, monkeypatch):
    from eom_catalog_service import inference_transfer_read_timing as timing
    from eom_catalog_service.item_db_similarity_selection import CatalogItemDbSimilaritySelection

    _value, raw = list_case(2)
    request = ItemDbSimilaritySelectionRequestV2.model_validate(raw)
    service = object.__new__(CatalogItemDbSimilaritySelection)
    service.sessions = NS(begin=MagicMock())
    service.owner = NS(identity=NS(fence_current_operator=Mock()))
    service._scope = Mock(side_effect=ValueError("synthetic-private-source-must-not-be-logged"))
    monkeypatch.setattr(timing._LOGGER, "propagate", True)
    with caplog.at_level("INFO"), pytest.raises(ValueError):
        service.resolve_many(request)
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "SIMILARITY_READ_FAILURE"
    ]
    assert len(records) == 1
    assert "ValueError" in records[0].message
    assert "synthetic-private-source" not in caplog.text
    assert request.actor_id not in caplog.text


@pytest.mark.parametrize("reverse", (False, True))
def test_catalog_resolves_two_anchors_once_and_restores_input_order(reverse):
    from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
    from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryLookup
    from eom_catalog_service.item_db_similarity_selection import CatalogItemDbSimilaritySelection

    from tests.unit.test_public_solution_index_assembly import setup

    value, raw = list_case(2)
    if reverse:
        raw["selections"].reverse()
    request = ItemDbSimilaritySelectionRequestV2.model_validate(raw)
    root = MagicMock()
    session = root.__enter__.return_value
    scope = EmbeddingRegistryLookup(
        corpus_id="corpus_" + "1" * 32,
        namespace=setup()[3],
        graph_snapshot=value.query.graph_snapshot,
        policy_revision_id=value.query.policy_revision_id,
        policy_sha256=value.query.policy_sha256,
    )
    entries = tuple(
        PublicSolutionEmbeddingEntry.model_construct(
            source=value.source.model_copy(update={"item_revision_id": selection.item_revision_id}),
            public_solution=NS(status="AVAILABLE"),
        )
        for selection in request.selections
    )
    service = object.__new__(CatalogItemDbSimilaritySelection)
    service.sessions = NS(begin=Mock(return_value=root))
    service.owner = NS(
        identity=NS(fence_current_operator=Mock()),
        catalog=NS(
            authorize_scope=Mock(),
            resolve_selected_sources=Mock(return_value=NS(entries=tuple(reversed(entries)))),
        ),
    )
    service._scope = Mock(return_value=(scope, value.result.search_snapshot_sha256))
    service._selected_pointers = Mock(
        return_value=tuple(
            NS(
                item_id=selection.item_id,
                item_revision_id=selection.item_revision_id,
                manifest_sha256=selection.item_manifest_sha256,
            )
            for selection in request.selections
        )
    )
    result = service.resolve_many(request)
    assert result.query.source_item_revision_ids == tuple(
        selection.item_revision_id for selection in request.selections
    )
    assert len(result.anchors) == 2
    assert service.owner.catalog.resolve_selected_sources.call_count == 1
    captured_selection = service.owner.catalog.resolve_selected_sources.call_args.args[2]
    assert captured_selection.source_revision_ids == tuple(
        sorted(selection.item_revision_id for selection in request.selections)
    )
    assert service.owner.identity.fence_current_operator.call_count == 2
    session.execute.assert_not_called()


@pytest.mark.parametrize("count", (2, 32))
def test_bulk_metadata_reads_do_not_grow_per_item(count):
    from eom_catalog_service.item_db_similarity_selection import CatalogItemDbSimilaritySelection

    _value, raw = list_case(count)
    request = ItemDbSimilaritySelectionRequestV2.model_validate(raw)
    revisions = tuple(
        NS(
            item_id=selected.item_id,
            item_revision_id=selected.item_revision_id,
            manifest_sha256=selected.item_manifest_sha256,
            registration_key=None,
            revision_state="APPROVED",
        )
        for selected in request.selections
    )
    session = Mock()
    session.scalars.side_effect = (
        revisions,
        (NS(item_id=revisions[0].item_id, lifecycle_state="ACTIVE"),),
    )
    session.execute.return_value.all.return_value = [
        (selected.graph_snapshot_revision_id, selected.item_revision_id)
        for selected in request.selections
    ]
    service = object.__new__(CatalogItemDbSimilaritySelection)
    service.owner = NS(configuration=NS(registry=NS(source_classes=("PAST_EXAM", "APPROVED_ITEM"))))
    service._require_selected_graph = Mock()
    assert service._selected_pointers(session, request.selections, Mock(), Mock()) == revisions
    assert session.scalars.call_count == 2
    assert session.execute.call_count == 1
    assert service._require_selected_graph.call_count == 1


def test_bulk_metadata_does_not_invent_missing_graph_membership():
    from eom_catalog_service.item_db_similarity_selection import (
        CatalogItemDbSimilaritySelection,
        ItemDbSimilaritySelectionError,
    )

    _value, raw = list_case(2)
    request = ItemDbSimilaritySelectionRequestV2.model_validate(raw)
    revisions = tuple(
        NS(
            item_id=selected.item_id,
            item_revision_id=selected.item_revision_id,
            manifest_sha256=selected.item_manifest_sha256,
            registration_key=None,
            revision_state="APPROVED",
        )
        for selected in request.selections
    )
    session = Mock()
    session.scalars.side_effect = (
        revisions,
        (NS(item_id=revisions[0].item_id, lifecycle_state="ACTIVE"),),
    )
    session.execute.return_value.all.return_value = [
        (request.selections[0].graph_snapshot_revision_id, revisions[0].item_revision_id)
    ]
    service = object.__new__(CatalogItemDbSimilaritySelection)
    service.owner = NS(configuration=NS(registry=NS(source_classes=("PAST_EXAM", "APPROVED_ITEM"))))
    service._require_selected_graph = Mock()
    with pytest.raises(ItemDbSimilaritySelectionError, match="SOURCE_POINTER_INVALID"):
        service._selected_pointers(session, request.selections, Mock(), Mock())


@pytest.mark.parametrize("bad_observation", (False, True))
def test_bulk_external_pointer_uses_real_revision_column_and_exact_observation(bad_observation):
    from eom_catalog_contracts.creative_source_lineage import creative_registration_key
    from eom_catalog_contracts.item_db_similarity_selection import ItemDbExternalSelection
    from eom_catalog_service.item_db_similarity_selection import (
        CatalogItemDbSimilaritySelection,
        ItemDbSimilaritySelectionError,
    )

    pointer = ItemDbExternalSelection(
        kind="EXTERNAL_SOURCE",
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        observation_sha256="sha256:" + "3" * 64,
    )
    revision = NS(
        item_id="item_" + "4" * 32,
        item_revision_id="itemrev_" + "5" * 32,
        registration_key=creative_registration_key(pointer.source_id),
        revision_state="APPROVED",
        metadata_json={
            "source_id": pointer.source_id,
            "source_revision_id": pointer.source_revision_id,
        },
    )
    session = Mock()
    session.execute.return_value = [
        (
            NS(source_id=pointer.source_id, current_revision_id=pointer.source_revision_id),
            NS(
                revision_id=pointer.source_revision_id,
                observation_sha256="sha256:" + "f" * 64
                if bad_observation
                else pointer.observation_sha256,
            ),
        )
    ]
    session.scalars.side_effect = (
        (revision,),
        (NS(item_id=revision.item_id, lifecycle_state="ACTIVE"),),
    )
    service = object.__new__(CatalogItemDbSimilaritySelection)
    service._require_selected_graph = Mock()
    if bad_observation:
        with pytest.raises(ItemDbSimilaritySelectionError, match="SOURCE_POINTER_INVALID"):
            service._selected_pointers(session, (pointer,), Mock(), Mock())
    else:
        assert service._selected_pointers(session, (pointer,), Mock(), Mock()) == (revision,)
    assert session.execute.call_count == 1
    assert session.scalars.call_count == 2
    service._require_selected_graph.assert_not_called()
