"""Opt-in real limited role; the existing disposable manifest is mandatory."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from eom_orchestrator import general_chat_owner_runtime as runtime
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.general_chat_artifacts import GeneralChatArtifactStore
from eom_orchestrator.general_chat_execution import GeneralChatExecutionService
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner
from eom_orchestrator.general_chat_privileges import chat_privileges_ready, chat_role_boundary_ready
from eom_orchestrator.general_chat_protected_environment import read_chat_environment
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_views import GeneralChatCreate, GeneralChatSubmission
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from tests.integration.general_chat_fixtures import (
    IDENTITY,
    RUNTIME,
    ChatFixture,
)
from tests.unit.test_general_chat_resident import answer

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def limited_chat(chat: ChatFixture, monkeypatch):
    state = Path(os.environ["EOM_GENERAL_CHAT_TEST_STATE"])
    manifest = DisposableManifest.load(state / "manifest.json")
    values = read_chat_environment(state / "chat.env", uid=os.getuid(), gid=os.getgid(), mode=0o600)
    assert set(values) == {"EOM_GENERAL_CHAT_DATABASE_URL"}
    url = make_url(values["EOM_GENERAL_CHAT_DATABASE_URL"])
    assert (url.drivername, url.host, url.port, url.username, url.database) == (
        "postgresql+psycopg",
        "127.0.0.1",
        5432,
        manifest.runtime_role,
        manifest.database,
    )
    metadata = create_engine(url, connect_args={"options": "-c search_path=app,pg_catalog"})
    publication = create_engine(
        url, pool_size=2, max_overflow=0, connect_args={"options": "-c search_path=app,pg_catalog"}
    )
    # Only pytest substitutes the disposable exact identity. Production config
    # and entrypoints have no caller-provided role override/fallback.
    monkeypatch.setattr(runtime, "OWNER_DATABASE_ROLE", manifest.runtime_role)
    try:
        runtime.require_chat_owner_database(metadata)
        repository = GeneralChatRepository(metadata)
        evidence = GeneralChatArtifactStore(
            metadata,
            ControlArtifactPublisher(publication, chat.evidence.publisher.settings),
            source_commit="a" * 40,
        )
        owner = GeneralChatConversationOwner(repository, evidence, clock=lambda: chat.now)
        execution = GeneralChatExecutionService(repository, evidence, clock=lambda: chat.now)
        yield metadata, repository, owner, execution, manifest
    finally:
        metadata.dispose()
        publication.dispose()


def test_actual_limited_role_completes_two_private_owner_histories_and_publication(
    limited_chat, chat
):
    engine, _, owner, execution, manifest = limited_chat
    with engine.connect() as connection:
        assert chat_privileges_ready(connection, role=manifest.runtime_role)
        assert chat_role_boundary_ready(connection, role=manifest.runtime_role)
    conversations = {}
    for actor in chat.actors:
        conversation = owner.create(
            actor_id=actor,
            request=GeneralChatCreate(title="role probe"),
            idempotency_key="create-role-" + uuid4().hex,
        )
        key = "submit-role-" + uuid4().hex
        request = GeneralChatSubmission(text="synthetic role question", expected_version=1)
        queued = owner.submit(
            actor_id=actor,
            conversation_id=conversation.conversation_id,
            request=request,
            idempotency_key=key,
        )
        claim = execution.claim_next(runtime_id=RUNTIME)
        assert claim is not None
        turn = execution.prepare(claim, identity=IDENTITY)
        execution.complete(claim, answer(turn))
        execution.complete(claim, answer(turn))
        view = owner.conversation(
            actor_id=actor, conversation_id=conversation.conversation_id, cursor=None
        )
        assert tuple(value.role for value in view.messages) == ("user", "assistant")
        replay = owner.submit(
            actor_id=actor,
            conversation_id=conversation.conversation_id,
            request=request,
            idempotency_key=key,
        )
        assert replay.conversation_id == queued.conversation_id
        assert replay.messages[0].turn_id == queued.messages[0].turn_id
        assert replay.messages[-1].state == "COMPLETED"
        assert replay.messages == view.messages
        conversations[actor] = conversation.conversation_id
    for actor, other in (chat.actors, tuple(reversed(chat.actors))):
        own_list = owner.conversations(actor_id=actor, cursor=None)
        assert conversations[actor] in {value.conversation_id for value in own_list.values}
        assert conversations[other] not in {value.conversation_id for value in own_list.values}
        with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_FOUND"):
            owner.conversation(actor_id=actor, conversation_id=conversations[other], cursor=None)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT password_hash FROM app.operator_credentials WHERE false",
        "SELECT username FROM app.operators WHERE false",
        "UPDATE app.operators SET status=status WHERE false",
        "SELECT slot_id FROM app.worker_slots WHERE false",
        "UPDATE app.jobs SET request=request WHERE false",
        "UPDATE app.artifact_revisions SET approved=approved WHERE false",
        "DELETE FROM app.general_chat_turns WHERE false",
        "CREATE TABLE app.unused_chat_privilege_probe (id integer)",
        "UPDATE app.alembic_version SET version_num=version_num WHERE false",
    ],
)
def test_actual_limited_role_denies_credentials_unrelated_data_and_history_mutations(
    limited_chat, statement
):
    engine, *_ = limited_chat
    with engine.connect() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(statement))
        assert getattr(error.value.orig, "sqlstate", None) == "42501"
        connection.rollback()


def test_extra_independent_column_grant_is_detected_without_global_acl_changes(limited_chat, chat):
    engine, _, _, _, manifest = limited_chat
    with chat.engine.begin() as connection:
        connection.execute(
            text('GRANT SELECT (username) ON app.operators TO "' + manifest.runtime_role + '"')
        )
    try:
        with engine.connect() as connection:
            assert not chat_privileges_ready(connection, role=manifest.runtime_role)
        with pytest.raises(ChatError, match="GENERAL_CHAT_OWNER_DATABASE_NOT_READY"):
            runtime.require_chat_owner_database(engine)
    finally:
        with chat.engine.begin() as connection:
            connection.execute(
                text(
                    'REVOKE SELECT (username) ON app.operators FROM "' + manifest.runtime_role + '"'
                )
            )


def test_missing_required_column_grant_is_detected(limited_chat, chat):
    engine, _, _, _, manifest = limited_chat
    with chat.engine.begin() as connection:
        connection.execute(
            text('REVOKE SELECT (status) ON app.operators FROM "' + manifest.runtime_role + '"')
        )
    try:
        with engine.connect() as connection:
            assert not chat_privileges_ready(connection, role=manifest.runtime_role)
    finally:
        with chat.engine.begin() as connection:
            connection.execute(
                text('GRANT SELECT (status) ON app.operators TO "' + manifest.runtime_role + '"')
            )
