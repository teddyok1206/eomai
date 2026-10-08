"""Real Unix RPC, durable local handoff and synthetic native: zero inference."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread

import pytest
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_lifecycle import serve_chat_worker
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.general_chat_worker_messages import chat_worker_ticket

from tests.unit.test_general_chat_resident import answer, staged
from tests.unit.test_general_chat_worker_handoff import BOOT, SyntheticNative, policy


@pytest.mark.parametrize("manual_stop", [False, True])
def test_listener_stops_but_known_answer_is_durable_before_service_exit(tmp_path, manual_stop):
    stop, retirement, entered, release = Event(), Event(), Event(), Event()
    codes, replies = [], []

    class RetiringNative(SyntheticNative):
        def answer(self, turn):
            entered.set()
            assert release.wait(3)
            retirement.set()
            return super().answer(turn)

    directory, rpc = tmp_path / "handoff", tmp_path / "rpc"
    directory.mkdir(mode=0o700)
    rpc.mkdir(mode=0o750)
    rpc.chmod(0o750)
    endpoint = ChatSocketEndpoint(rpc / "worker.sock", os.getuid(), os.getgid())
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as handoff:
        native = RetiringNative()
        application = ChatWorkerApplication(native, handoff, policy=policy(), boot_id=BOOT)
        server = ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid())
        service = Thread(
            target=lambda: codes.append(serve_chat_worker(server, stop=stop, retirement=retirement))
        )
        service.start()
        client = ChatWorkerClient(endpoint=endpoint, policy=policy())
        client.check_admission()
        request = staged(1)
        caller = Thread(target=lambda: replies.append(client.answer(request)))
        caller.start()
        try:
            assert entered.wait(2)
            (stop if manual_stop else retirement).set()
            assert server.stopped.wait(2)
            assert service.is_alive() and not codes
            assert (
                handoff.lookup(chat_worker_ticket(request, policy_sha256=policy().sha256)).state
                == "UNKNOWN"
            )
        finally:
            release.set()
            caller.join(3)
            service.join(3)
        assert not caller.is_alive() and not service.is_alive()
        assert replies == [answer(request)] and codes == [0 if manual_stop else 75]
        assert native.calls == [request] and not endpoint.path.exists()
    # Local result survives daemon/socket lifetime; no generation or new ticket.
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as reopened:
        result = reopened.lookup(chat_worker_ticket(request, policy_sha256=policy().sha256))
        assert result.state == "KNOWN" and result.result == answer(request)


def test_pre_requested_retirement_does_not_remove_pending_evidence(tmp_path: Path):
    directory, rpc = tmp_path / "handoff", tmp_path / "rpc"
    directory.mkdir(mode=0o700)
    rpc.mkdir(mode=0o750)
    rpc.chmod(0o750)
    endpoint = ChatSocketEndpoint(rpc / "worker.sock", os.getuid(), os.getgid())
    stop, retirement = Event(), Event()
    retirement.set()
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as handoff:
        assert handoff.reserve(ticket)
        native = SyntheticNative()
        server = ChatWorkerRpcServer(
            ChatWorkerApplication(native, handoff, policy=policy(), boot_id=BOOT),
            endpoint=endpoint,
            owner_uid=os.getuid(),
        )
        assert serve_chat_worker(server, stop=stop, retirement=retirement) == 75
        assert handoff.lookup(ticket).state == "UNKNOWN" and not native.calls
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as reopened:
        assert reopened.lookup(ticket).state == "UNKNOWN"
