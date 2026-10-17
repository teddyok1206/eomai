"""Synthetic owner metadata and real canonical bytes; never production authority."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_read import (
    parse_private_chat_query_read_reply,
    parse_private_chat_query_read_request,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_execution import GeneralChatExecutionService
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_private_query_source import GeneralChatPrivateQuerySource
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_MESSAGE_SCHEMA
from eom_protocol.general_chat_dispatch import ChatDispatchReceipt, ChatExecutionIdentity
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA, RagChatTurnInput
from eom_protocol.general_chat_worker_messages import chat_worker_ticket

from tests.unit.general_chat_rag_fixtures import request as rag_request
from tests.unit.inference_transfer_fixtures import NOW

ACTOR = "operator_" + "7" * 32
RUNTIME = "chatrt_" + "8" * 32


class MemorySourceEvidence:
    def __init__(self, repository):
        self.repository = repository
        self.members = {}
        self.reads = []
        self.callback = None

    def add(self, seed, schema, payload):
        pointer = ArtifactMemberPointer(
            artifact_id="artifact_" + seed * 32,
            artifact_revision_id="rev_" + seed * 32,
            member_path="chat/evidence.json",
            schema_ref=schema,
            media_type="application/json",
            sha256=sha256_bytes(payload),
        )
        self.members[pointer.artifact_id] = (pointer, payload)
        return pointer

    def resolve_family(self, hints):
        return tuple(self.members[v.artifact_id][0] for v in hints)

    def read(self, pointers):
        assert self.repository.open_sessions == 0
        self.reads.append(pointers)
        values = tuple(self.members[v.artifact_id][1] for v in pointers)
        if self.callback is not None:
            self.callback(len(self.reads))
        return values

    def publish(self, **kwargs):
        raise AssertionError("source reads cannot publish")


class SourceRepository:
    def __init__(self, prepared):
        self.open_sessions = 0
        self.revoked = False
        self.owner = ACTOR
        self.prepared = prepared
        self.sessions = SimpleNamespace(begin=self.read_snapshot)
        self.cap = SimpleNamespace(
            runtime_id=RUNTIME,
            active_turn_id=prepared.turn_id,
            claim_id=prepared.claim_id,
            expires_at=NOW + timedelta(minutes=10),
        )
        self.row = SimpleNamespace(
            conversation_id=prepared.conversation_id,
            turn_id=prepared.turn_id,
            claim_id=prepared.claim_id,
            state="RUNNING",
        )

    @contextmanager
    def read_snapshot(self):
        self.open_sessions += 1
        try:
            yield object()
        finally:
            self.open_sessions -= 1

    def capacity(self, session, *, lock=False):
        return self.cap

    def turn(self, session, turn_id, *, lock=False):
        if turn_id != self.row.turn_id:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return self.row

    def conversation_record(self, session, conversation_id, **kwargs):
        if conversation_id != self.row.conversation_id:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return SimpleNamespace(owner_id=self.owner)

    def require_actor(self, session, actor):
        if self.revoked:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")

    def owned(self, session, actor, conversation_id):
        if actor != self.owner:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return self.conversation_record(session, conversation_id)


def source_case(*, original_text=None, question=None, identity_seed: str | None = None):
    prepared = rag_request()
    if identity_seed is not None:
        prepared = RagChatTurnInput.model_validate(
            prepared.model_dump(mode="json")
            | {
                "conversation_id": "chat_" + identity_seed,
                "turn_id": "chatturn_" + identity_seed,
                "claim_id": "chatclaim_" + identity_seed,
            }
        )
    if question is not None:
        messages = [{"role": "user", "text": question}]
        prepared = RagChatTurnInput.model_validate(
            prepared.model_dump(mode="json")
            | {
                "messages": messages,
                "context_sha256": sha256_bytes(canonical_json_bytes(messages)),
            }
        )
    repository = SourceRepository(prepared)
    evidence = MemorySourceEvidence(repository)
    policy = source_chat_worker_policy(model="synthetic-model", protocol=4)
    ticket = chat_worker_ticket(prepared, policy_sha256=policy.sha256)
    input_member = evidence.add("1", RAG_INPUT_SCHEMA, canonical_json_bytes(prepared))
    dispatch = ChatDispatchReceipt(
        schema_version="general-chat-dispatch/4.0",
        runtime_id=RUNTIME,
        identity=ChatExecutionIdentity(boot_id="chatboot_" + "9" * 32, policy=policy),
        ticket=ticket,
        input=input_member,
    )
    dispatch_member = evidence.add(
        "2", "eom://schemas/general-chat/dispatch/4.0", canonical_json_bytes(dispatch)
    )
    user = {
        "schema_version": "general-chat-message/1.0",
        "conversation_id": prepared.conversation_id,
        "turn_id": prepared.turn_id,
        "role": "user",
        "text": prepared.messages[-1].text if original_text is None else original_text,
    }
    message = evidence.add("3", CHAT_MESSAGE_SCHEMA, canonical_json_bytes(user))
    row = repository.row
    row.request_artifact_id, row.request_revision_id, row.request_sha256 = (
        input_member.artifact_id,
        input_member.artifact_revision_id,
        input_member.sha256,
    )
    row.dispatch_artifact_id, row.dispatch_revision_id, row.dispatch_sha256 = (
        dispatch_member.artifact_id,
        dispatch_member.artifact_revision_id,
        dispatch_member.sha256,
    )
    row.input_artifact_id, row.input_revision_id, row.input_sha256 = (
        message.artifact_id,
        message.artifact_revision_id,
        message.sha256,
    )
    execution = GeneralChatExecutionService(repository, evidence, clock=lambda: NOW)
    return SimpleNamespace(
        execution=execution,
        source=GeneralChatPrivateQuerySource(execution),
        repository=repository,
        evidence=evidence,
        ticket=ticket,
        prepared=prepared,
    )


def request(ticket=None, origin=None):
    command = (
        {"action": "MATERIALIZE_LIVE_CHAT_QUERY", "ticket": ticket.model_dump(mode="json")}
        if origin is None
        else {"action": "AUTHORIZE_LIVE_CHAT_QUERY", "origin": origin.model_dump(mode="json")}
    )
    return parse_private_chat_query_read_request(
        {
            "schema_version": "general-chat-private-query-read-request/1.0",
            "request_id": "chatqueryrpc_" + "a" * 32,
            "command": command,
        }
    )


def test_actual_owner_derived_from_live_claim_and_canonical_dispatch_not_wire_actor():
    value = source_case()
    query = request(value.ticket)
    reply = value.source.read(query)
    parse_private_chat_query_read_reply(reply, request=query)
    assert reply.status == "SUCCEEDED"
    assert reply.value.origin.actor_id == ACTOR
    assert reply.value.origin.runtime_id == RUNTIME
    assert reply.value.origin.ticket == value.ticket
    assert reply.value.text == value.prepared.messages[-1].text
    assert len(value.evidence.reads) == 2
    assert value.execution.require_live_tool_actor(value.ticket) == ACTOR
    again = value.source.read(request(origin=reply.value.origin))
    assert again.value == reply.value.origin
    assert not hasattr(again.value, "text")
    assert (
        value.repository.row.state == "RUNNING"
        and value.repository.cap.expires_at == NOW + timedelta(minutes=10)
    )


@pytest.mark.parametrize(
    "fault", ["expired", "terminal", "claim", "request", "policy", "runtime", "revoked", "question"]
)
def test_invalid_or_no_longer_live_source_never_discloses_question(fault):
    value = source_case(original_text="다른 원본 질문" if fault == "question" else None)
    ticket = value.ticket
    if fault == "expired":
        value.repository.cap.expires_at = NOW
    elif fault == "terminal":
        value.repository.row.state = "COMPLETED"
    elif fault == "claim":
        ticket = ticket.model_copy(update={"claim_id": "chatclaim_" + "f" * 32})
    elif fault == "request":
        ticket = ticket.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    elif fault == "policy":
        ticket = ticket.model_copy(update={"policy_sha256": "sha256:" + "f" * 64})
    elif fault == "runtime":
        value.repository.cap.runtime_id = "chatrt_" + "f" * 32
    elif fault == "revoked":
        value.repository.revoked = True
    reply = value.source.read(request(ticket))
    assert reply.status == "FAILED" and reply.value is None
    assert value.prepared.messages[-1].text not in canonical_json_bytes(reply).decode()


@pytest.mark.parametrize("fault", ["actor", "owner", "claim", "message", "request", "dispatch"])
def test_late_revocation_and_pointer_changes_fail_after_read(fault):
    value = source_case()

    def mutate(count):
        if count != 2:
            return
        if fault == "actor":
            value.repository.revoked = True
        elif fault == "owner":
            value.repository.owner = "operator_" + "f" * 32
        elif fault == "claim":
            value.repository.cap.expires_at = NOW
        elif fault == "message":
            value.repository.row.input_sha256 = "sha256:" + "f" * 64
        elif fault == "request":
            value.repository.row.request_revision_id = "rev_" + "f" * 32
        else:
            value.repository.row.dispatch_sha256 = "sha256:" + "f" * 64

    value.evidence.callback = mutate
    reply = value.source.read(request(value.ticket))
    assert reply.status == "FAILED" and reply.value is None


def test_origin_is_reauthorized_and_not_a_reusable_native_grant():
    value = source_case()
    origin = value.execution.materialize_live_private_query(value.ticket).origin
    value.repository.row.state = "COMMITTING"
    reply = value.source.read(request(origin=origin))
    assert reply.status == "FAILED" and reply.value is None


def test_family_resolution_cannot_substitute_identical_bytes_from_another_revision():
    value = source_case()
    original = value.evidence.resolve_family

    def substitute(hints):
        resolved = original(hints)
        if len(resolved) == 2:
            old = resolved[1]
            foreign = old.model_copy(
                update={
                    "artifact_id": "artifact_" + "f" * 32,
                    "artifact_revision_id": "rev_" + "f" * 32,
                }
            )
            value.evidence.members[foreign.artifact_id] = (
                foreign,
                value.evidence.members[old.artifact_id][1],
            )
            return resolved[0], foreign
        return resolved

    value.evidence.resolve_family = substitute
    reply = value.source.read(request(value.ticket))
    assert reply.status == "FAILED" and reply.value is None
    assert value.evidence.reads == []


def test_unknown_private_read_error_is_sanitized():
    value = source_case()
    value.execution.materialize_live_private_query = lambda _: (_ for _ in ()).throw(
        RuntimeError("private-question-and-path")
    )
    reply = value.source.read(request(value.ticket))
    assert reply.error_code == "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
    assert "private-question" not in canonical_json_bytes(reply).decode()
