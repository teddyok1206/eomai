"""Guarded disposable PostgreSQL + canonical local Artifact reads; zero inference."""

from __future__ import annotations

import pytest
from eom_identifiers import sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.general_chat_models import GeneralChatTurnRecord
from eom_orchestrator.general_chat_similarity_basis import read_owned_private_chat_query
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_protocol.general_chat_grounding import GroundedChatSubmission
from sqlalchemy import Select, event, func, select

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def read(chat, conversation, turn_id, *, actor=0, evidence=None):
    return read_owned_private_chat_query(
        chat.repository,
        chat.evidence if evidence is None else evidence,
        actor_id=chat.actors[actor],
        conversation_id=conversation.conversation_id,
        turn_id=turn_id,
    )


@pytest.mark.parametrize("grounded", [False, True])
def test_owned_query_exact_replay_is_read_only_and_resolves_one_registered_message(chat, grounded):
    conversation = chat.create()
    text = "  속력이 2배이면 이동 거리는?\n단위도 비교해줘.  "
    if grounded:
        conversation = chat.owner.submit(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            request=GroundedChatSubmission(text=text, expected_version=1, selection=None),
            idempotency_key="private-chat-grounded-query",
        )
    else:
        conversation = chat.submit(conversation, message=text)
    turn_id = conversation.messages[0].turn_id
    with chat.repository.read_snapshot() as session:
        before = (
            session.scalar(select(func.count()).select_from(JobRecord)),
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)),
        )
        original = session.get(GeneralChatTurnRecord, turn_id)
        original_pointer = (
            original.input_artifact_id,
            original.input_revision_id,
            original.input_sha256,
        )
        state = original.state
    statements = []
    turn_reads = []

    def collect(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
        query = None if context.compiled is None else context.compiled.statement
        if isinstance(query, Select) and GeneralChatTurnRecord.__table__ in query.get_final_froms():
            turn_reads.append(statement)

    event.listen(chat.engine, "before_cursor_execute", collect)
    try:
        first, second = read(chat, conversation, turn_id), read(chat, conversation, turn_id)
    finally:
        event.remove(chat.engine, "before_cursor_execute", collect)
    assert first == second and first.text == text
    assert first.basis.query_text_sha256 == sha256_bytes(text.encode())
    assert first.basis.message.schema_ref.endswith("/2.0" if grounded else "/1.0")
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )
    # A bounded PK lookup, never a conversation-wide message/history materialization.
    assert len(turn_reads) == 4
    assert all("general_chat_turns.turn_id =" in statement for statement in turn_reads)
    with chat.repository.read_snapshot() as session:
        assert before == (
            session.scalar(select(func.count()).select_from(JobRecord)),
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)),
        )
        current = session.get(GeneralChatTurnRecord, turn_id)
        assert (
            current.input_artifact_id,
            current.input_revision_id,
            current.input_sha256,
        ) == original_pointer
        assert current.state == state == "QUEUED" and current.claim_id is None


def test_foreign_conversation_and_cross_conversation_turn_are_denied(chat):
    first = chat.submit(chat.create())
    second = chat.create(actor=1)
    turn_id = first.messages[0].turn_id
    for conversation, actor in ((first, 1), (second, 1)):
        with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_FOUND"):
            read(chat, conversation, turn_id, actor=actor)
    with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_FOUND"):
        read(chat, first, "chatturn_" + "f" * 32)


def test_actor_revocation_in_separate_committed_transaction_is_rechecked_after_read(chat):
    conversation = chat.submit(chat.create())
    turn_id = conversation.messages[0].turn_id

    class RevokingEvidence:
        def resolve_family(self, pointers):
            return chat.evidence.resolve_family(pointers)

        def read(self, pointers):
            payloads = chat.evidence.read(pointers)
            with chat.repository.sessions.begin() as session:
                session.get(OperatorRecord, chat.actors[0]).status = "DISABLED"
            return payloads

    try:
        with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
            read(chat, conversation, turn_id, evidence=RevokingEvidence())
    finally:
        # Test-only restoration in the guarded disposable DB, never runtime row repair.
        with chat.repository.sessions.begin() as session:
            session.get(OperatorRecord, chat.actors[0]).status = "ACTIVE"


def test_replaced_or_missing_artifact_is_not_silently_recovered(chat):
    conversation = chat.submit(chat.create())
    turn_id = conversation.messages[0].turn_id

    class MissingEvidence:
        def resolve_family(self, pointers):
            return chat.evidence.resolve_family(pointers)

        def read(self, pointers):
            raise FileNotFoundError("synthetic missing canonical member")

    with pytest.raises(ChatError, match=r"^GENERAL_CHAT_POINTER_INVALID$"):
        read(chat, conversation, turn_id, evidence=MissingEvidence())
