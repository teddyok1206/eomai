"""Opt-in, guarded disposable PostgreSQL; synthetic worker results, zero inference."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Any
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_client import GeneralChatOwnerClient
from eom_orchestrator.general_chat_coordinator import run_chat_coordinator
from eom_orchestrator.general_chat_execution import ChatClaim, GeneralChatExecutionService
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_models import (
    GeneralChatCapacityRecord,
    GeneralChatConversationRecord,
    GeneralChatTurnRecord,
)
from eom_orchestrator.general_chat_owner_runtime import require_chat_owner_database
from eom_orchestrator.general_chat_owner_server import GeneralChatOwnerRpcServer
from eom_orchestrator.general_chat_recovery import recover_known_chat_turn
from eom_orchestrator.general_chat_resident import GeneralChatResident
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_orchestrator.models import WorkerSlotRecord
from eom_protocol.general_chat import CHAT_RESULT_SCHEMA, ChatTurnInput, ChatTurnResult
from eom_protocol.general_chat_dispatch import CHAT_DISPATCH_SCHEMA, ChatExecutionIdentity
from eom_protocol.general_chat_owner_messages import ChatOwnerErrorCode, ChatOwnerFault
from eom_protocol.general_chat_views import GeneralChatCreate, GeneralChatSubmission
from eom_protocol.general_chat_worker_messages import chat_worker_ticket
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.general_chat_fixtures import IDENTITY, NOW, RUNTIME, ChatFixture
from tests.unit.test_general_chat_worker_handoff import BOOT, SyntheticNative, policy

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class SyntheticKnowledge:
    """Typed source port only; these are not Catalog/Graph provenance acceptance tests."""

    denied = False

    def resolve(self, *, actor_id, selection, purpose):
        from eom_protocol.general_chat_grounding import ChatKnowledgeCatalogReply

        from tests.unit.test_general_chat_grounding_contract import context

        if self.denied:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")
        return ChatKnowledgeCatalogReply(
            status="SUCCEEDED",
            context=context() if selection is not None and purpose == "MATERIALIZE" else None,
            agent_state=None,
            error_code=None,
        )


class AgentKnowledge(SyntheticKnowledge):
    def __init__(self):
        self.selections = []

    def search(self, **values):
        from tests.unit.test_general_chat_agent_search import Knowledge

        if self.denied:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")
        return Knowledge().outcome

    def resolve(self, *, actor_id, selection, purpose):
        self.selections.append((purpose, selection))
        return super().resolve(actor_id=actor_id, selection=selection, purpose=purpose)


def test_agent_tools_persist_once_and_followup_reuses_exact_pinned_context(chat):
    from eom_orchestrator.general_chat_agent_native import NativeChatTools
    from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
    from eom_protocol.general_chat_grounding import AgentChatTurnInput, validate_agent_citations
    from eom_protocol.general_chat_tools import ChatToolRequest
    from eom_protocol.general_chat_worker_messages import ChatWorkerExecute, ChatWorkerRequest

    from tests.unit.test_general_chat_agent_search import arguments, read_command
    from tests.unit.test_general_chat_grounding_contract import context, result

    knowledge = AgentKnowledge()
    chat.owner.knowledge = chat.execution.knowledge = knowledge
    identity = ChatExecutionIdentity(
        boot_id=BOOT, policy=source_chat_worker_policy(model="synthetic-model")
    )
    conversation = chat.create()
    chat.submit(conversation)
    claim = chat.claim()
    prepared = chat.execution.prepare(claim, identity=identity)
    assert isinstance(prepared, AgentChatTurnInput) and prepared.knowledge is None
    envelope = ChatWorkerRequest(
        schema_version="general-chat-worker-request/3.0",
        request_id="chatwrpc_" + uuid4().hex,
        policy_sha256=identity.policy.sha256,
        command=ChatWorkerExecute(boot_id=identity.boot_id, turn=prepared),
    )
    broker = chat.execution.tool_broker(envelope)

    class Port:
        sequence = 0

        def call(self, command):
            self.sequence += 1
            return broker.execute(
                ChatToolRequest(
                    rpc_request_id=envelope.request_id,
                    ticket=chat_worker_ticket(prepared, policy_sha256=identity.policy.sha256),
                    sequence=self.sequence,
                    command=command,
                )
            )

    tools = NativeChatTools(prepared, Port())
    tools.call("search_eom_items", arguments().model_dump(mode="json"))
    tools.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
    answer = tools.result(
        reply=canonical_json_bytes(result().answer.model_dump(mode="json")).decode(), failure=None
    )
    assert len(answer.tool_records) == 2
    chat.execution.complete(claim, answer)
    chat.execution.complete(claim, answer)
    assert chat.execution.active_claim() is None
    assert chat.execution.execution_receipt(claim).schema_version == "general-chat-dispatch/3.0"
    view = chat.owner.conversation(
        actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
    )
    assert view.messages[-1].text == answer.reply
    grounding = chat.owner.grounding(
        actor_id=chat.actors[0],
        conversation_id=conversation.conversation_id,
        turn_ids=(claim.turn_id,),
    )
    assert grounding.values[0].receipt.used_source_keys == ("S1",)
    assert grounding.values[0].sources[0].item == context().sources[0].item
    assert any(purpose == "AUTHORIZE" for purpose, _ in knowledge.selections)
    with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_FOUND"):
        chat.owner.conversation(
            actor_id=chat.actors[1], conversation_id=conversation.conversation_id, cursor=None
        )
    chat.submit(view, message="그 문항의 후속 질문")
    next_claim = chat.claim()
    following = chat.execution.prepare(next_claim, identity=identity)
    assert isinstance(following, AgentChatTurnInput)
    assert following.knowledge.selection == context().selection
    assert any(message.text == answer.reply for message in following.messages)
    no_new_tools = NativeChatTools(following, Port())
    next_answer = no_new_tools.result(
        reply=canonical_json_bytes(result().answer.model_dump(mode="json")).decode(), failure=None
    )
    assert next_answer.tool_records == ()
    validate_agent_citations(following, next_answer, following.knowledge)
    chat.execution.complete(next_claim, next_answer)
    knowledge.denied = True
    with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
        chat.owner.conversation(
            actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
        )


def grounded_identity():
    from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
    from eom_protocol.general_chat_worker_messages import read_chat_worker_policy

    historical = source_chat_worker_policy(model="synthetic-model").model_dump(
        mode="json", exclude={"agent_prompt_sha256"}
    )
    historical["schema_version"] = "general-chat-worker-policy/2.0"
    return ChatExecutionIdentity(boot_id=BOOT, policy=read_chat_worker_policy(historical))


def finish_grounded(chat, claim, request):
    import json

    from eom_orchestrator.general_chat_grounded_prompt import grounded_chat_result

    answer = {
        "answer_sections": [
            {
                "section_id": "section_1",
                "markdown": "합성 검증 답변",
                "support_kind": "SOURCE_SUPPORTED" if request.knowledge else "GENERAL_KNOWLEDGE",
                "citation_keys": ["S1"] if request.knowledge else [],
            }
        ],
        "limitations": [],
    }
    result = grounded_chat_result(request, reply=json.dumps(answer), failure=None)
    chat.execution.complete(claim, result)
    return result


@pytest.mark.parametrize("grounded", [False, True])
def test_successor_artifacts_dispatch_history_and_source_views_are_exact(chat, grounded):
    from eom_protocol.general_chat_grounding import GroundedChatSubmission

    from tests.unit.test_general_chat_grounding_contract import context

    knowledge = SyntheticKnowledge()
    chat.owner.knowledge = chat.execution.knowledge = knowledge
    conversation = chat.create()
    sent = chat.owner.submit(
        actor_id=chat.actors[0],
        conversation_id=conversation.conversation_id,
        request=GroundedChatSubmission(
            text="합성 질문",
            expected_version=conversation.resource_version,
            selection=context().selection if grounded else None,
        ),
        idempotency_key="grounded-" + uuid4().hex,
    )
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=grounded_identity())
    assert request.protocol_version == "general-chat-turn/2.0"
    assert (request.knowledge is not None) == grounded
    result = finish_grounded(chat, claim, request)
    assert chat.execution.execution_receipt(claim).schema_version == "general-chat-dispatch/2.0"
    assert chat.execution.active_claim() is None
    chat.execution.complete(claim, result)
    view = chat.owner.grounding(
        actor_id=chat.actors[0], conversation_id=sent.conversation_id, turn_ids=(claim.turn_id,)
    )
    assert view.values[0].receipt.request_sha256 == result.request_sha256
    assert len(view.values[0].sources) == int(grounded)
    assert (
        chat.owner.conversation(
            actor_id=chat.actors[0], conversation_id=sent.conversation_id, cursor=None
        )
        .messages[-1]
        .text
        == result.reply
    )
    if grounded:
        knowledge.denied = True
        with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
            chat.owner.conversation(
                actor_id=chat.actors[0], conversation_id=sent.conversation_id, cursor=None
            )
        with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
            chat.owner.grounding(
                actor_id=chat.actors[0],
                conversation_id=sent.conversation_id,
                turn_ids=(claim.turn_id,),
            )


def test_denied_preparation_terminates_exact_claim_without_model_or_dispatch(chat):
    from eom_orchestrator.general_chat_execution import ChatPreparationRejected

    chat.execution.knowledge = SyntheticKnowledge()
    conversation = chat.create()
    chat.submit(conversation)
    claim = chat.claim()
    chat.execution.knowledge.denied = True
    with pytest.raises(ChatPreparationRejected, match="GENERAL_CHAT_FORBIDDEN"):
        chat.execution.prepare(claim, identity=grounded_identity())
    assert chat.execution.active_claim() is None
    with chat.repository.read_snapshot() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "FAILED" and turn.failure_code == "GENERAL_CHAT_FORBIDDEN"
        assert (
            turn.request_artifact_id is turn.dispatch_artifact_id is turn.output_artifact_id is None
        )


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
            == "20261008_0049"
        )


@pytest.fixture
def chat_rpc(chat: ChatFixture, tmp_path: Path):
    directory = tmp_path / "rpc"
    directory.mkdir(mode=0o750)
    # The guarded DB runner uses umask077; the RPC parent has its own exact mode.
    directory.chmod(0o750)
    endpoint = ChatSocketEndpoint(directory / "owner.sock", os.getuid(), os.getgid())
    with GeneralChatOwnerRpcServer(
        chat.owner, endpoint=endpoint, allowed_uids=frozenset({os.getuid()})
    ) as server:
        thread = Thread(target=server.serve)
        thread.start()
        try:
            yield GeneralChatOwnerClient(endpoint)
        finally:
            server.stop()
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_private_rpc_concurrent_replay_preserves_one_database_intent_and_claim(
    chat: ChatFixture, chat_rpc: GeneralChatOwnerClient
) -> None:
    request = GeneralChatCreate(title="RPC 동시 요청")
    key = "create-rpc-" + uuid4().hex

    def create(_):
        return chat_rpc.create(actor_id=chat.actors[0], request=request, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = tuple(pool.map(create, range(8)))
    assert len({value.conversation_id for value in values}) == 1
    conversation = values[0]
    submission = GeneralChatSubmission(text="동일한 질문", expected_version=1)
    submit_key = "submit-rpc-" + uuid4().hex

    def submit(_):
        return chat_rpc.submit(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            request=submission,
            idempotency_key=submit_key,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = tuple(pool.map(submit, range(8)))
    assert len({message.turn_id for value in responses for message in value.messages}) == 1
    claim = chat.claim()
    assert chat.execution.claim_next(runtime_id=RUNTIME) is None
    prepared = chat.execution.prepare(claim, identity=IDENTITY)
    chat.answer(claim, prepared)
    replay = submit(None)
    assert tuple(value.role for value in replay.messages) == ("user", "assistant")
    assert replay.messages[-1].state == "COMPLETED"
    assert chat.execution.claim_next(runtime_id=RUNTIME) is None


def test_private_rpc_two_owners_use_separate_history_and_same_intent_scope(
    chat: ChatFixture, chat_rpc: GeneralChatOwnerClient
) -> None:
    key = "owner-rpc-" + uuid4().hex
    request = GeneralChatCreate(title="동일 제목")
    a, b = tuple(
        chat_rpc.create(actor_id=actor, request=request, idempotency_key=key)
        for actor in chat.actors
    )
    assert a.conversation_id != b.conversation_id
    for actor, own, foreign in ((chat.actors[0], a, b), (chat.actors[1], b, a)):
        listing = chat_rpc.conversations(actor_id=actor, cursor=None)
        assert {value.conversation_id for value in listing.values} == {own.conversation_id}
        with pytest.raises(ChatOwnerFault) as failure:
            chat_rpc.conversation(
                actor_id=actor, conversation_id=foreign.conversation_id, cursor=None
            )
        assert failure.value.code == ChatOwnerErrorCode.NOT_FOUND


def test_resident_processes_two_authenticated_owners_without_shared_history(
    chat: ChatFixture, chat_rpc: GeneralChatOwnerClient
) -> None:
    conversations = (chat.create(), chat.create(actor=1))
    for index, conversation in enumerate(conversations):
        chat.submit(conversation, actor=index, message=f"owner-{index}-private-question")
        # Equal timestamps intentionally sort by turn ID; use distinct instants
        # when asserting chronological FIFO rather than random identity order.
        chat.now += timedelta(microseconds=1)
    stop = Event()

    class SyntheticWorker:
        execution_identity = IDENTITY

        def __init__(self) -> None:
            self.requests: list[ChatTurnInput] = []

        def check_admission(self) -> None:
            pass

        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            self.requests.append(request)
            if len(self.requests) == 2:
                stop.set()
            return ChatTurnResult(
                conversation_id=request.conversation_id,
                turn_id=request.turn_id,
                claim_id=request.claim_id,
                request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
                status="SUCCEEDED",
                reply=f"synthetic reply to {request.messages[-1].text}",
                failure_code=None,
            )

    worker = SyntheticWorker()
    GeneralChatResident(chat.execution, worker, runtime_id=RUNTIME).run(stop)
    assert len(worker.requests) == 2
    assert all(len(request.messages) == 1 for request in worker.requests)
    assert tuple(request.messages[0].text for request in worker.requests) == (
        "owner-0-private-question",
        "owner-1-private-question",
    )
    for index, conversation in enumerate(conversations):
        view = chat_rpc.conversation(
            actor_id=chat.actors[index], conversation_id=conversation.conversation_id, cursor=None
        )
        assert tuple(message.role for message in view.messages) == ("user", "assistant")
        assert all(f"owner-{index}-private-question" in message.text for message in view.messages)
        with pytest.raises(ChatOwnerFault) as failure:
            chat_rpc.conversation(
                actor_id=chat.actors[1 - index],
                conversation_id=conversation.conversation_id,
                cursor=None,
            )
        assert failure.value.code == ChatOwnerErrorCode.NOT_FOUND
    assert chat.owner.slot().state == "UNAVAILABLE"
    with chat.repository.sessions.begin() as session:
        assert chat.repository.capacity(session).active_turn_id is None


@pytest.fixture
def chat_worker_rpc(chat: ChatFixture, tmp_path: Path):
    workspace, runtime = tmp_path / "worker-local-handoff", tmp_path / "worker-rpc"
    workspace.mkdir(mode=0o700)
    workspace.chmod(0o700)
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    native = SyntheticNative()
    endpoint = ChatSocketEndpoint(runtime / "worker.sock", os.getuid(), os.getgid())
    with ChatLocalHandoff(workspace, worker_uid=os.getuid()) as local:
        application = ChatWorkerApplication(native, local, policy=policy(), boot_id=BOOT)
        with ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid()) as server:
            thread = Thread(target=server.serve)
            thread.start()
            try:
                yield ChatWorkerClient(endpoint=endpoint, policy=policy()), native, local
            finally:
                server.stop()
                thread.join(2)
                assert not thread.is_alive()


def test_resident_database_private_worker_and_artifact_commit_are_owner_separated(
    chat: ChatFixture, chat_worker_rpc
) -> None:
    worker, native, local = chat_worker_rpc
    a, b = chat.create(), chat.create(actor=1)
    chat.submit(a, message="private-a")
    chat.now += timedelta(microseconds=1)
    chat.submit(b, actor=1, message="private-b")
    stop = Event()
    original = native.answer

    def synthetic_answer(request):
        result = original(request)
        if len(native.calls) == 2:
            stop.set()
        return result

    native.answer = synthetic_answer
    GeneralChatResident(chat.execution, worker, runtime_id=RUNTIME).run(stop)
    assert len(native.calls) == 2
    assert tuple(request.messages[0].text for request in native.calls) == ("private-a", "private-b")
    assert all(len(request.messages) == 1 for request in native.calls)
    for index, conversation in enumerate((a, b)):
        view = chat.owner.conversation(
            actor_id=chat.actors[index], conversation_id=conversation.conversation_id, cursor=None
        )
        assert tuple(message.role for message in view.messages) == ("user", "assistant")
        assert view.messages[-1].state == "COMPLETED"
        ticket = chat_worker_ticket(native.calls[index], policy_sha256=policy().sha256)
        assert local.lookup(ticket).state == "KNOWN"
    assert chat.owner.slot().state == "UNAVAILABLE"
    with chat.repository.sessions.begin() as session:
        assert chat.repository.capacity(session).active_turn_id is None


def test_coordinator_runs_two_owners_through_existing_fifo_and_exact_boot(chat, chat_worker_rpc):
    worker, native, _ = chat_worker_rpc
    a, b = chat.create(), chat.create(actor=1)
    chat.submit(a, message="private-coordinator-a")
    chat.now += timedelta(microseconds=1)
    chat.submit(b, actor=1, message="private-coordinator-b")
    chat.execution.withdraw(runtime_id=RUNTIME)
    stop = Event()
    original = native.answer

    def synthetic_answer(request):
        result = original(request)
        if len(native.calls) == 2:
            stop.set()
        return result

    native.answer = synthetic_answer
    reports = []
    run_chat_coordinator(chat.execution, lambda: worker, stop=stop, report_state=reports.append)
    assert not reports and len(native.calls) == 2
    assert tuple(value.messages[0].text for value in native.calls) == (
        "private-coordinator-a",
        "private-coordinator-b",
    )
    with chat.repository.read_snapshot() as session:
        cap = chat.repository.capacity(session)
        assert cap.runtime_id != RUNTIME and cap.active_turn_id is None
        for request in native.calls:
            turn = chat.repository.turn(session, request.turn_id)
            assert turn.state == "COMPLETED"
            receipt = chat.execution.execution_receipt(
                ChatClaim(
                    cap.runtime_id,
                    request.conversation_id,
                    request.turn_id,
                    request.claim_id,
                )
            )
            assert receipt.identity == IDENTITY
    assert chat.owner.slot().state == "UNAVAILABLE"


def test_coordinator_recovers_known_private_result_before_admitting_new_boot(chat, chat_worker_rpc):
    worker, native, _ = chat_worker_rpc
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    worker.check_admission()
    expected = worker.answer(request)
    chat.execution.withdraw(runtime_id=RUNTIME)
    stop = Event()

    class LookupOnly:
        def lookup(self, ticket):
            value = worker.lookup(ticket)
            stop.set()
            return value

        def check_admission(self):
            pytest.fail("recovery must not readmit or invoke native")

    run_chat_coordinator(chat.execution, LookupOnly, stop=stop, report_state=lambda _: None)
    assert len(native.calls) == 1
    with chat.repository.read_snapshot() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "COMPLETED"
        assert turn.output_sha256 == sha256_bytes(
            canonical_json_bytes(expected.model_dump(mode="json"))
        )
        assert chat.repository.capacity(session).active_turn_id is None


def test_actual_postgres_owner_admission_rejects_broad_disposable_owner_role(chat):
    # Exercises the actual SQL privilege functions/schema head without granting
    # rights, creating a runtime role or touching production credentials.
    with pytest.raises(ChatError, match="GENERAL_CHAT_OWNER_DATABASE_NOT_READY"):
        require_chat_owner_database(chat.engine)


def test_lost_worker_reply_recovers_exact_known_result_without_another_model_call(
    chat: ChatFixture, chat_worker_rpc, monkeypatch
) -> None:
    worker, native, local = chat_worker_rpc
    conversation = chat.create()
    chat.submit(conversation)
    from eom_orchestrator import general_chat_worker_client as transport

    original = transport.exchange_chat_frame

    def lose_reply(endpoint, document, **kwargs):
        reply = original(endpoint, document, **kwargs)
        if document["command"]["action"] == "EXECUTE":
            raise ChatTransportError("UNAVAILABLE")
        return reply

    monkeypatch.setattr(transport, "exchange_chat_frame", lose_reply)
    with pytest.raises(ChatError, match="GENERAL_CHAT_RECONCILIATION_REQUIRED"):
        GeneralChatResident(chat.execution, worker, runtime_id=RUNTIME).run(Event())
    assert len(native.calls) == 1 and chat.owner.slot().state == "UNAVAILABLE"
    with chat.repository.sessions.begin() as session:
        capacity = chat.repository.capacity(session)
        turn = chat.repository.turn(session, capacity.active_turn_id)
        assert turn.state == "RUNNING" and turn.output_artifact_id is None
        claim = ChatClaim(RUNTIME, turn.conversation_id, turn.turn_id, turn.claim_id)
    request = chat.execution.prepare(claim, identity=IDENTITY)
    ticket = chat_worker_ticket(request, policy_sha256=policy().sha256)
    output = worker.lookup(ticket)
    assert output == local.lookup(ticket) and output.result is not None
    # Supported exact-claim admission while the original lease is still valid;
    # this does not claim automatic expired-claim takeover or policy provenance.
    chat.execution.complete(claim, output.result)
    chat.execution.complete(claim, output.result)
    assert len(native.calls) == 1
    view = chat.owner.conversation(
        actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
    )
    assert view.messages[-1].state == "COMPLETED"


def test_withdrawal_preserves_unknown_active_claim_and_request_evidence(chat: ChatFixture) -> None:
    conversation = chat.create()
    chat.submit(conversation)
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    with chat.repository.sessions.begin() as session:
        capacity = chat.repository.capacity(session)
        expected = (
            capacity.runtime_id,
            capacity.active_turn_id,
            capacity.claim_id,
            capacity.expires_at,
        )
        turn = chat.repository.turn(session, claim.turn_id)
        request_pointer = (turn.request_artifact_id, turn.request_revision_id, turn.request_sha256)
    assert chat.execution.withdraw(runtime_id=RUNTIME)
    assert chat.owner.slot().state == "UNAVAILABLE"
    with chat.repository.sessions.begin() as session:
        capacity = chat.repository.capacity(session)
        assert (
            capacity.runtime_id,
            capacity.active_turn_id,
            capacity.claim_id,
            capacity.expires_at,
        ) == expected
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "RUNNING" and turn.output_artifact_id is None
        assert (
            turn.request_artifact_id,
            turn.request_revision_id,
            turn.request_sha256,
        ) == request_pointer
    with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_READY"):
        chat.execution.claim_next(runtime_id=RUNTIME)
    # Exact known-result admission is still possible; withdrawal did not release the lease.
    chat.answer(claim, request)
    assert (
        chat.owner.conversation(
            actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
        )
        .messages[-1]
        .state
        == "COMPLETED"
    )


def test_another_runtime_cannot_withdraw_current_capacity(chat: ChatFixture) -> None:
    assert not chat.execution.withdraw(runtime_id="chatrt_" + "b" * 32)
    assert chat.owner.slot().state == "READY"
    with chat.repository.sessions.begin() as session:
        capacity = chat.repository.capacity(session)
        assert capacity.runtime_id == RUNTIME and capacity.heartbeat_at == chat.now
    with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_INVALID"):
        chat.execution.withdraw(runtime_id="caller supplied invalid identity")


def test_new_resident_does_not_reclaim_or_regenerate_existing_unknown_turn(
    chat: ChatFixture,
) -> None:
    conversation = chat.create()
    chat.submit(conversation)
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    assert chat.execution.withdraw(runtime_id=RUNTIME)

    class NeverDispatch:
        execution_identity = IDENTITY

        def check_admission(self) -> None:
            pass

        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            raise AssertionError("reconciliation must not run a model")

    with pytest.raises(ChatError, match="GENERAL_CHAT_RECONCILIATION_REQUIRED"):
        GeneralChatResident(chat.execution, NeverDispatch(), runtime_id="chatrt_" + "b" * 32).run(
            Event()
        )
    with chat.repository.sessions.begin() as session:
        capacity = chat.repository.capacity(session)
        assert capacity.runtime_id == RUNTIME and capacity.active_turn_id == claim.turn_id
        assert chat.repository.turn(session, claim.turn_id).state == "RUNNING"
    chat.answer(claim, request)


def test_private_rpc_expired_heartbeat_blocks_fresh_submit_but_retains_history_and_replay(
    chat: ChatFixture, chat_rpc: GeneralChatOwnerClient
) -> None:
    conversation = chat.create()
    request = GeneralChatSubmission(text="확정된 질문", expected_version=1)
    key = "expire-rpc-" + uuid4().hex
    queued = chat_rpc.submit(
        actor_id=chat.actors[0],
        conversation_id=conversation.conversation_id,
        request=request,
        idempotency_key=key,
    )
    chat.now += timedelta(minutes=1)
    assert chat_rpc.slot().state == "UNAVAILABLE"
    assert (
        chat_rpc.submit(
            actor_id=chat.actors[0],
            conversation_id=conversation.conversation_id,
            request=request,
            idempotency_key=key,
        )
        == queued
    )
    fresh = chat.create(actor=1)
    with pytest.raises(ChatOwnerFault) as failure:
        chat_rpc.submit(
            actor_id=chat.actors[1],
            conversation_id=fresh.conversation_id,
            request=request,
            idempotency_key="fresh-rpc-" + uuid4().hex,
        )
    assert failure.value.code == ChatOwnerErrorCode.NOT_READY
    assert (
        chat_rpc.conversation(
            actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
        ).messages
        == queued.messages
    )


def test_private_rpc_stale_version_and_conflicting_intent_remain_explicit_failures(
    chat: ChatFixture, chat_rpc: GeneralChatOwnerClient
) -> None:
    conversation = chat.create()
    request = GeneralChatSubmission(text="원 질문", expected_version=1)
    key = "conflict-rpc-" + uuid4().hex
    chat_rpc.submit(
        actor_id=chat.actors[0],
        conversation_id=conversation.conversation_id,
        request=request,
        idempotency_key=key,
    )
    for failure_key, body, code in (
        (
            key,
            GeneralChatSubmission(text="다른 질문", expected_version=1),
            ChatOwnerErrorCode.IDEMPOTENCY_CONFLICT,
        ),
        ("stale-rpc-" + uuid4().hex, request, ChatOwnerErrorCode.STALE_REVISION),
    ):
        with pytest.raises(ChatOwnerFault) as failure:
            chat_rpc.submit(
                actor_id=chat.actors[0],
                conversation_id=conversation.conversation_id,
                request=body,
                idempotency_key=failure_key,
            )
        assert failure.value.code == code


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
    chat.answer(claim, chat.execution.prepare(claim, identity=IDENTITY))
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
    assert request.messages[-1].text == "첫 사용자 전용 질문"
    assert chat.owner.slot().state == "BUSY"
    chat.answer(claim, request)
    other = chat.claim()
    other_request = chat.execution.prepare(other, identity=IDENTITY)
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
    assert chat.execution.prepare(claim, identity=IDENTITY) == request
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
    second_request = chat.execution.prepare(second, identity=IDENTITY)
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
    forged = ChatClaim(RUNTIME, claim.conversation_id, claim.turn_id, "chatclaim_" + "b" * 32)
    with pytest.raises(ChatError, match="CLAIM_MISMATCH"):
        chat.execution.prepare(forged, identity=IDENTITY)
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
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
    result = chat.answer(claim, chat.execution.prepare(claim, identity=IDENTITY), failed=True)
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
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
    request = chat.execution.prepare(claim, identity=IDENTITY)
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
    chat.answer(claim, chat.execution.prepare(claim, identity=IDENTITY))
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
        request = chat.execution.prepare(claim, identity=IDENTITY)
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


def test_dispatch_is_canonical_pointer_only_and_concurrent_prepare_is_exact_replay(
    chat: ChatFixture,
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    with chat.engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM artifact_revisions"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        requests = tuple(
            pool.map(lambda _: chat.execution.prepare(claim, identity=IDENTITY), range(8))
        )
    assert all(value == requests[0] for value in requests)
    receipt = chat.execution.execution_receipt(claim)
    assert receipt.identity == IDENTITY
    assert receipt.runtime_id == RUNTIME
    assert receipt.ticket == chat_worker_ticket(requests[0], policy_sha256=policy().sha256)
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "RUNNING"
        assert (turn.request_artifact_id, turn.request_revision_id, turn.request_sha256) == (
            receipt.input.artifact_id,
            receipt.input.artifact_revision_id,
            receipt.input.sha256,
        )
        assert turn.dispatch_artifact_id is not None
        assert turn.dispatch_revision_id is not None and turn.dispatch_sha256 is not None
    with chat.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM artifact_revisions")) == before + 2


@pytest.mark.parametrize("change", ["boot", "model", "prompt"])
def test_prepared_dispatch_cannot_be_reinterpreted_with_current_execution_policy(
    chat: ChatFixture,
    change: str,
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    document = IDENTITY.model_dump(mode="json")
    if change == "boot":
        document["boot_id"] = "chatboot_" + "f" * 32
    elif change == "model":
        document["policy"]["model"] = "different-synthetic-model"
    else:
        document["policy"]["prompt_sha256"] = "sha256:" + "f" * 64
    different = GeneralChatExecutionService(
        chat.repository,
        chat.evidence,
        clock=lambda: chat.now,
    )
    with pytest.raises(ChatError, match="EXECUTION_POLICY_MISMATCH"):
        different.prepare(claim, identity=ChatExecutionIdentity.model_validate(document))
    # Read-only audit/recovery follows historical pointers, not the new policy.
    assert different.execution_receipt(claim).identity == IDENTITY
    chat.answer(claim, request)


def test_dispatch_publication_interruption_never_grants_unrecorded_execution(
    chat: ChatFixture,
    monkeypatch,
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    publish = chat.evidence.publish
    attempts = 0

    def interrupted(**kwargs):
        nonlocal attempts
        pointer = publish(**kwargs)
        if kwargs["schema_ref"] == CHAT_DISPATCH_SCHEMA:
            attempts += 1
            if attempts == 1:
                raise OSError("synthetic interruption after canonical dispatch publication")
        return pointer

    monkeypatch.setattr(chat.evidence, "publish", interrupted)
    with pytest.raises(OSError, match="synthetic interruption"):
        chat.execution.prepare(claim, identity=IDENTITY)
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "CLAIMED"
        assert turn.request_artifact_id is None and turn.dispatch_artifact_id is None
    with chat.engine.connect() as connection:
        before_replay = connection.scalar(text("SELECT count(*) FROM artifact_revisions"))
    request = chat.execution.prepare(claim, identity=IDENTITY)
    receipt = chat.execution.execution_receipt(claim)
    assert receipt.ticket.request_sha256 == sha256_bytes(
        canonical_json_bytes(request.model_dump(mode="json"))
    )
    with chat.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM artifact_revisions")) == before_replay
    assert attempts == 2


def test_dispatch_pointer_is_db_immutable_and_dangling_revisions_fail(
    chat: ChatFixture,
) -> None:
    chat.submit(chat.create())
    claim = chat.claim()
    chat.execution.prepare(claim, identity=IDENTITY)
    with (
        pytest.raises(IntegrityError, match="dispatch identity is immutable"),
        chat.engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE general_chat_turns SET dispatch_sha256 = :digest WHERE turn_id = :turn"),
            {"digest": "sha256:" + "f" * 64, "turn": claim.turn_id},
        )
    with (
        pytest.raises(IntegrityError, match="fk_chat_dispatch_revision"),
        chat.repository.sessions.begin() as session,
    ):
        original = chat.repository.turn(session, claim.turn_id)
        session.add(
            GeneralChatTurnRecord(
                turn_id="chatturn_" + uuid4().hex,
                conversation_id=original.conversation_id,
                user_sequence=original.user_sequence + 2,
                expected_version=original.expected_version,
                submission_key_sha256="sha256:" + "e" * 64,
                submission_request_sha256=original.submission_request_sha256,
                state="FAILED",
                claim_id="chatclaim_" + uuid4().hex,
                input_artifact_id=original.input_artifact_id,
                input_revision_id=original.input_revision_id,
                input_sha256=original.input_sha256,
                request_artifact_id=original.request_artifact_id,
                request_revision_id=original.request_revision_id,
                request_sha256=original.request_sha256,
                dispatch_artifact_id=original.dispatch_artifact_id,
                dispatch_revision_id="rev_" + "f" * 32,
                dispatch_sha256=original.dispatch_sha256,
                failure_code="SYNTHETIC_FAILURE",
                created_at=NOW,
                completed_at=NOW,
            )
        )


def test_new_running_transition_requires_dispatch_even_without_application(
    chat: ChatFixture,
) -> None:
    first = chat.submit(chat.create())
    claim = chat.claim()
    chat.execution.prepare(claim, identity=IDENTITY)
    with chat.repository.sessions.begin() as session:
        original = chat.repository.turn(session, claim.turn_id)
    second = chat.submit(chat.create(actor=1), actor=1)
    # Isolated negative fixture: try the old source's transition without dispatch.
    # This is not an operational repair or bypass used by the application.
    with (
        pytest.raises(IntegrityError, match="new chat execution requires pinned dispatch"),
        chat.engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE general_chat_turns SET state = 'CLAIMED', claim_id = :claim "
                "WHERE conversation_id = :conversation"
            ),
            {"claim": "chatclaim_" + "e" * 32, "conversation": second.conversation_id},
        )
        connection.execute(
            text(
                "UPDATE general_chat_turns SET state = 'RUNNING', "
                "request_artifact_id = :artifact, request_revision_id = :revision, "
                "request_sha256 = :digest WHERE conversation_id = :conversation"
            ),
            {
                "artifact": original.request_artifact_id,
                "revision": original.request_revision_id,
                "digest": original.request_sha256,
                "conversation": second.conversation_id,
            },
        )
    assert (
        chat.owner.conversation(
            actor_id=chat.actors[0], conversation_id=first.conversation_id, cursor=None
        )
        .messages[0]
        .state
        == "RUNNING"
    )


def test_migration_downgrade_refuses_to_delete_pinned_execution_evidence(
    chat: ChatFixture,
) -> None:
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    chat.submit(chat.create())
    claim = chat.claim()
    chat.execution.prepare(claim, identity=IDENTITY)
    receipt = chat.execution.execution_receipt(claim)
    migration = import_module("migrations.versions.20261008_0049_general_chat_dispatch")
    with (
        pytest.raises(DBAPIError, match="cannot discard pinned chat dispatch provenance"),
        chat.engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
    assert chat.execution.execution_receipt(claim) == receipt
    assert {"dispatch_artifact_id", "dispatch_revision_id", "dispatch_sha256"} <= {
        column["name"]
        for column in inspect(chat.engine).get_columns("general_chat_turns", schema="app")
    }


@pytest.mark.parametrize("elapsed_minutes", [1, 31])
def test_exact_known_recovery_never_extends_lease_or_repeats_generation(
    chat: ChatFixture,
    chat_worker_rpc,
    elapsed_minutes: int,
) -> None:
    client, native, _ = chat_worker_rpc
    conversation = chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    client.check_admission()
    result = client.answer(request)
    assert chat.execution.active_claim() == claim
    receipt = chat.execution.execution_receipt(claim)
    chat.now += timedelta(minutes=elapsed_minutes)
    with chat.repository.sessions.begin() as session:
        expires = chat.repository.capacity(session).expires_at
    chat.execution.withdraw(runtime_id=RUNTIME)
    assert recover_known_chat_turn(chat.execution, client) == claim
    assert chat.execution.active_claim() is None
    chat.execution.reconcile_known_result(claim, result)  # terminal exact replay
    assert chat.execution.execution_receipt(claim) == receipt
    view = chat.owner.conversation(
        actor_id=chat.actors[0], conversation_id=conversation.conversation_id, cursor=None
    )
    assert view.messages[-1].state == "COMPLETED" and view.messages[-1].text == result.reply
    assert len(native.calls) == 1 and expires == NOW + timedelta(minutes=30)
    with pytest.raises(ChatError, match="NOT_READY"):
        chat.execution.claim_next(runtime_id=RUNTIME)
    assert recover_known_chat_turn(chat.execution, client) is None


def test_recovery_denies_live_owner_without_changing_claim_or_result_state(
    chat: ChatFixture,
    chat_worker_rpc,
) -> None:
    client, native, _ = chat_worker_rpc
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    client.check_admission()
    client.answer(request)
    chat.now += timedelta(minutes=31)
    chat.execution.heartbeat(runtime_id=RUNTIME)
    with pytest.raises(ChatError, match="RECOVERY_NOT_QUIESCENT"):
        recover_known_chat_turn(chat.execution, client)
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "RUNNING" and turn.result_sha256 is None
        assert chat.repository.capacity(session).expires_at == NOW + timedelta(minutes=30)
    assert len(native.calls) == 1


@pytest.mark.parametrize("state", ["UNKNOWN", "ABSENT"])
def test_unknown_or_absent_local_result_remains_fenced_after_claim_expiry(
    chat: ChatFixture,
    chat_worker_rpc,
    state: str,
) -> None:
    client, native, local = chat_worker_rpc
    chat.submit(chat.create())
    claim = chat.claim()
    chat.execution.prepare(claim, identity=IDENTITY)
    receipt = chat.execution.execution_receipt(claim)
    if state == "UNKNOWN":
        assert local.reserve(receipt.ticket)
    chat.now += timedelta(minutes=31)
    chat.execution.withdraw(runtime_id=RUNTIME)
    with pytest.raises(ChatError, match="RECONCILIATION_REQUIRED"):
        recover_known_chat_turn(chat.execution, client)
    assert client.lookup(receipt.ticket).state == state
    assert chat.execution.active_claim() == claim and not native.calls
    with pytest.raises(ChatError, match="RECONCILIATION_REQUIRED"):
        chat.execution.prepare(claim, identity=IDENTITY)


def test_expired_committing_recovery_reuses_pinned_hash_and_registered_output(
    chat: ChatFixture,
    chat_worker_rpc,
    monkeypatch,
) -> None:
    client, native, _ = chat_worker_rpc
    chat.submit(chat.create())
    claim = chat.claim()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    client.check_admission()
    result = client.answer(request)
    publish = chat.evidence.publish

    def disconnected(**kwargs):
        pointer = publish(**kwargs)
        if kwargs["schema_ref"] == CHAT_RESULT_SCHEMA:
            raise OSError("synthetic final canonical publication disconnect")
        return pointer

    monkeypatch.setattr(chat.evidence, "publish", disconnected)
    with pytest.raises(OSError, match="synthetic final"):
        chat.execution.complete(claim, result)
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "COMMITTING" and turn.result_sha256 is not None
        digest = turn.result_sha256
    monkeypatch.setattr(chat.evidence, "publish", publish)
    with chat.engine.connect() as connection:
        before_recovery = connection.scalar(text("SELECT count(*) FROM artifact_revisions"))
    chat.now += timedelta(minutes=31)
    chat.execution.withdraw(runtime_id=RUNTIME)
    assert recover_known_chat_turn(chat.execution, client) == claim
    with chat.repository.sessions.begin() as session:
        turn = chat.repository.turn(session, claim.turn_id)
        assert turn.state == "COMPLETED" and turn.output_sha256 == digest
    with chat.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM artifact_revisions")) == before_recovery
    assert len(native.calls) == 1
