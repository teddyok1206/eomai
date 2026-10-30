"""Pointer/schema/replay and actual socket framing; source/IAM leaves are explicitly synthetic."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest
from eom_api.services.item_db_similarity_client import CatalogItemDbSimilarityClient
from eom_catalog_contracts.item_db_similarity_selection import (
    ItemDbGraphSelection,
    ItemDbSimilarityItemPin,
    ItemDbSimilarityPreparedSelection,
    ItemDbSimilaritySelectionReply,
    ItemDbSimilaritySelectionRequest,
    validate_item_db_similarity_selection_reply,
)
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_catalog_service import item_db_similarity_selection as module
from eom_catalog_service.item_db_similarity_dispatch import dispatch_item_db_similarity_selection
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_public_solution_similarity_contracts import public_similarity_case

ERRORS = (ValueError, SchemaError)


def selected_case(*, pinned=False):
    context = public_similarity_case()[1]
    source = context.request.anchor.source
    key = "studio:db-similarity:synthetic-request"
    op = "queryprepare_" + content_sha256({"purpose": "ITEM_DATABASE_SEARCH/1.0", "key": key})[7:39]
    selection = ItemDbGraphSelection(
        kind="GRAPH_ITEM",
        item_id=source.item_id,
        item_revision_id=source.item_revision_id,
        item_manifest_sha256="sha256:" + "9" * 64,
        graph_snapshot_revision_id=context.request.graph_snapshot.graph_snapshot_revision_id,
        graph_snapshot_sha256="sha256:" + "8" * 64,
    )
    value = dict(
        schema_version="system-rag-reference-query-prepare-request/4.0",
        operation="PREPARE_REFERENCE_QUERY",
        operation_id=op,
        idempotency_key=key,
        source_item_revision_ids=[source.item_revision_id],
        graph_snapshot=context.request.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=context.request.policy_revision_id,
        policy_sha256=context.request.policy_sha256,
        consumer_purpose="ITEM_DATABASE_SEARCH",
        top_k=context.request.top_k,
    )
    query = ReferenceQueryPrepareRequestV4.model_validate(
        value | {"request_sha256": content_sha256(value)}
    )
    request = ItemDbSimilaritySelectionRequest(
        schema_version="item-db-similarity-selection-request/1.0",
        operation="RESOLVE_ITEM_DB_SIMILARITY",
        actor_id="operator_" + "1" * 32,
        operation_id=op,
        idempotency_key=key,
        selection=selection,
        top_k=query.top_k,
        pinned_query=query if pinned else None,
    )
    result = ItemDbSimilarityPreparedSelection(
        selection_sha256=content_sha256(selection),
        anchor=ItemDbSimilarityItemPin(
            item_id=source.item_id,
            item_revision_id=source.item_revision_id,
            item_manifest_sha256=selection.item_manifest_sha256,
        ),
        query=query,
        search_snapshot_sha256=selection.graph_snapshot_sha256,
    )
    reply = ItemDbSimilaritySelectionReply(
        schema_version="item-db-similarity-selection-reply/1.0",
        operation="RESOLVE_ITEM_DB_SIMILARITY",
        status="READY",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request),
        result=result,
        error_code=None,
    )
    return NS(**locals())


def test_closed_pointer_and_original_query_are_not_authority_or_paths():
    value = selected_case(pinned=True)
    validate_item_db_similarity_selection_reply(value.request, value.reply)
    for field in ("actor_id", "path", "runtime", "vectors", "permissions"):
        with pytest.raises(ERRORS):
            ItemDbGraphSelection.model_validate(
                value.selection.model_dump(mode="json") | {field: "x"}
            )


@pytest.mark.parametrize("field", ("idempotency_key", "operation_id", "top_k", "selection"))
def test_replay_cannot_mix_a_different_original_source_or_intent(field):
    value = selected_case(pinned=True)
    changed = value.request.model_dump(mode="json")
    if field == "selection":
        changed[field]["item_revision_id"] = "itemrev_" + "f" * 32
    else:
        changed[field] = (
            9
            if field == "top_k"
            else "queryprepare_" + "f" * 32
            if field == "operation_id"
            else "changed-request-key"
        )
    with pytest.raises(ERRORS):
        ItemDbSimilaritySelectionRequest.model_validate(changed)


@pytest.mark.parametrize("field", ("actor", "request", "source", "query"))
def test_reply_binds_the_actual_actor_source_and_original_query(field):
    value = selected_case(pinned=True)
    body = value.reply.model_dump(mode="json")
    if field == "actor":
        body["actor_id"] = "operator_" + "f" * 32
    elif field == "request":
        body["request_sha256"] = "sha256:" + "f" * 64
    elif field == "source":
        body["result"]["anchor"]["item_manifest_sha256"] = "sha256:" + "f" * 64
    else:
        body["result"]["search_snapshot_sha256"] = None
    with pytest.raises(ERRORS):
        validate_item_db_similarity_selection_reply(
            value.request, ItemDbSimilaritySelectionReply.model_validate(body)
        )


def test_dispatch_and_fixed_client_preserve_the_exact_current_operator(monkeypatch, tmp_path):
    from eom_api.services import item_db_similarity_client as client_module

    value = selected_case()
    service = NS(resolve=Mock(return_value=value.result))

    def exchange(_endpoint, document, **_options):
        import json

        return json.loads(
            dispatch_item_db_similarity_selection(service, canonical_json_bytes(document) + b"\n")
        )

    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogItemDbSimilarityClient(ChatSocketEndpoint(tmp_path / "synthetic.sock", 42, 43))
    assert client.resolve(value.request) == value.reply
    service.resolve.assert_called_once_with(value.request)


def test_missing_owner_does_not_select_a_legacy_owner_or_change_the_request():
    import json

    value = selected_case()
    reply = ItemDbSimilaritySelectionReply.model_validate(
        json.loads(
            dispatch_item_db_similarity_selection(
                None, canonical_json_bytes(value.request) + b"\n"
            ),
        )
    )
    validate_item_db_similarity_selection_reply(value.request, reply)
    assert reply.status == "UNAVAILABLE" and reply.error_code == "ITEM_DB_SIMILARITY_UNAVAILABLE"


def test_pinned_scope_replay_uses_exact_original_graph_and_never_reads_a_new_head(monkeypatch):
    value = selected_case(pinned=True)
    owner = NS(
        configuration=NS(registry=NS(corpus_id="corpus_" + "1" * 32, namespace="synthetic-public"))
    )
    service = object.__new__(module.CatalogItemDbSimilaritySelection)
    service.owner = owner
    service.retrieval = NS(resolve_snapshot_pointer=Mock(return_value=value.query.graph_snapshot))
    session = Mock()
    session.get.return_value = NS(
        state="PUBLISHED", snapshot_sha256=value.result.search_snapshot_sha256
    )
    repository = Mock(side_effect=AssertionError("replay cannot select another head"))
    monkeypatch.setattr(module, "EmbeddingRegistryRepository", repository)
    scope, digest = service._scope(session, value.request)
    assert scope.graph_snapshot == value.query.graph_snapshot
    assert scope.policy_revision_id == value.query.policy_revision_id
    assert digest == value.result.search_snapshot_sha256
    session.get.assert_called_once_with(
        KnowledgeGraphSnapshotRecord, value.query.graph_snapshot.graph_snapshot_revision_id
    )
    repository.assert_not_called()


def test_mismatched_device_head_never_fabricates_one_search_scope(monkeypatch):
    value = selected_case()
    registry = NS(corpus_id="corpus_" + "1" * 32, namespace="cpu")
    owner = NS(
        configuration=NS(registry=registry),
        cuda_owner=NS(configuration=NS(registry=NS(namespace="cuda"))),
    )
    service = object.__new__(module.CatalogItemDbSimilaritySelection)
    service.owner = owner
    service.retrieval = Mock()
    cpu = NS(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        policy_revision_id="accessrev_" + "1" * 32,
        policy_sha256="sha256:" + "1" * 64,
    )
    cuda = NS(graph_snapshot_revision_id="graphrev_" + "2" * 32)
    repository = NS(current_namespace_revision=Mock(side_effect=((cpu, 2), (cuda, 2))))
    monkeypatch.setattr(module, "EmbeddingRegistryRepository", lambda _session: repository)
    with pytest.raises(module.ItemDbSimilaritySelectionError, match="NOT_INDEXED"):
        service._scope(Mock(), value.request)
    service.retrieval.resolve_snapshot_pointer.assert_not_called()


def test_revoked_identity_stops_before_any_source_or_index_work():
    from eom_identity_service import OperatorAuthorizationFenceError

    value = selected_case()
    service = object.__new__(module.CatalogItemDbSimilaritySelection)
    root = MagicMock()
    service.sessions = NS(begin=Mock(return_value=root))
    service.owner = NS(
        identity=NS(
            fence_current_operator=Mock(
                side_effect=OperatorAuthorizationFenceError("AUTHORITY_UNAVAILABLE")
            )
        )
    )
    service._scope = Mock(side_effect=AssertionError("source work forbidden"))
    with pytest.raises(module.ItemDbSimilaritySelectionError, match="AUTHORITY_UNAVAILABLE"):
        service.resolve(value.request)
    service._scope.assert_not_called()


@pytest.mark.parametrize("pinned", (False, True))
def test_successful_resolution_keeps_original_source_and_fences_both_ends(pinned):
    from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
    from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryLookup

    from tests.unit.test_public_solution_index_assembly import setup

    value = selected_case(pinned=pinned)
    service = object.__new__(module.CatalogItemDbSimilaritySelection)
    root = MagicMock()
    session = root.__enter__.return_value
    service.sessions = NS(begin=Mock(return_value=root))
    scope = EmbeddingRegistryLookup(
        corpus_id="corpus_" + "1" * 32,
        namespace=setup()[3],
        graph_snapshot=value.query.graph_snapshot,
        policy_revision_id=value.query.policy_revision_id,
        policy_sha256=value.query.policy_sha256,
    )
    # The real public entry's remaining fields are already covered by its own
    # schema tests; this leaf only tests adapter selection and identity closure.
    entry = PublicSolutionEmbeddingEntry.model_construct(
        source=value.source, public_solution=NS(status="AVAILABLE")
    )
    service.owner = NS(
        identity=NS(fence_current_operator=Mock()),
        catalog=NS(
            authorize_scope=Mock(),
            resolve_selected_sources=Mock(return_value=NS(entries=(entry,))),
        ),
    )
    service._scope = Mock(return_value=(scope, value.result.search_snapshot_sha256))
    service._selected_revision = Mock(
        return_value=NS(
            item_id=value.source.item_id,
            item_revision_id=value.source.item_revision_id,
            manifest_sha256=value.selection.item_manifest_sha256,
        )
    )
    assert service.resolve(value.request) == value.result
    session.execute.assert_not_called()
    assert service.owner.identity.fence_current_operator.call_args_list == [
        ((session, value.request.actor_id),),
        ((session, value.request.actor_id),),
    ]
    assert service.owner.catalog.resolve_selected_sources.call_count == 1


def test_catalog_operation_round_trip_uses_actual_unix_peer_gate(tmp_path):
    import os
    import socket
    import threading

    from tests.unit.test_catalog_application_boundary import _server

    value = selected_case()
    server = _server(tmp_path)
    service = NS(resolve=Mock(return_value=value.result))
    server.item_db_similarity_selection = service
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogItemDbSimilarityClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        assert client.resolve(value.request) == value.reply
        service.resolve.assert_called_once_with(value.request)
        server.allowed_uid = os.getuid() + 100000
        server.chat_owner_uid = os.getuid()
        left, right = socket.socketpair(socket.AF_UNIX)
        try:
            assert server.peer_is_allowed(left)
            assert not server.peer_can_operate(left, value.request.operation)
        finally:
            left.close()
            right.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("failure", ("manifest", "membership", "lifecycle", "external"))
def test_selected_revision_requires_exact_pointer_membership_and_lifecycle(failure):
    from eom_catalog_contracts.item_db_similarity_selection import ItemDbExternalSelection
    from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
    from eom_catalog_service.models import ItemRecord, ItemRevisionRecord

    value = selected_case()
    service = object.__new__(module.CatalogItemDbSimilaritySelection)
    service._require_selected_graph = Mock()
    revision = NS(
        item_id=value.source.item_id,
        item_revision_id=value.source.item_revision_id,
        manifest_sha256=value.selection.item_manifest_sha256,
        revision_state="APPROVED",
    )
    item = NS(lifecycle_state="ACTIVE")
    session = Mock()
    session.get.side_effect = lambda model, _key: revision if model is ItemRevisionRecord else item
    request = value.request
    if failure == "manifest":
        revision.manifest_sha256 = "sha256:" + "f" * 64
    elif failure == "membership":
        service._require_selected_graph.side_effect = module.ItemDbSimilaritySelectionError(
            "SOURCE_POINTER_INVALID"
        )
    elif failure == "lifecycle":
        item.lifecycle_state = "REVOKED"
    else:
        request = value.request.model_copy(
            update={
                "selection": ItemDbExternalSelection(
                    kind="EXTERNAL_SOURCE",
                    source_id="extitem_" + "1" * 32,
                    source_revision_id="extitemrev_" + "2" * 32,
                    observation_sha256="sha256:" + "3" * 64,
                )
            }
        )
        session.get.side_effect = None
        session.get.return_value = None
    with pytest.raises(module.ItemDbSimilaritySelectionError):
        service._selected_revision(
            session, request, EmbeddingRegistryCaller(request.actor_id), Mock()
        )
    if failure in {"manifest", "external"}:
        service._require_selected_graph.assert_not_called()
    if failure == "lifecycle":
        assert session.get.call_args.args[0] is ItemRecord
