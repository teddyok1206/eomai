"""Closed metadata joins/routing; SQL source/role state are declared fixtures here."""

from __future__ import annotations

import json
import os
import socket
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_api_contracts.chat_knowledge import ChatGraphSnapshot, ChatItemCard, ChatKnowledgeSelection
from eom_api_contracts.items import ItemApprovalView
from eom_catalog_contracts.chat_ranked_candidate_read import (
    CHAT_RANKED_READ_REQUEST_BYTES,
    ChatRankedCandidateKey,
    ChatRankedCandidateReadError,
    build_chat_ranked_candidate_read_request,
    chat_ranked_candidate_keys,
    failed_chat_ranked_candidate_read_reply,
    parse_chat_ranked_candidate_read_request,
    validate_chat_ranked_candidate_read_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.chat_knowledge_discovery import (
    candidate_statement,
    validate_ranked_candidate_relations,
)
from eom_catalog_service.chat_knowledge_search import chat_search_query
from eom_catalog_service.chat_rag_resolution import ChatRagResolutionError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator import general_chat_knowledge as adapter
from eom_orchestrator.general_chat_socket import ChatTransportError
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_tools import ChatSearchCatalogRequest
from jsonschema import Draft202012Validator
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from tests.unit.general_chat_rag_fixtures import scope
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_chat_private_query_scope import identities
from tests.unit.test_chat_rag_resolution import ACTOR, PERMISSIONS, policy, service
from tests.unit.test_general_chat_agent_search import arguments
from tests.unit.test_private_chat_similarity_service import case as context_case
from tests.unit.test_private_chat_similarity_service import compose

MANIFEST_HASH = "sha256:" + "b" * 64
COMPONENT_HASH = "sha256:" + "c" * 64


def key(number=1):
    return ChatRankedCandidateKey(
        item_id=f"item_{number:032x}",
        item_revision_id=f"itemrev_{number:032x}",
        source_class="PAST_EXAM",
        component_artifact_id=f"artifact_{number:032x}",
        component_artifact_revision_id=f"rev_{number:032x}",
        component_sha256=COMPONENT_HASH,
    )


def request(count=2, **changes):
    values = dict(
        actor_id=ACTOR,
        scope=scope(),
        arguments=arguments("TOPIC", terms=["전자기"]),
        candidates=tuple(key(n) for n in range(1, count + 1)),
    )
    return build_chat_ranked_candidate_read_request(**(values | changes))


def card(number=1):
    return dict(
        item=dict(
            item_id=key(number).item_id,
            item_revision_id=key(number).item_revision_id,
            manifest_sha256=MANIFEST_HASH,
        ),
        display_name="합성 기출",
        approval="APPROVED",
        source_kind="PAST_EXAM",
        graph_membership="INDEXED",
    )


def reply(query=None):
    query = request() if query is None else query
    return dict(
        schema_version="chat-ranked-candidate-read-reply/1.0",
        request_sha256=query.request_sha256,
        status="SUCCEEDED",
        scope=query.scope.model_dump(mode="json"),
        cards=[card()],
        truncated=False,
        error_code=None,
    )


def test_schema_mirror_and_64_small_keys_have_bounded_canonical_frames():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["chat-ranked-candidate-read"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("chat-ranked-candidate-read"))
    query = request(64)
    assert len(canonical_json_bytes(query)) + 1 <= CHAT_RANKED_READ_REQUEST_BYTES
    result = validate_chat_ranked_candidate_read_reply(query, reply(query))
    assert (
        result.cards[0].item.manifest_sha256
        == MANIFEST_HASH
        != query.candidates[0].component_sha256
    )


def test_native_projection_removes_paths_and_bytes_but_preserves_source_component_identity():
    original, owner = context_case()
    context = compose(original, owner)
    keys = chat_ranked_candidate_keys(context)
    assert len(keys) == len(context.candidates)
    for reference, candidate in zip(keys, context.candidates, strict=True):
        assert reference.item_id == candidate.source.item_id
        assert reference.component_sha256 == candidate.source.artifact_member.sha256
    assert b"materialized_path" not in canonical_json_bytes([v.model_dump() for v in keys])
    assert b'"text"' not in canonical_json_bytes([v.model_dump() for v in keys])


@pytest.mark.parametrize(
    "change", ["actor_role", "path", "latest", "hash", "duplicate", "too_many", "RECENT", "hidden"]
)
def test_request_cannot_supply_authority_paths_latest_or_ambiguous_order(change):
    query = request()
    value = query.model_dump(mode="json")
    if change in {"actor_role", "path"}:
        value[change] = "DO_NOT_DISCLOSE"
    elif change == "latest":
        value["scope"]["snapshot"]["graph_snapshot_revision_id"] = "latest"
    elif change == "hash":
        value["request_sha256"] = MANIFEST_HASH
    elif change == "duplicate":
        value["candidates"].append(deepcopy(value["candidates"][0]))
    elif change == "too_many":
        value["candidates"] = [key(n).model_dump(mode="json") for n in range(1, 66)]
    elif change == "RECENT":
        value["arguments"] = arguments().model_dump(mode="json")
    else:
        value = query.model_copy(update={"authority": "ADMIN"})
    if change not in {"hash", "hidden"}:
        value = seal(value, "request_sha256")
    with pytest.raises(ChatRankedCandidateReadError) as caught:
        parse_chat_ranked_candidate_read_request(value)
    assert str(caught.value) == "CHAT_RANKED_CANDIDATE_READ_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        "request",
        "scope",
        "unoffered",
        "reordered",
        "duplicate",
        "pending",
        "not_indexed",
        "source",
        "source_class",
        "failed_partial",
    ],
)
def test_reply_cannot_substitute_or_promote_candidates(change):
    query = request()
    value = reply(query)
    if change == "request":
        value["request_sha256"] = MANIFEST_HASH
    elif change == "scope":
        value["scope"]["policy"]["sha256"] = MANIFEST_HASH
    elif change == "unoffered":
        value["cards"] = [card(3)]
    elif change == "reordered":
        value["cards"] = [card(2), card(1)]
    elif change == "duplicate":
        value["cards"] = [card(), card()]
    elif change == "pending":
        value["cards"][0]["approval"] = "PENDING"
    elif change == "not_indexed":
        value["cards"][0]["graph_membership"] = "NOT_INDEXED"
    elif change == "source":
        query = request(arguments=arguments("TOPIC", terms=["전자기"], source="GENERATED"))
        value = reply(query)
    elif change == "source_class":
        value["cards"][0]["source_kind"] = "GENERATED"
    else:
        value.update(status="FAILED", error_code="CHAT_KNOWLEDGE_FORBIDDEN")
    with pytest.raises(ChatRankedCandidateReadError):
        validate_chat_ranked_candidate_read_reply(query, value)


def test_failed_and_empty_replies_do_not_disclose_partial_cards():
    query = request()
    failure = failed_chat_ranked_candidate_read_reply(query, "CHAT_KNOWLEDGE_FORBIDDEN")
    assert failure.scope is None and failure.cards == () and not failure.truncated
    empty = reply(query) | dict(status="EMPTY", cards=[])
    assert validate_chat_ranked_candidate_read_reply(query, empty).scope == query.scope


def query_projection(query):
    return chat_search_query(
        ChatSearchCatalogRequest(
            actor_id=query.actor_id, arguments=query.arguments, snapshot=query.scope.snapshot
        )
    )


def sql(statement):
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_ranked_sql_applies_exact_topic_source_component_and_current_filters_before_limit():
    query = request(candidates=(key(17), key(2)))
    text = sql(
        candidate_statement(
            query_projection(query),
            query.scope.snapshot.graph_snapshot_revision_id,
            ranked_candidates=query.candidates,
        )
    )
    assert "item_revisions.item_revision_id = items.current_revision_id" in text
    assert "knowledge_node_source_pointers.source_sha256" in text and COMPONENT_HASH in text
    assert "knowledge_node_terms.term IN ('전자기')" in text
    assert "knowledge_node_source_pointers.source_class" in text
    order = text.rpartition("ORDER BY")[2]
    assert order.index(key(17).item_revision_id) < order.index(key(2).item_revision_id)
    assert "created_at DESC" not in order
    assert text.index("EXISTS") < text.rindex("LIMIT 7")
    assert "item_revisions.revision_state = 'APPROVED'" in text


def test_empty_ranked_pool_is_not_an_unrestricted_query_or_invalid_empty_case():
    query = request(0)
    text = sql(
        candidate_statement(
            query_projection(query),
            query.scope.snapshot.graph_snapshot_revision_id,
            ranked_candidates=(),
        )
    )
    assert "CASE" not in text and "1 != 1" in text


def rows_for(keys):
    return [
        (
            v.item_id,
            v.item_revision_id,
            "ACTIVE",
            v.item_revision_id,
            "APPROVED",
            MANIFEST_HASH,
            v.item_id,
        )
        for v in keys
    ]


def test_preflight_uses_one_bounded_metadata_join_for_64_candidates_not_n_plus_one():
    query = request(64)
    session = Mock()
    session.execute.return_value.tuples.return_value = rows_for(query.candidates)
    validate_ranked_candidate_relations(
        session, query.candidates, query.scope.snapshot.graph_snapshot_revision_id
    )
    session.execute.assert_called_once()
    text = sql(session.execute.call_args.args[0])
    assert "knowledge_snapshot_analyses.source_sha256 = item_components.sha256" in text
    assert (
        "knowledge_snapshot_analyses.source_artifact_revision_id = "
        "item_components.artifact_revision_id" in text
    )
    assert COMPONENT_HASH in text and "display_name" not in text


@pytest.mark.parametrize(
    "change", ["missing", "item_id", "inactive", "retired", "pending", "manifest", "no_current"]
)
def test_preflight_fails_invalid_relations_before_any_title_projection(change):
    query = request(1)
    rows = rows_for(query.candidates)
    if change == "missing":
        rows = []
    else:
        row = list(rows[0])
        position, replacement = {
            "item_id": (0, key(2).item_id),
            "inactive": (2, "DELETED_SOFT"),
            "retired": (4, "RETIRED"),
            "pending": (4, "IN_REVIEW"),
            "manifest": (5, "invalid"),
            "no_current": (1, None),
        }[change]
        row[position] = replacement
        rows = [row]
    session = Mock()
    session.execute.return_value.tuples.return_value = rows
    with pytest.raises(ValueError):
        validate_ranked_candidate_relations(
            session, query.candidates, query.scope.snapshot.graph_snapshot_revision_id
        )
    assert session.execute.call_count == 1


def test_valid_historical_revision_is_not_rewritten_to_latest():
    query = request(1)
    row = list(rows_for(query.candidates)[0])
    row[1], row[4] = key(9).item_revision_id, "SUPERSEDED"
    session = Mock()
    session.execute.return_value.tuples.return_value = [row]
    validate_ranked_candidate_relations(
        session, query.candidates, query.scope.snapshot.graph_snapshot_revision_id
    )
    text = sql(
        candidate_statement(
            query_projection(query),
            query.scope.snapshot.graph_snapshot_revision_id,
            ranked_candidates=query.candidates,
        )
    )
    assert key(1).item_revision_id in text and key(9).item_revision_id not in text


def selected(query):
    return ChatKnowledgeSelection(
        values=(
            ChatItemCard(
                **card()["item"],
                revision_number=1,
                display_name="합성 기출",
                created_at=datetime(2026, 10, 18, tzinfo=UTC),
                approval=ItemApprovalView(status="APPROVED", human_review_required=False),
                source_kind="PAST_EXAM",
                graph_membership="INDEXED",
                exam=None,
            ),
        ),
        snapshot=ChatGraphSnapshot(
            graph_snapshot_revision_id=query.scope.snapshot.graph_snapshot_revision_id,
            snapshot_sha256=query.scope.snapshot.sha256,
        ),
        truncated=False,
    )


def owner_case():
    value = service()
    value.sessions = MagicMock()
    session = value.sessions.return_value.__enter__.return_value
    value._authority = Mock(return_value=(policy(), "ADMIN", PERMISSIONS))
    value._scope = Mock()
    value.discovery = Mock()
    query = request()
    value.discovery.search_in_session.return_value = selected(query)
    return value, session, query


def test_rag_owner_reuses_same_actor_policy_snapshot_and_discovery_transaction():
    value, session, query = owner_case()
    result = value.read_ranked_candidates(query)
    assert result.status == "SUCCEEDED" and result.cards[0].item.manifest_sha256 == MANIFEST_HASH
    value._authority.assert_called_once_with(session, ACTOR, query.scope.policy)
    value._scope.assert_called_once_with(session, query.scope)
    value.discovery.search_in_session.assert_called_once_with(
        session, query_projection(query), actor_id=ACTOR, ranked_candidates=query.candidates
    )
    session.connection.assert_called_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "cause,code",
    [
        (ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN"), "CHAT_KNOWLEDGE_FORBIDDEN"),
        (SQLAlchemyError("private detail"), "CHAT_KNOWLEDGE_UNAVAILABLE"),
        (ValueError("private detail"), "CHAT_KNOWLEDGE_POINTER_INVALID"),
    ],
)
def test_owner_failure_stops_before_metadata_or_titles(cause, code):
    value, _, query = owner_case()
    value._authority.side_effect = cause
    result = value.read_ranked_candidates(query)
    assert result.status == "FAILED" and result.error_code == code
    assert result.cards == () and result.scope is None
    value._scope.assert_not_called()
    value.discovery.search_in_session.assert_not_called()


def test_source_permission_loss_is_not_ignored_by_metadata_read():
    value, _, query = owner_case()
    value._authority.return_value = (
        policy(),
        "ADMIN",
        PERMISSIONS - {PermissionKey.CONTENT_INTAKE_READ},
    )
    assert value.read_ranked_candidates(query).error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
    value.discovery.search_in_session.assert_not_called()


def test_real_temporary_unix_peer_client_and_owner_routing(tmp_path, monkeypatch):
    identities(monkeypatch)
    query = request()
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    handler = Mock(return_value=reply(query))
    server.chat_rag = SimpleNamespace(read_ranked_candidates=handler)
    monkeypatch.setattr(adapter, "CATALOG_APPLICATION_SOCKET_PATH", str(server.socket_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        actual = adapter.CatalogChatKnowledgeClient().read_ranked_candidates(
            actor_id=ACTOR,
            scope=query.scope,
            arguments=query.arguments,
            candidates=query.candidates,
        )
        assert actual.cards[0].item.manifest_sha256 == MANIFEST_HASH
        handler.assert_called_once_with(query)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("kind", ["INVALID", "UNAVAILABLE"])
def test_client_does_not_retry_or_create_a_job_on_transport_failure(monkeypatch, kind):
    identities(monkeypatch)
    wire = Mock(side_effect=ChatTransportError(kind))
    monkeypatch.setattr(adapter, "exchange_chat_frame", wire)
    query = request()
    with pytest.raises(ChatError):
        adapter.CatalogChatKnowledgeClient().read_ranked_candidates(
            actor_id=ACTOR,
            scope=query.scope,
            arguments=query.arguments,
            candidates=query.candidates,
        )
    assert wire.call_count == 1
    assert wire.call_args.kwargs == dict(request_limit=32768, reply_limit=16384, timeout=20)


@pytest.mark.parametrize("fault", ["noncanonical", "role", "hash", "oversized"])
def test_invalid_real_unix_frame_does_not_reach_the_metadata_owner(tmp_path, fault):
    query = request()
    document = query.model_dump(mode="json")
    if fault == "role":
        document["actor_role"] = "ADMIN"
        document = seal(document, "request_sha256")
    elif fault == "hash":
        document["request_sha256"] = MANIFEST_HASH
    elif fault == "oversized":
        document["actor_id"] = "x" * CHAT_RANKED_READ_REQUEST_BYTES
    raw = (
        json.dumps(document).encode() if fault == "noncanonical" else canonical_json_bytes(document)
    ) + b"\n"
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    handler = Mock()
    server.chat_rag = SimpleNamespace(read_ranked_candidates=handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(raw)
            connection.shutdown(socket.SHUT_WR)
            assert connection.recv(16384) == b""
        handler.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("fault", ["pending", "scope", "unoffered"])
def test_actual_owner_never_returns_unverified_discovery_projection(fault):
    value, _, query = owner_case()
    selected_value = selected(query).model_dump(mode="json")
    if fault == "pending":
        selected_value["values"][0]["approval"].update(status="PENDING", human_review_required=True)
    elif fault == "scope":
        selected_value["snapshot"]["snapshot_sha256"] = MANIFEST_HASH
    else:
        selected_value["values"][0].update(
            item_id=key(9).item_id, item_revision_id=key(9).item_revision_id
        )
    value.discovery.search_in_session.return_value = ChatKnowledgeSelection.model_validate(
        selected_value
    )
    result = value.read_ranked_candidates(query)
    assert result.error_code == "CHAT_KNOWLEDGE_POINTER_INVALID"
    assert result.cards == () and result.scope is None
