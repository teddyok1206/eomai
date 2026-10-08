"""Shared guarded PostgreSQL fixture; synthetic answers and local Artifacts only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.general_chat_artifacts import GeneralChatArtifactStore
from eom_orchestrator.general_chat_execution import ChatClaim, GeneralChatExecutionService
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.settings import Settings
from eom_protocol.general_chat import ChatTurnInput, ChatTurnResult
from eom_protocol.general_chat_dispatch import ChatExecutionIdentity
from eom_protocol.general_chat_views import GeneralChatCreate, GeneralChatSubmission
from sqlalchemy import Engine, create_engine, text

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableDatabaseManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.test_general_chat_worker_handoff import BOOT, policy

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
RUNTIME = "chatrt_" + "a" * 32
IDENTITY = ChatExecutionIdentity(boot_id=BOOT, policy=policy())


@dataclass
class ChatFixture:
    engine: Engine
    repository: GeneralChatRepository
    evidence: GeneralChatArtifactStore
    owner: GeneralChatConversationOwner
    execution: GeneralChatExecutionService
    actors: tuple[str, str]
    now: datetime = NOW

    def create(self, actor: int = 0):
        return self.owner.create(
            actor_id=self.actors[actor],
            request=GeneralChatCreate(title="테스트 대화"),
            idempotency_key="create-" + uuid4().hex,
        )

    def submit(self, conversation, *, actor: int = 0, message: str = "질문"):
        return self.owner.submit(
            actor_id=self.actors[actor],
            conversation_id=conversation.conversation_id,
            request=GeneralChatSubmission(
                text=message, expected_version=conversation.resource_version
            ),
            idempotency_key="send-" + uuid4().hex,
        )

    def claim(self) -> ChatClaim:
        claim = self.execution.claim_next(runtime_id=RUNTIME)
        assert claim is not None
        return claim

    def answer(
        self, claim: ChatClaim, request: ChatTurnInput, *, failed: bool = False
    ) -> ChatTurnResult:
        result = ChatTurnResult(
            conversation_id=claim.conversation_id,
            turn_id=claim.turn_id,
            claim_id=claim.claim_id,
            request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
            status="FAILED" if failed else "SUCCEEDED",
            reply="" if failed else "확인한 답변",
            failure_code="CODEX_TURN_FAILED" if failed else None,
        )
        self.execution.complete(claim, result)
        return result


@pytest.fixture
def chat(tmp_path: Path):
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run guarded testdb_run.sh chat-tests; never point pytest at production")
    state_value = os.environ.get("EOM_GENERAL_CHAT_TEST_STATE")
    if not state_value:
        pytest.fail("chat persistence requires the guarded disposable manifest")
    state = validate_state_directory(Path(state_value))
    manifest = DisposableDatabaseManifest.load(state / "manifest.json")
    url = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert url.username == manifest.owner_role
    assert unquote(url.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == manifest.database
    repository = GeneralChatRepository(engine)
    actors = ("operator_" + uuid4().hex, "operator_" + uuid4().hex)
    with repository.sessions.begin() as session:
        for actor_id in actors:
            session.add(
                OperatorRecord(
                    operator_id=actor_id,
                    username=actor_id,
                    normalized_username=actor_id,
                    display_name="Chat test",
                    status="ACTIVE",
                    must_change_password=False,
                    role_version=1,
                    created_by="disposable-chat-test",
                )
            )
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    publication_engine = create_engine(
        os.environ["EOM_DATABASE_URL"],
        pool_size=2,
        max_overflow=0,
        pool_timeout=5,
        pool_pre_ping=True,
    )
    evidence = GeneralChatArtifactStore(
        engine,
        ControlArtifactPublisher(publication_engine, settings),
        source_commit="a" * 40,
    )
    value = ChatFixture(
        engine,
        repository,
        evidence,
        GeneralChatConversationOwner(repository, evidence),
        GeneralChatExecutionService(repository, evidence),
        actors,
    )
    value.owner.clock = lambda: value.now
    value.execution.clock = lambda: value.now
    value.execution.heartbeat(runtime_id=RUNTIME)
    yield value
    # Finish only this fixture's queued/running synthetic work via the application.
    # No database row repair, no history deletion and no model invocation.
    value.now = NOW
    value.execution.heartbeat(runtime_id=RUNTIME)
    with repository.sessions.begin() as session:
        cap = repository.capacity(session)
        active = (
            None if cap.active_turn_id is None else repository.turn(session, cap.active_turn_id)
        )
    if active is not None:
        assert active.claim_id is not None
        claim = ChatClaim(RUNTIME, active.conversation_id, active.turn_id, active.claim_id)
        request = value.execution.prepare(claim, identity=IDENTITY)
        value.answer(claim, request, failed=True)
    while (claim := value.execution.claim_next(runtime_id=RUNTIME)) is not None:
        value.answer(claim, value.execution.prepare(claim, identity=IDENTITY), failed=True)
    engine.dispose()
    publication_engine.dispose()
