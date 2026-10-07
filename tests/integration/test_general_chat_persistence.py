"""Opt-in, guarded disposable PostgreSQL; synthetic worker results, zero inference."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.general_chat_artifacts import GeneralChatArtifactStore
from eom_orchestrator.general_chat_execution import ChatClaim, GeneralChatExecutionService
from eom_orchestrator.general_chat_models import (
    GeneralChatCapacityRecord,
    GeneralChatConversationRecord,
    GeneralChatTurnRecord,
)
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.settings import Settings
from eom_protocol.general_chat import CHAT_RESULT_SCHEMA, ChatTurnInput, ChatTurnResult
from eom_protocol.general_chat_views import GeneralChatCreate, GeneralChatSubmission
from sqlalchemy import Engine, create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableDatabaseManifest
from scripts.api.testdb_guard import validate_state_directory

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
RUNTIME = "chatrt_" + "a" * 32


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
        request = value.execution.prepare(claim)
        value.answer(claim, request, failed=True)
    while (claim := value.execution.claim_next(runtime_id=RUNTIME)) is not None:
        value.answer(claim, value.execution.prepare(claim), failed=True)
    engine.dispose()
    publication_engine.dispose()


def test_chat_migration_matches_authoritative_metadata(chat: ChatFixture) -> None:
    inspector = inspect(chat.engine)
    for model in (GeneralChatConversationRecord, GeneralChatTurnRecord, GeneralChatCapacityRecord):
        table = model.__table__
        assert tuple(c["name"] for c in inspector.get_columns(table.name, schema="app")) == tuple(
            table.columns.keys()
        )
        assert {c["name"] for c in inspector.get_check_constraints(table.name, schema="app")} == {
            c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
        }
        assert {
            c["name"]
            for c in inspector.get_indexes(table.name, schema="app")
            if not c.get("duplicates_constraint")
        } == {c.name for c in table.indexes}
    with chat.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == "20261007_0048"
        )


def test_concurrent_create_is_single_owner_scoped_receipt(chat: ChatFixture) -> None:
    barrier = Barrier(8)
    request = GeneralChatCreate(title="동시 대화 생성")
    key = "create-" + uuid4().hex

    def invoke():
        barrier.wait(timeout=10)
        return chat.owner.create(actor_id=chat.actors[0], request=request, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = tuple(executor.map(lambda _: invoke(), range(8)))
    assert len({value.conversation_id for value in values}) == 1
    other = chat.owner.create(actor_id=chat.actors[1], request=request, idempotency_key=key)
    assert other.conversation_id != values[0].conversation_id
    with pytest.raises(ChatError, match="IDEMPOTENCY_CONFLICT"):
        chat.owner.create(
            actor_id=chat.actors[0],
            request=GeneralChatCreate(title="다른 내용"),
            idempotency_key=key,
        )


def test_concurrent_identical_submission_replays_after_revision_changes(chat: ChatFixture) -> None:
    conversation = chat.create()
    request = GeneralChatSubmission(text="한 번만 보낼 질문", expected_version=1)
    key = "send-" + uuid4().hex
    barrier = Barrier(8)

    def invoke():
        barrier.wait(timeout=10)
        return chat.owner.submit(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            request=request,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = tuple(executor.map(lambda _: invoke(), range(8)))
    assert len({value.messages[0].turn_id for value in values}) == 1
    claim = chat.claim()
    chat.answer(claim, chat.execution.prepare(claim))
    replay = invoke_without_barrier(chat, conversation.conversation_id, request, key)
    assert replay.messages[0].turn_id == values[0].messages[0].turn_id
    assert replay.messages[1].state == "COMPLETED"


def invoke_without_barrier(chat: ChatFixture, conversation_id: str, request, key: str):
    return chat.owner.submit(
        actor_id=chat.actors[0],
        conversation_id=conversation_id,
        request=request,
        idempotency_key=key,
    )


def test_distinct_concurrent_intents_do_not_generate_second_active_turn(chat: ChatFixture) -> None:
    conversation = chat.create()
    barrier = Barrier(6)

    def invoke(index: int):
        barrier.wait(timeout=10)
        try:
            return chat.owner.submit(
                actor_id=chat.actors[0],
                conversation_id=conversation.conversation_id,
                request=GeneralChatSubmission(text=f"질문 {index}", expected_version=1),
                idempotency_key="send-" + uuid4().hex,
            )
        except ChatError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=6) as executor:
        values = tuple(executor.map(invoke, range(6)))
    assert sum(not isinstance(value, str) for value in values) == 1
    assert set(value for value in values if isinstance(value, str)) == {
        "GENERAL_CHAT_STALE_REVISION"
    }


def test_owner_denial_and_stale_revision_publish_no_artifacts(chat: ChatFixture) -> None:
    conversation = chat.create()
    with chat.engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM artifact_revisions"))
    with pytest.raises(ChatError, match="NOT_FOUND"):
        chat.owner.conversation(
            actor_id=chat.actors[1], conversation_id=conversation.conversation_id, cursor=None
        )
    with pytest.raises(ChatError, match="NOT_FOUND"):
        chat.owner.submit(
            actor_id=chat.actors[1],
            conversation_id=conversation.conversation_id,
            request=GeneralChatSubmission(text="침입", expected_version=1),
            idempotency_key="send-" + uuid4().hex,
        )
    with pytest.raises(ChatError, match="STALE_REVISION"):
        chat.owner.submit(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            request=GeneralChatSubmission(text="오래된 버전", expected_version=2),
            idempotency_key="send-" + uuid4().hex,
        )
    with chat.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM artifact_revisions")) == before


def test_atomic_dedicated_claims_do_not_touch_existing_six_slots(chat: ChatFixture) -> None:
    with chat.repository.sessions.begin() as session:
        for index in range(1, 7):
            slot_id = f"{index:02d}"
            if session.get(WorkerSlotRecord, slot_id) is None:
                session.add(
                    WorkerSlotRecord(
                        slot_id=slot_id,
                        linux_user=f"chat-fixture-cdx{slot_id}",
                        role="authoring",
                        enabled=True,
                        gpu=False,
                    )
                )
    with chat.engine.connect() as connection:
        baseline = tuple(
            connection.execute(
                text("SELECT slot_id, enabled FROM worker_slots ORDER BY slot_id")
            ).all()
        )
        leases = connection.scalar(text("SELECT count(*) FROM worker_leases"))
    first, second = chat.create(), chat.create(actor=1)
    chat.submit(first, message="첫 사용자 전용 질문")
    chat.now += timedelta(microseconds=1)
    chat.submit(second, actor=1, message="둘째 사용자 전용 질문")
    barrier = Barrier(8)

    def invoke(_):
        barrier.wait(timeout=10)
        return chat.execution.claim_next(runtime_id=RUNTIME)

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = tuple(executor.map(invoke, range(8)))
    claims = tuple(value for value in values if value is not None)
    assert len(claims) == 1
    claim = claims[0]
    request = chat.execution.prepare(claim)
    assert request.messages[-1].text == "첫 사용자 전용 질문"
    assert chat.owner.slot().state == "BUSY"
    chat.answer(claim, request)
    other = chat.claim()
    other_request = chat.execution.prepare(other)
    assert [m.text for m in other_request.messages] == ["둘째 사용자 전용 질문"]
    chat.answer(other, other_request)
    assert chat.owner.slot().state == "READY"
    with chat.engine.connect() as connection:
        assert (
            tuple(
                connection.execute(
                    text("SELECT slot_id, enabled FROM worker_slots ORDER BY slot_id")
                ).all()
            )
            == baseline
        )
        assert connection.scalar(text("SELECT count(*) FROM worker_leases")) == leases


def test_concurrent_completion_is_idempotent_and_context_pins_previous_answer(
    chat: ChatFixture,
) -> None:
    conversation = chat.submit(chat.create(), message="첫 질문")
    claim = chat.claim()
    request = chat.execution.prepare(claim)
    assert chat.execution.prepare(claim) == request
    result = ChatTurnResult(
        conversation_id=claim.conversation_id,
        turn_id=claim.turn_id,
        claim_id=claim.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        status="SUCCEEDED",
        reply="확인한 답변",
        failure_code=None,
    )
    barrier = Barrier(6)

    def finish(_):
        barrier.wait(timeout=10)
        return chat.execution.complete(claim, result)

    with ThreadPoolExecutor(max_workers=6) as executor:
        tuple(executor.map(finish, range(6)))
    latest = chat.owner.conversation(
        actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
    )
    assert [m.text for m in latest.messages] == ["첫 질문", "확인한 답변"]
    chat.submit(latest, message="그 답변 이어서 설명해줘")
    second = chat.claim()
    second_request = chat.execution.prepare(second)
    assert [m.text for m in second_request.messages] == [
        "첫 질문",
        "확인한 답변",
        "그 답변 이어서 설명해줘",
    ]
    chat.answer(second, second_request)
    with chat.repository.sessions.begin() as session:
        count = session.scalar(
            select(func.count())
            .select_from(GeneralChatTurnRecord)
            .where(
                GeneralChatTurnRecord.conversation_id == conversation.conversation_id,
            )
        )
        assert count == 2


def test_stale_claim_invalid_result_and_terminal_mutation_are_rejected(chat: ChatFixture) -> None:
    conversation = chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim)
    forged = ChatClaim(RUNTIME, claim.conversation_id, claim.turn_id, "chatclaim_" + "b" * 32)
    with pytest.raises(ChatError, match="CLAIM_MISMATCH"):
        chat.execution.prepare(forged)
    result = chat.answer(claim, request)
    with pytest.raises(ChatError, match="RESULT_CONFLICT"):
        chat.execution.complete(claim, result.model_copy(update={"reply": "다른 답변"}))
    with pytest.raises(IntegrityError), chat.engine.begin() as connection:
        connection.execute(
            text("UPDATE general_chat_turns SET state = 'QUEUED' WHERE turn_id = :id"),
            {"id": claim.turn_id},
        )
    with pytest.raises(IntegrityError), chat.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE general_chat_conversations SET owner_id = :owner "
                "WHERE conversation_id = :id"
            ),
            {"owner": chat.actors[1], "id": conversation.conversation_id},
        )


def test_commit_failure_resumes_same_evidence_without_reinvoking_worker(
    chat: ChatFixture, monkeypatch
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim)
    original = chat.evidence.publish

    def interrupted(**kwargs: Any):
        if kwargs["schema_ref"] == CHAT_RESULT_SCHEMA:
            raise OSError("isolated simulated publication interruption")
        return original(**kwargs)

    monkeypatch.setattr(chat.evidence, "publish", interrupted)
    with pytest.raises(OSError, match="interruption"):
        chat.answer(claim, request)
    with chat.repository.sessions.begin() as session:
        assert chat.repository.turn(session, claim.turn_id).state == "COMMITTING"
    monkeypatch.setattr(chat.evidence, "publish", original)
    chat.answer(claim, request)
    assert chat.owner.slot().state == "READY"


def test_failed_worker_history_is_retained_without_partial_answer(chat: ChatFixture) -> None:
    conversation = chat.submit(chat.create())
    claim = chat.claim()
    result = chat.answer(claim, chat.execution.prepare(claim), failed=True)
    chat.execution.complete(claim, result)
    latest = chat.owner.conversation(
        actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
    )
    assert latest.messages[1].state == "FAILED" and latest.messages[1].text == ""
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.output_artifact_id is not None and turn.failure_code == "CODEX_TURN_FAILED"


def test_competing_success_and_failure_pin_one_result_before_publication(chat: ChatFixture) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim)
    success = ChatTurnResult(
        conversation_id=claim.conversation_id,
        turn_id=claim.turn_id,
        claim_id=claim.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        status="SUCCEEDED",
        reply="경합 답변",
        failure_code=None,
    )
    failed = success.model_copy(
        update={"status": "FAILED", "reply": "", "failure_code": "CODEX_TIMEOUT"}
    )
    barrier = Barrier(8)

    def finish(index: int):
        value = success if index % 2 else failed
        barrier.wait(timeout=10)
        try:
            chat.execution.complete(claim, value)
            return value.status
        except ChatError as error:
            assert error.code == "GENERAL_CHAT_RESULT_CONFLICT"
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = tuple(executor.map(finish, range(8)))
    winners = set(statuses) - {"CONFLICT"}
    assert len(winners) == 1 and statuses.count("CONFLICT") == 4
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.result_status in winners
        assert turn.output_sha256 == turn.result_sha256
    assert chat.owner.slot().state == "READY"


def test_expiry_is_unavailable_and_never_automatically_reclaims_unknown_execution(
    chat: ChatFixture,
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim)
    chat.now = NOW + timedelta(minutes=31)
    assert chat.owner.slot().state == "UNAVAILABLE"
    with pytest.raises(ChatError, match="RECONCILIATION_REQUIRED"):
        chat.execution.heartbeat(runtime_id="chatrt_" + "b" * 32)
    chat.execution.heartbeat(runtime_id=RUNTIME)
    with pytest.raises(ChatError, match="RECONCILIATION_REQUIRED"):
        chat.execution.claim_next(runtime_id=RUNTIME)
    # Return the synthetic clock to its baseline solely to finish this test's work.
    chat.now = NOW
    chat.answer(claim, request)


def test_chat_body_never_enters_database_metadata(chat: ChatFixture) -> None:
    secret_text = "DB에 복제하지 않는 대화-" + uuid4().hex
    conversation = chat.submit(chat.create(), message=secret_text)
    claim = chat.claim()
    chat.answer(claim, chat.execution.prepare(claim))
    with chat.engine.connect() as connection:
        for table in (
            "general_chat_conversations",
            "general_chat_turns",
            "jobs",
            "artifact_revisions",
        ):
            rows = (
                connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t"))
                .scalars()
                .all()
            )
            assert all(secret_text not in row for row in rows)
    assert (
        chat.owner.conversation(
            actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
        )
        .messages[0]
        .text
        == secret_text
    )


def test_conversation_pagination_is_bounded_and_owner_scoped(chat: ChatFixture) -> None:
    for _ in range(51):
        chat.create()
    chat.create(actor=1)
    first = chat.owner.conversations(actor_id=chat.actors[0], cursor=None)
    assert len(first.values) == 50 and first.has_more and first.next_cursor
    second = chat.owner.conversations(actor_id=chat.actors[0], cursor=first.next_cursor)
    assert len(second.values) == 1 and not second.has_more
    assert not {value.conversation_id for value in first.values} & {
        value.conversation_id for value in second.values
    }
    with pytest.raises(ChatError, match="CURSOR_INVALID"):
        chat.owner.conversations(actor_id=chat.actors[1], cursor=first.next_cursor)


def test_context_budget_drops_only_complete_old_exchanges(chat: ChatFixture) -> None:
    conversation = chat.create()
    for index in range(4):
        chat.submit(conversation, message=f"{index}:" + "한" * 15900)
        claim = chat.claim()
        request = chat.execution.prepare(claim)
        result = ChatTurnResult(
            conversation_id=claim.conversation_id,
            turn_id=claim.turn_id,
            claim_id=claim.claim_id,
            request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
            status="SUCCEEDED",
            reply="답" * 31900,
            failure_code=None,
        )
        chat.execution.complete(claim, result)
        conversation = chat.owner.conversation(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            cursor=None,
        )
        assert (
            len(canonical_json_bytes([value.model_dump() for value in request.messages])) <= 128000
        )
        assert request.messages[0].role == request.messages[-1].role == "user"
        assert len(request.messages) % 2 == 1
        assert request.messages[-1].text.startswith(f"{index}:")
    assert len(request.messages) < 7


def test_corrupted_artifact_bytes_fail_closed_at_owner_projection(
    chat: ChatFixture, monkeypatch
) -> None:
    conversation = chat.submit(chat.create())
    original = chat.evidence.read
    monkeypatch.setattr(chat.evidence, "read", lambda pointers: tuple(b"{}" for _ in pointers))
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        chat.owner.conversation(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            cursor=None,
        )
    monkeypatch.setattr(chat.evidence, "read", original)


def test_database_constraint_rejects_second_active_turn_even_without_application_guard(
    chat: ChatFixture,
) -> None:
    conversation = chat.submit(chat.create())
    with chat.repository.sessions.begin() as session:
        original = chat.repository.history(session, conversation.conversation_id, limit=1)[0]
    with (
        pytest.raises(IntegrityError, match="uq_chat_one_active"),
        chat.repository.sessions.begin() as session,
    ):
        session.add(
            GeneralChatTurnRecord(
                turn_id="chatturn_" + uuid4().hex,
                conversation_id=conversation.conversation_id,
                user_sequence=3,
                expected_version=conversation.resource_version,
                submission_key_sha256="sha256:" + "b" * 64,
                submission_request_sha256="sha256:" + "c" * 64,
                state="QUEUED",
                input_artifact_id=original.input_artifact_id,
                input_revision_id=original.input_revision_id,
                input_sha256=original.input_sha256,
                created_at=NOW,
            )
        )


def test_saturated_metadata_pool_does_not_block_canonical_publication(chat: ChatFixture) -> None:
    # More intents than the default metadata pool's 15 connections. Each blocks
    # on its indexed transaction lock; publication still has two reserved connections.
    conversations = tuple(chat.create() for _ in range(20))
    barrier = Barrier(20)

    def submit(index: int):
        barrier.wait(timeout=10)
        return chat.submit(conversations[index])

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = tuple(executor.submit(submit, index) for index in range(20))
        values = tuple(future.result(timeout=15) for future in futures)
    assert len({value.messages[0].turn_id for value in values}) == 20
