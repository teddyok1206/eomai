"""Actual broker/publication; declared synthetic claim, Catalog and native authority."""

from __future__ import annotations

from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.chat_private_query_scope import (
    build_chat_private_query_scope_request,
    validate_chat_private_query_scope_reply,
)
from eom_catalog_contracts.chat_ranked_candidate_read import (
    build_chat_ranked_candidate_read_request,
    validate_chat_ranked_candidate_read_reply,
)
from eom_catalog_contracts.chat_similarity_observation import (
    validate_chat_similarity_observation,
)
from eom_catalog_contracts.chat_similarity_provenance import ChatSimilarityProvenanceError
from eom_catalog_contracts.private_chat_query_prepare import (
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import general_chat_similarity_consumer as consumer
from eom_orchestrator import private_chat_query_completion as completion
from eom_orchestrator.general_chat_rag_broker import ChatRagToolBroker
from eom_orchestrator.general_chat_socket import ChatTransportError
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_rag_tools import ChatToolRequestV2
from eom_protocol.general_chat_tools import ChatToolOutcome
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_chat_similarity_provenance import case as case
from tests.unit.test_chat_similarity_provenance import prepared as prepared
from tests.unit.test_chat_similarity_provenance import store as store
from tests.unit.test_general_chat_agent_search import arguments


class Source:
    def __init__(self, prepared):
        self.origin, self.calls, self.failure = prepared.native.origin, [], None

    def materialize_live_private_query(self, ticket):
        assert ticket == self.origin.ticket
        self.calls.append("materialize")
        return SimpleNamespace(origin=self.origin)

    def authorize_live_private_query(self, origin):
        assert origin == self.origin
        self.calls.append("authorize")
        if self.failure:
            raise ChatError(self.failure)
        return origin


class Native:
    def __init__(self, prepared):
        self.context = prepared.reply.context
        self.calls, self.status, self.failure = [], "READY", None
        self.code = "INDEX_NOT_PREPARED"

    def reply(self, request):
        self.calls.append(request.action)
        if self.failure:
            raise self.failure
        return validate_private_chat_query_prepare_reply(
            request,
            dict(
                schema_version="system-rag-private-chat-query-prepare-reply/1.0",
                action=request.action,
                request_id=request.request_id,
                request_sha256=request.request_sha256,
                status=self.status,
                workflow_id="workflow_" + "1" * 32 if self.status != "UNAVAILABLE" else None,
                context=self.context.model_dump(mode="json") if self.status == "READY" else None,
                error_code=None if self.status in {"PENDING", "READY"} else self.code,
            ),
        )

    def execute(self, request):
        return self.reply(request)

    def continue_pending_original(self, request, acknowledged):
        assert acknowledged.action == "PREPARE_PRIVATE_CHAT_QUERY"
        return self.reply(request)

    def read_original(self, request, acknowledged):
        assert acknowledged.action == "PREPARE_PRIVATE_CHAT_QUERY"
        document = request.model_dump(mode="json", exclude={"request_sha256"})
        document["action"] = "READ_PRIVATE_CHAT_QUERY"
        return self.reply(
            parse_private_chat_query_prepare_request(
                document | {"request_sha256": content_sha256(document)}
            )
        )


class Catalog:
    def __init__(self, prepared):
        self.prepared, self.calls, self.failure = prepared, [], None
        self.cards = prepared.record.outcome.cards
        self.graph = prepared.record.outcome

    def resolve_private_query_scope(self, **values):
        self.calls.append("scope")
        request = build_chat_private_query_scope_request(**values)
        return validate_chat_private_query_scope_reply(
            request,
            dict(
                schema_version="chat-private-query-scope-reply/1.0",
                request_sha256=request.request_sha256,
                status="SUCCEEDED",
                scope=request.scope.model_dump(mode="json"),
                graph_snapshot=self.prepared.native.graph_snapshot.model_dump(mode="json"),
                error_code=None,
            ),
        )

    def read_ranked_candidates(self, **values):
        self.calls.append("metadata")
        if self.failure:
            raise self.failure
        request = build_chat_ranked_candidate_read_request(**values)
        return validate_chat_ranked_candidate_read_reply(
            request,
            dict(
                schema_version="chat-ranked-candidate-read-reply/1.0",
                request_sha256=request.request_sha256,
                status="SUCCEEDED" if self.cards else "EMPTY",
                scope=request.scope.model_dump(mode="json"),
                cards=[c.model_dump(mode="json") for c in self.cards],
                truncated=False,
                error_code=None,
            ),
        )

    def search(self, **values):
        self.calls.append("search")
        return ChatToolOutcome.model_validate(
            self.graph.model_dump(mode="json", exclude={"rag_context"})
        )


@pytest.fixture
def integrated(prepared, store, monkeypatch):
    evidence = store
    # The older READY-provenance fixture uses a synthetic manifest location.
    # This consumer additionally crosses the real closed scope bridge, whose
    # existing canonical member/schema requirements must not be relaxed.
    graph = prepared.native.graph_snapshot.model_dump(mode="json")
    graph["manifest_artifact"].update(
        member_path="projections/manifest.json",
        schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/9.0",
    )
    prepared.native = parse_private_chat_query_prepare_request(
        seal(
            prepared.native.model_dump(mode="json") | {"graph_snapshot": graph},
            "request_sha256",
        )
    )
    context = prepared.reply.context.model_dump(mode="json")
    context["request"] = seal(context["request"] | {"graph_snapshot": graph}, "request_sha256")
    prepared.reply = validate_private_chat_query_prepare_reply(
        prepared.native,
        prepared.reply.model_dump(mode="json")
        | {
            "request_sha256": prepared.native.request_sha256,
            "context": seal(context, "context_sha256"),
        },
    )
    source, native, catalog = Source(prepared), Native(prepared), Catalog(prepared)
    ports = consumer.ChatSimilarityPorts(catalog, native, evidence, Event())
    turn = consumer.ChatSimilarityTurn(
        source=source,
        ticket=source.origin.ticket,
        scope=prepared.scope,
        ports=ports,
    )
    broker = ChatRagToolBroker(
        rpc_request_id=prepared.record.request.rpc_request_id,
        ticket=source.origin.ticket,
        prepared=prepared.turn,
        actor_guard=lambda: source.origin.actor_id,
        knowledge=catalog,
        rag_knowledge=catalog,
        evidence=evidence,
        similarity=turn,
    )
    monkeypatch.setattr(completion, "PRIVATE_CHAT_QUERY_POLL_SECONDS", 0)
    return SimpleNamespace(
        prepared=prepared,
        source=source,
        native=native,
        catalog=catalog,
        turn=turn,
        broker=broker,
        evidence=evidence,
    )


def call(value, *, args=None):
    request = value.prepared.record.request.model_dump(mode="json")
    request["sequence"] = value.broker.transcript.sequence + 1
    if args is not None:
        request["command"]["arguments"] = args.model_dump(mode="json")
    return value.broker.execute(ChatToolRequestV2.model_validate(request))


def observation(value, result):
    read = value.evidence.read_similarity_observation(result.pointer)
    assert read is not None
    assert value.evidence.read((result.pointer,)) == (canonical_json_bytes(result.record),)
    return read


def test_actual_broker_merges_and_atomically_persists_observation_without_fake_citation(integrated):
    value = integrated
    answer = call(value)
    record = observation(value, answer)
    assert record.status == "READY", (
        record.phase,
        record.error_code,
        value.catalog.calls,
        value.native.calls,
    )
    assert answer.record.outcome.cards == value.catalog.cards
    assert record.status == "READY" and record.phase == "COMPLETE"
    assert record.native_reply.action == "READ_PRIVATE_CHAT_QUERY"
    assert record.native_request.action == "PREPARE_PRIVATE_CHAT_QUERY"
    assert record.native_reply.request_sha256 != record.native_request.request_sha256
    assert value.native.calls == ["PREPARE_PRIVATE_CHAT_QUERY", "READ_PRIVATE_CHAT_QUERY"]
    assert value.catalog.calls == ["search", "scope", "metadata"]
    assert value.source.calls.count("authorize") == 2
    assert value.broker.transcript.items.context is None
    assert value.broker.transcript.rag_context is None
    assert value.evidence.publish_similarity_observation(answer.record, record) == answer.pointer
    with pytest.raises(ChatSimilarityProvenanceError):
        value.evidence.read_similarity_provenance(answer.pointer)
    call(value)
    assert value.native.calls.count("PREPARE_PRIVATE_CHAT_QUERY") == 1


@pytest.mark.parametrize("native_status", ["PENDING", "UNAVAILABLE"])
@pytest.mark.parametrize("with_graph", [True, False])
def test_not_ready_does_not_become_empty_or_ready(integrated, native_status, with_graph):
    value = integrated
    value.native.status = native_status
    if not with_graph:
        value.catalog.graph = value.catalog.graph.model_copy(
            update={"status": "EMPTY", "cards": ()}
        )
    result = call(value)
    record = observation(value, result)
    assert record.status == native_status
    assert not record.delivered_native_items
    assert result.record.outcome.status == ("SUCCEEDED" if with_graph else "FAILED")
    assert "metadata" not in value.catalog.calls
    initial_prepares = value.native.calls.count("PREPARE_PRIVATE_CHAT_QUERY")
    call(value)
    assert value.native.calls.count("PREPARE_PRIVATE_CHAT_QUERY") == initial_prepares


def test_unknown_outcome_latches_and_cannot_trigger_a_second_physical_submission(integrated):
    value = integrated
    value.native.failure = ChatTransportError("UNAVAILABLE")
    first = call(value)
    assert observation(value, first).status == "UNKNOWN"
    value.native.failure = None
    second = call(value)
    assert observation(value, second).status == "UNKNOWN"
    assert value.native.calls == ["PREPARE_PRIVATE_CHAT_QUERY"]


@pytest.mark.parametrize("failure", ["GENERAL_CHAT_FORBIDDEN", "GENERAL_CHAT_POINTER_INVALID"])
def test_metadata_integrity_or_permission_error_never_returns_graph_partial_cards(
    integrated, failure
):
    value = integrated
    value.catalog.failure = ChatError(failure)
    result = call(value)
    assert result.record.outcome.status == "FAILED" and not result.record.outcome.cards
    assert observation(value, result).error_code == "INTEGRITY_REJECTED"
    assert result.record.outcome.error_code == (
        "CHAT_KNOWLEDGE_FORBIDDEN"
        if failure == "GENERAL_CHAT_FORBIDDEN"
        else "CHAT_KNOWLEDGE_POINTER_INVALID"
    )


def test_native_order_precedes_graph_and_duplicate_reference_is_not_repeated(integrated):
    value = integrated
    value.catalog.cards = value.catalog.cards[1:2]
    result = call(value)
    assert tuple(c.item for c in result.record.outcome.cards) == (
        value.prepared.refs[1],
        value.prepared.refs[0],
        value.prepared.refs[2],
    )
    assert observation(value, result).delivered_native_items == (value.prepared.refs[1],)


def test_conflicting_manifest_for_same_revision_fails_instead_of_choosing_latest(integrated):
    value = integrated
    cards = list(value.catalog.graph.cards)
    cards[0] = cards[0].model_copy(
        update={
            "item": cards[0].item.model_copy(
                update={
                    "manifest_sha256": "sha256:" + "e" * 64,
                }
            )
        }
    )
    value.catalog.graph = value.catalog.graph.model_copy(update={"cards": tuple(cards)})
    result = call(value)
    assert result.record.outcome.status == "FAILED"
    assert observation(value, result).error_code == "INTEGRITY_REJECTED"


def test_native_source_revocation_after_metadata_discards_even_valid_graph_cards(integrated):
    value = integrated
    original = value.catalog.read_ranked_candidates

    def revoke(**values):
        reply = original(**values)
        value.native.status, value.native.code = "FAILED", "SOURCE_ACCESS_DENIED"
        return reply

    value.catalog.read_ranked_candidates = revoke
    result = call(value)
    assert result.record.outcome.status == "FAILED"
    assert result.record.outcome.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
    record = observation(value, result)
    assert record.native_reply.error_code == "SOURCE_ACCESS_DENIED"
    assert not record.delivered_native_items


def test_failed_graph_search_does_not_start_or_hide_behind_native_query(integrated):
    from eom_protocol.general_chat_rag_tools import failed_rag_tool

    value = integrated
    value.catalog.graph = failed_rag_tool("CHAT_KNOWLEDGE_FORBIDDEN")
    result = call(value)
    assert result.record.outcome.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
    assert not value.native.calls and value.catalog.calls == ["search"]
    assert value.evidence.read_similarity_observation(result.pointer) is None


@pytest.mark.parametrize("fault", ["bytes", "missing"])
def test_new_companion_cannot_disappear_or_change_without_read_failure(integrated, fault):
    from pathlib import Path

    from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
    from eom_orchestrator.models import ArtifactRevisionRecord
    from sqlalchemy import select

    value = integrated
    result = call(value)
    with value.evidence.engine.connect() as connection:
        location = connection.scalar(
            select(ArtifactRevisionRecord.nas_path).where(
                ArtifactRevisionRecord.revision_id == result.pointer.artifact_revision_id,
            )
        )
    member = Path(location) / "chat/similarity-observation.json"
    if fault == "bytes":
        member.write_bytes(b"corrupt")
    else:
        member.unlink()
    with pytest.raises(ControlArtifactResolutionError):
        value.evidence.read_similarity_observation(result.pointer)


def test_source_revocation_during_metadata_read_blocks_delivery_and_publication(integrated):
    value = integrated
    original = value.catalog.read_ranked_candidates

    def revoke(**values):
        reply = original(**values)
        value.source.failure = "GENERAL_CHAT_FORBIDDEN"
        return reply

    value.catalog.read_ranked_candidates = revoke
    with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
        call(value)
    assert value.broker.transcript.sequence == 0


def test_recent_search_keeps_original_route_and_has_no_similarity_companion(integrated):
    value = integrated
    answer = call(value, args=arguments())
    assert value.catalog.calls == ["search"] and not value.native.calls
    assert value.evidence.read_similarity_observation(answer.pointer) is None


def test_execution_binds_consumer_to_actual_claim_service_not_worker_authority(integrated):
    from eom_protocol.general_chat_worker_messages import ChatWorkerExecute, ChatWorkerRequest

    from tests.unit.test_private_chat_query_source import source_case

    value = integrated
    actual = source_case()
    actual.execution.knowledge = value.catalog
    actual.execution.rag_knowledge = value.catalog
    actual.execution.similarity = value.turn.ports
    command = ChatWorkerRequest(
        schema_version="general-chat-worker-request/4.0",
        request_id=value.prepared.record.request.rpc_request_id,
        policy_sha256=actual.ticket.policy_sha256,
        command=ChatWorkerExecute(boot_id="chatboot_" + "9" * 32, turn=actual.prepared),
    )
    broker = actual.execution.tool_broker(command)
    assert isinstance(broker, ChatRagToolBroker)
    assert broker.similarity.source is actual.execution
    assert broker.similarity.ticket == actual.ticket
    assert broker.similarity.scope == actual.prepared.rag_scope
    assert broker.similarity.ports is value.turn.ports


def test_broker_rejects_a_consumer_bound_to_a_different_claim_before_io(integrated):
    value = integrated
    value.turn.ticket = value.turn.ticket.model_copy(update={"claim_id": "chatclaim_" + "a" * 32})
    with pytest.raises(ChatError, match="GENERAL_CHAT_PROTOCOL_INVALID"):
        ChatRagToolBroker(
            rpc_request_id=value.prepared.record.request.rpc_request_id,
            ticket=value.source.origin.ticket,
            prepared=value.prepared.turn,
            actor_guard=lambda: value.source.origin.actor_id,
            knowledge=value.catalog,
            rag_knowledge=value.catalog,
            evidence=value.evidence,
            similarity=value.turn,
        )
    assert not value.native.calls and not value.catalog.calls and not value.source.calls


def test_deadline_and_shutdown_never_submit_native_work(integrated):
    value = integrated
    value.turn.ports.stop.set()
    result = call(value)
    assert observation(value, result).status == "UNAVAILABLE"
    assert not value.native.calls and value.catalog.calls == ["search"]


def test_closed_schema_mirror_and_no_source_text_in_companion(integrated):
    from pathlib import Path

    value = integrated
    result = call(value)
    record = observation(value, result)
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["general-chat-similarity-observation"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("general-chat-similarity-observation"))
    payload = canonical_json_bytes(record)
    assert b'"text"' not in payload and b'"vectors"' not in payload
    for extra in ("actor_role", "text", "vectors", "latest", "permission"):
        with pytest.raises(ChatSimilarityProvenanceError):
            validate_chat_similarity_observation(
                result.record, record.model_dump(mode="json") | {extra: "PRIVATE"}
            )


@pytest.mark.parametrize(
    "change",
    ["sibling", "origin", "scope", "reply_action", "request_hash", "delivered", "empty", "status"],
)
def test_constructed_or_rehashed_false_observation_is_rejected(integrated, change):
    value = integrated
    result = call(value)
    record = observation(value, result)
    document = deepcopy(record.model_dump(mode="json"))
    if change == "sibling":
        document["tool_record_member"]["sha256"] = "sha256:" + "a" * 64
    elif change == "origin":
        document["origin"]["actor_id"] = "operator_" + "a" * 32
    elif change == "scope":
        document["scope"]["policy"]["sha256"] = "sha256:" + "a" * 64
    elif change == "reply_action":
        document["native_reply"]["action"] = "PREPARE_PRIVATE_CHAT_QUERY"
    elif change == "request_hash":
        document["native_request"]["request_sha256"] = "sha256:" + "a" * 64
    elif change == "delivered":
        document["delivered_native_items"][0]["manifest_sha256"] = "sha256:" + "a" * 64
    elif change == "empty":
        document["native_reply"] = None
    else:
        document["status"] = "PENDING"
    with pytest.raises(ChatSimilarityProvenanceError):
        validate_chat_similarity_observation(result.record, seal(document, "observation_sha256"))
    forged = record.model_copy(update={"status": "READY", "extra": "bad"})
    with pytest.raises(ChatSimilarityProvenanceError):
        validate_chat_similarity_observation(result.record, forged)
