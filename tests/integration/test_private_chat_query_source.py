"""Guarded PostgreSQL ownership/claim reads; Catalog/model ports remain synthetic."""

from __future__ import annotations

from datetime import timedelta

import pytest
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_protocol.general_chat_worker_messages import chat_worker_ticket
from sqlalchemy import event, func, select

from tests.integration.test_general_chat_persistence import rag_execution, rag_tools

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def live_source(chat):
    _, identity = rag_execution(chat)
    question = "  속력은 -2 m/s가 아니다.\n조건과 단위를 비교해 주세요.  "
    chat.submit(chat.create(), message=question)
    claim = chat.claim()
    prepared = chat.execution.prepare(claim, identity=identity)
    ticket = chat_worker_ticket(prepared, policy_sha256=identity.policy.sha256)
    try:
        yield question, claim, prepared, identity, ticket
    finally:
        # Close this fixture's work with its original pinned policy, not the
        # generic V1 fixture identity. Never rewrite the dispatch for cleanup.
        if chat.execution.active_claim() == claim:
            chat.execution.complete(
                claim,
                rag_tools(chat, claim, prepared, identity).result(
                    reply="", failure="CODEX_TURN_FAILED"
                ),
            )


def snapshot(chat, turn_id):
    with chat.repository.read_snapshot() as session:
        turn = session.get(GeneralChatTurnRecord, turn_id)
        capacity = session.scalar(select(GeneralChatCapacityRecord))
        return (
            session.scalar(select(func.count()).select_from(JobRecord)),
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)),
            tuple(getattr(turn, column.name) for column in turn.__table__.columns),
            tuple(getattr(capacity, column.name) for column in capacity.__table__.columns),
        )


def test_live_source_and_exact_reauthorization_do_not_publish_renew_or_write(chat, live_source):
    question, claim, _, _, ticket = live_source
    before = snapshot(chat, claim.turn_id)
    statements = []

    def collect(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(chat.engine, "before_cursor_execute", collect)
    try:
        projection = chat.execution.materialize_live_private_query(ticket)
        assert projection.text == question
        assert projection.origin.actor_id == chat.actors[0]
        assert chat.execution.authorize_live_private_query(projection.origin) == projection.origin
    finally:
        event.remove(chat.engine, "before_cursor_execute", collect)
    assert snapshot(chat, claim.turn_id) == before
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def test_expired_claim_is_not_reauthorized_or_renewed(chat, live_source):
    _, claim, _, _, ticket = live_source
    origin = chat.execution.materialize_live_private_query(ticket).origin
    before = snapshot(chat, claim.turn_id)
    original_clock = chat.now
    try:
        chat.now += timedelta(minutes=31)
        with pytest.raises(ChatError):
            chat.execution.authorize_live_private_query(origin)
        assert snapshot(chat, claim.turn_id) == before
    finally:
        chat.now = original_clock


def test_disabled_real_actor_cannot_reuse_an_origin(chat, live_source):
    _, _, _, _, ticket = live_source
    origin = chat.execution.materialize_live_private_query(ticket).origin
    try:
        with chat.repository.sessions.begin() as session:
            session.get(OperatorRecord, chat.actors[0]).status = "DISABLED"
        with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
            chat.execution.authorize_live_private_query(origin)
    finally:
        with chat.repository.sessions.begin() as session:
            session.get(OperatorRecord, chat.actors[0]).status = "ACTIVE"


def test_terminal_history_cannot_be_used_as_live_source(chat, live_source):
    _, claim, prepared, identity, ticket = live_source
    origin = chat.execution.materialize_live_private_query(ticket).origin
    result = rag_tools(chat, claim, prepared, identity).result(
        reply="", failure="CODEX_TURN_FAILED"
    )
    chat.execution.complete(claim, result)
    before = snapshot(chat, claim.turn_id)
    with pytest.raises(ChatError):
        chat.execution.authorize_live_private_query(origin)
    assert snapshot(chat, claim.turn_id) == before


def test_actor_revocation_during_artifact_io_fails_before_text_disclosure(
    chat, live_source, monkeypatch
):
    _, _, _, _, ticket = live_source
    original_read = chat.evidence.read
    changed = False

    def read(pointer, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            with chat.repository.sessions.begin() as session:
                session.get(OperatorRecord, chat.actors[0]).status = "DISABLED"
        return original_read(pointer, **kwargs)

    monkeypatch.setattr(chat.evidence, "read", read)
    try:
        with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
            chat.execution.materialize_live_private_query(ticket)
        assert changed
    finally:
        with chat.repository.sessions.begin() as session:
            session.get(OperatorRecord, chat.actors[0]).status = "ACTIVE"
