"""V5 policy over existing private V4 RPC; synthetic output, zero inference."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Thread

import pytest
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.general_chat_rag_turn import RagChatTurnInput, RagChatTurnResult
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerPolicy,
    chat_worker_ticket,
    read_chat_worker_policy,
)

from tests.unit.general_chat_rag_fixtures import context, request, result
from tests.unit.test_general_chat_native_runtime_contracts import policy_document, runtime_policy
from tests.unit.test_general_chat_worker_handoff import BOOT


class SyntheticRagNative:
    def __init__(self) -> None:
        self.calls: list[RagChatTurnInput] = []
        self.ready = True

    def require_admission(self, policy: ChatWorkerPolicy) -> None:
        if not self.ready:
            raise ChatError("GENERAL_CHAT_WORKER_NOT_READY")

    def answer(self, turn: RagChatTurnInput, *, tools=None) -> RagChatTurnResult:
        self.calls.append(turn)
        return result(turn)


@pytest.fixture
def rpc_v5(tmp_path: Path, monkeypatch):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    socket_directory = tmp_path / "rpc"
    socket_directory.mkdir(mode=0o750)
    socket_directory.chmod(0o750)
    endpoint = ChatSocketEndpoint(socket_directory / "worker.sock", os.getuid(), os.getgid())
    selected = runtime_policy()
    native = SyntheticRagNative()
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as local:
        application = ChatWorkerApplication(native, local, policy=selected, boot_id=BOOT)
        received = []
        handle = application.handle

        def record(envelope, **values):
            received.append(envelope)
            return handle(envelope, **values)

        monkeypatch.setattr(application, "handle", record)
        with ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid()) as server:
            thread = Thread(target=server.serve)
            thread.start()
            try:
                yield ChatWorkerClient(endpoint=endpoint, policy=selected), native, local, received
            finally:
                server.stop()
                thread.join(2)
                assert not thread.is_alive()


def test_v5_policy_executes_and_exactly_replays_through_v4_private_rpc(rpc_v5) -> None:
    client, native, local, received = rpc_v5
    prepared = request(knowledge=context())
    client.check_admission()
    assert client.execution_identity.policy == runtime_policy()
    completed = client.answer(prepared)
    assert completed == result(prepared)
    assert client.answer(prepared) == completed
    ticket = chat_worker_ticket(prepared, policy_sha256=runtime_policy().sha256)
    assert client.lookup(ticket).result == completed
    assert local.lookup(ticket).result == completed
    assert native.calls == [prepared]
    assert {value.schema_version for value in received} == {"general-chat-worker-request/4.0"}
    assert [value.command.action for value in received] == ["PROBE", "EXECUTE", "EXECUTE", "RESULT"]


def test_v5_worker_recovers_old_v4_ticket_without_admission_or_policy_rewrite(rpc_v5) -> None:
    client, native, local, received = rpc_v5
    prepared = request(knowledge=context())
    historical = read_chat_worker_policy(policy_document(4))
    ticket = chat_worker_ticket(prepared, policy_sha256=historical.sha256)
    assert local.reserve(ticket)
    local.publish(ticket, result(prepared))
    native.ready = False
    recovered = client.lookup(ticket)
    assert recovered.state == "KNOWN" and recovered.result == result(prepared)
    assert received[-1].schema_version == "general-chat-worker-request/4.0"
    assert received[-1].policy_sha256 == historical.sha256 != runtime_policy().sha256
    assert received[-1].command.ticket == ticket
    with pytest.raises(ChatError, match="NOT_READY"):
        client.check_admission()
    assert client.lookup(ticket) == recovered
    assert local.lookup(ticket).result == result(prepared)
    assert native.calls == []
