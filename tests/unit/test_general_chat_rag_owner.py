"""Canonical V4 history, exact-pin authorization and owner wire compatibility."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_models import GeneralChatTurnRecord
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner
from eom_orchestrator.general_chat_rag_access import authorize_rag_context, prepare_rag_scope
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat import CHAT_MESSAGE_SCHEMA, StoredChatMessage
from eom_protocol.general_chat_grounding import ChatGroundingQuery, ChatGroundingViews
from eom_protocol.general_chat_owner_messages import (
    ChatOwnerRequest,
    read_chat_owner_reply,
    read_chat_owner_request,
)
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagAuthorizeCommand,
    ChatRagCatalogReply,
    ChatRagPrepareCommand,
)
from eom_protocol.general_chat_rag_turn import (
    RAG_INPUT_SCHEMA,
    RAG_RESULT_SCHEMA,
    ChatGroundingViewsV2,
)
from jsonschema import ValidationError as SchemaError

from tests.unit import test_general_chat_owner_rpc
from tests.unit.general_chat_rag_fixtures import context, request, result, scope
from tests.unit.test_general_chat_agent_search import Evidence

rpc = test_general_chat_owner_rpc.rpc

NOW = datetime(2026, 10, 9, tzinfo=UTC)
ACTOR = "operator_" + "a" * 32


class HistoryEvidence(Evidence):
    def __init__(self):
        super().__init__()
        self.read_calls = []

    def read(self, pointers):
        self.read_calls.append(pointers)
        return super().read(pointers)

    def resolve_family(self, pointers):
        by_identity = {(p.artifact_id, p.artifact_revision_id, p.sha256): p for p in self.payloads}
        return tuple(
            by_identity[(p.artifact_id, p.artifact_revision_id, p.sha256)] for p in pointers
        )


class Authorizer:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.replace = False

    def rag(self, query):
        self.calls.append(query)
        if self.failure:
            return ChatRagCatalogReply(
                status="FAILED", scope=None, context=None, error_code=self.failure
            )
        command = query.command
        if isinstance(command, ChatRagPrepareCommand):
            return ChatRagCatalogReply(
                status="SUCCEEDED", scope=scope(), context=None, error_code=None
            )
        assert isinstance(command, ChatRagAuthorizeCommand)
        value = context() if self.replace else command.context
        return ChatRagCatalogReply(
            status="SUCCEEDED", scope=value.scope, context=value, error_code=None
        )


def history_turn(evidence, *, number=1):
    prepared = request(knowledge=context()).model_copy(
        update={"turn_id": f"chatturn_{number:032x}", "claim_id": f"chatclaim_{number:032x}"}
    )
    answer = result(prepared)
    user = StoredChatMessage(
        conversation_id=prepared.conversation_id,
        turn_id=prepared.turn_id,
        role="user",
        text=prepared.messages[0].text,
    )
    pointers = tuple(
        evidence.publish(
            payload=canonical_json_bytes(value.model_dump(mode="json")),
            schema_ref=schema,
            intent=f"history-{number}-{schema}",
            created_at=NOW,
        )
        for value, schema in (
            (user, CHAT_MESSAGE_SCHEMA),
            (prepared, RAG_INPUT_SCHEMA),
            (answer, RAG_RESULT_SCHEMA),
        )
    )
    row = GeneralChatTurnRecord(
        conversation_id=prepared.conversation_id,
        turn_id=prepared.turn_id,
        claim_id=prepared.claim_id,
        state="COMPLETED",
        user_sequence=2 * number - 1,
        created_at=NOW,
        completed_at=NOW,
    )
    for prefix, pointer in zip(("input", "request", "output"), pointers, strict=True):
        setattr(row, prefix + "_artifact_id", pointer.artifact_id)
        setattr(row, prefix + "_revision_id", pointer.artifact_revision_id)
        setattr(row, prefix + "_sha256", pointer.sha256)
    return row, prepared, answer


def test_history_materialization_is_batched_and_same_rag_context_authorized_once():
    evidence, port = HistoryEvidence(), Authorizer()
    turns = tuple(history_turn(evidence, number=n)[0] for n in range(1, 21))
    owner = GeneralChatConversationOwner(None, evidence, rag_knowledge=port)
    resolved = owner.resolved_turns(request().conversation_id, turns, actor_id=ACTOR)
    messages = owner.project_messages(
        request().conversation_id, turns, actor_id=ACTOR, resolved=resolved
    )
    assert len(messages) == 40 and all(m.text for m in messages)
    assert all(value.rag == context() for value in resolved.values())
    assert [len(batch) for batch in evidence.read_calls] == [60, 0]
    assert len(port.calls) == 1
    assert port.calls[0].actor_id == ACTOR
    assert port.calls[0].command.context == context()


@pytest.mark.parametrize("actor,port", [(None, Authorizer()), (ACTOR, None)])
def test_rag_history_cannot_be_resolved_without_actual_actor_or_authorization_port(actor, port):
    evidence = HistoryEvidence()
    row, prepared, _ = history_turn(evidence)
    owner = GeneralChatConversationOwner(None, evidence, rag_knowledge=port)
    with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
        owner.resolved_turns(prepared.conversation_id, (row,), actor_id=actor)


@pytest.mark.parametrize(
    "failure,code",
    [
        ("CHAT_KNOWLEDGE_FORBIDDEN", "FORBIDDEN"),
        ("CHAT_KNOWLEDGE_UNAVAILABLE", "APPLICATION_UNAVAILABLE"),
        ("CHAT_KNOWLEDGE_POINTER_INVALID", "POINTER_INVALID"),
    ],
)
def test_revoked_unavailable_or_invalid_history_is_not_silently_omitted(failure, code):
    evidence, port = HistoryEvidence(), Authorizer()
    row, prepared, _ = history_turn(evidence)
    port.failure = failure
    owner = GeneralChatConversationOwner(None, evidence, rag_knowledge=port)
    with pytest.raises(ChatError, match="GENERAL_CHAT_" + code):
        owner.resolved_turns(prepared.conversation_id, (row,), actor_id=ACTOR)


def test_authorization_cannot_substitute_a_different_text_or_context():
    from tests.unit.general_chat_rag_fixtures import source

    port = Authorizer()
    port.replace = True
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        authorize_rag_context(port, actor_id=ACTOR, context=context(source(text="다른 분석")))


def test_scope_preparation_checks_pins_and_initial_denial_is_explicitly_optional():
    port = Authorizer()
    assert prepare_rag_scope(port, actor_id=ACTOR, policy=scope().policy, snapshot=None) == scope()
    assert port.calls[0].command.snapshot is None
    for failure in ("CHAT_KNOWLEDGE_FORBIDDEN", "CHAT_KNOWLEDGE_UNAVAILABLE"):
        port.failure = failure
        assert prepare_rag_scope(port, actor_id=ACTOR, policy=scope().policy, snapshot=None) is None
    port.failure = "CHAT_KNOWLEDGE_POINTER_INVALID"
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        prepare_rag_scope(port, actor_id=ACTOR, policy=scope().policy, snapshot=None)
    port.failure = None
    other = scope().policy.model_copy(update={"sha256": "sha256:" + "b" * 64})
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        prepare_rag_scope(port, actor_id=ACTOR, policy=other, snapshot=None)


@pytest.mark.parametrize(
    "code,optional",
    [
        ("GENERAL_CHAT_APPLICATION_UNAVAILABLE", True),
        ("GENERAL_CHAT_FORBIDDEN", True),
        ("GENERAL_CHAT_POINTER_INVALID", False),
    ],
)
def test_initial_optional_boundary_never_hides_an_invalid_pin(code, optional):
    class FailedPort:
        def rag(self, _):
            raise ChatError(code)

    if optional:
        assert (
            prepare_rag_scope(FailedPort(), actor_id=ACTOR, policy=scope().policy, snapshot=None)
            is None
        )
    else:
        with pytest.raises(ChatError, match=code):
            prepare_rag_scope(FailedPort(), actor_id=ACTOR, policy=scope().policy, snapshot=None)


def test_catalog_adapter_keeps_invalid_evidence_distinct_from_transport_failure(monkeypatch):
    from types import SimpleNamespace

    from eom_orchestrator import general_chat_knowledge as adapter
    from eom_protocol.general_chat_rag_knowledge import ChatRagCatalogRequest

    monkeypatch.setattr(adapter.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=123))
    monkeypatch.setattr(adapter.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=456))
    query = ChatRagCatalogRequest(
        actor_id=ACTOR, command=ChatRagPrepareCommand(snapshot=None, policy=scope().policy)
    )
    seen = []

    def forged(endpoint, document, **limits):
        seen.append((endpoint, document, limits))
        return ChatRagCatalogReply(
            status="SUCCEEDED",
            scope=scope().model_copy(
                update={
                    "policy": scope().policy.model_copy(update={"sha256": "sha256:" + "b" * 64})
                }
            ),
            context=None,
            error_code=None,
        ).model_dump(mode="json")

    monkeypatch.setattr(adapter, "exchange_chat_frame", forged)
    with pytest.raises(ChatError, match="GENERAL_CHAT_POINTER_INVALID"):
        adapter.CatalogChatKnowledgeClient().rag(query)
    assert seen[0][1] == query.model_dump(mode="json")
    assert seen[0][2] == {"request_limit": 64000, "reply_limit": 64000, "timeout": 20}

    def disconnected(*_, **__):
        raise OSError("private transport detail")

    monkeypatch.setattr(adapter, "exchange_chat_frame", disconnected)
    with pytest.raises(ChatError, match="GENERAL_CHAT_APPLICATION_UNAVAILABLE"):
        adapter.CatalogChatKnowledgeClient().rag(query)


def test_owner_v4_wire_exposes_rag_views_and_upgrades_old_views_without_history_changes(rpc):
    owner, server, client, _ = rpc
    conversation = "chat_" + "2" * 32
    owner.grounding = lambda **_: ChatGroundingViews(conversation_id=conversation, values=())
    value = client.grounding(
        actor_id=ACTOR, conversation_id=conversation, turn_ids=("chatturn_" + "1" * 32,)
    )
    assert isinstance(value, ChatGroundingViewsV2) and value.values == ()
    query = ChatGroundingQuery(
        actor_id=ACTOR, conversation_id=conversation, turn_ids=("chatturn_" + "1" * 32,)
    )
    wire = read_chat_owner_request(
        ChatOwnerRequest(
            schema_version="general-chat-owner-request/4.0",
            request_id="chatrpc_" + "1" * 32,
            command=query,
        ).model_dump(mode="json")
    )
    reply = server.execute(wire)
    assert read_chat_owner_reply(reply.model_dump(mode="json"), request=wire) == reply
    assert reply.schema_version == "general-chat-owner-reply/4.0"
    legacy = wire.model_copy(update={"schema_version": "general-chat-owner-request/2.0"})
    owner.grounding = lambda **_: value
    assert server.execute(legacy).error_code.value == "GENERAL_CHAT_PROTOCOL_INVALID"
    with pytest.raises((ValueError, SchemaError)):
        read_chat_owner_reply(reply.model_dump(mode="json"), request=legacy)
