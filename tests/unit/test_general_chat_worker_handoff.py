"""Synthetic private worker, real local handoff/socket; never calls a model."""

from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_native import CHAT_INSTRUCTIONS, NATIVE_PROFILE
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    send_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.general_chat import ChatTurnInput, ChatTurnResult
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerError,
    ChatWorkerExecute,
    ChatWorkerFault,
    ChatWorkerLookup,
    ChatWorkerPolicy,
    ChatWorkerProbe,
    ChatWorkerRequest,
    chat_worker_ticket,
    read_chat_worker_policy,
    read_chat_worker_reply,
    read_chat_worker_request,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_general_chat_resident import answer, staged

ROOT = Path(__file__).resolve().parents[2]
BOOT = "chatboot_" + "b" * 32


def policy() -> ChatWorkerPolicy:
    return read_chat_worker_policy(
        {
            "schema_version": "general-chat-worker-policy/1.0",
            "model": "synthetic-model",
            "native_profile": NATIVE_PROFILE,
            "prompt_revision": "general-chat/1.0.0",
            "prompt_sha256": sha256_bytes(CHAT_INSTRUCTIONS.encode("utf-8")),
        }
    )


def request(command=None, *, selected_policy: ChatWorkerPolicy | None = None) -> ChatWorkerRequest:
    return read_chat_worker_request(
        ChatWorkerRequest(
            request_id="chatwrpc_" + uuid4().hex,
            policy_sha256=(selected_policy or policy()).sha256,
            command=command or ChatWorkerExecute(boot_id=BOOT, turn=staged(1)),
        ).model_dump(mode="json")
    )


class SyntheticNative:
    def __init__(self) -> None:
        self.calls: list[ChatTurnInput] = []
        self.ready = True

    def require_admission(self, selected_policy: ChatWorkerPolicy) -> None:
        if not self.ready:
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)

    def answer(self, turn: ChatTurnInput) -> ChatTurnResult:
        self.calls.append(turn)
        return answer(turn)


@pytest.fixture
def handoff(tmp_path: Path):
    directory = tmp_path / "private-handoff"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as store:
        yield store, directory


@pytest.fixture
def worker(handoff):
    store, directory = handoff
    native = SyntheticNative()
    application = ChatWorkerApplication(native, store, policy=policy(), boot_id=BOOT)
    return application, native, directory


@pytest.fixture
def rpc(worker, tmp_path: Path):
    application, native, directory = worker
    runtime = tmp_path / "private-rpc"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    endpoint = ChatSocketEndpoint(runtime / "worker.sock", os.getuid(), os.getgid())
    with ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid()) as server:
        thread = Thread(target=server.serve)
        thread.start()
        try:
            yield ChatWorkerClient(endpoint=endpoint, policy=policy()), server, native, directory
        finally:
            server.stop()
            thread.join(2)
            assert not thread.is_alive()


def test_worker_protocol_canonical_mirrors_and_frozen_values() -> None:
    for kind in ("policy", "ticket", "request", "reply"):
        leaf = f"general-chat-worker-{kind}.schema.json"
        canonical = (ROOT / "schemas/general-chat" / leaf).read_bytes()
        assert canonical == (ROOT / "packages/protocol/eom_protocol/schemas" / leaf).read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical))
    pinned = policy()
    assert pinned.sha256 == sha256_bytes(canonical_json_bytes(pinned.model_dump(mode="json")))
    with pytest.raises(ValidationError):
        pinned.model = "other"
    document = pinned.model_dump(mode="json")
    document["auth"] = "forbidden"
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)


@pytest.mark.parametrize("field", ["owner_id", "native_thread_id", "nas_path", "auth"])
def test_worker_request_rejects_native_identity_storage_and_auth_fields(field: str) -> None:
    document = request().model_dump(mode="json")
    document["command"][field] = "caller-controlled"
    with pytest.raises(SchemaError):
        read_chat_worker_request(document)


def test_worker_reply_hash_boot_correlation_action_and_result_identity_are_pinned(worker) -> None:
    application, _, _ = worker
    original = request()
    reply = application.handle(original)
    assert reply.status == "SUCCEEDED"
    document = reply.model_dump(mode="json")
    for field, value in (
        ("request_id", "chatwrpc_" + "f" * 32),
        ("boot_id", "chatboot_" + "f" * 32),
        ("policy_sha256", "sha256:" + "f" * 64),
        ("action", "PROBE"),
    ):
        with pytest.raises((ValueError, SchemaError)):
            read_chat_worker_reply({**document, field: value}, request=original)
    document["value"]["result"]["request_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        read_chat_worker_reply(document, request=original)


def test_result_lookup_cannot_change_nested_policy() -> None:
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    document = request(ChatWorkerLookup(ticket=ticket)).model_dump(mode="json")
    document["command"]["ticket"]["policy_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        read_chat_worker_request(document)


def test_local_handoff_records_metadata_not_transcript_and_durable_marker_is_unique(
    handoff,
) -> None:
    store, directory = handoff
    turn = staged(1)
    ticket = chat_worker_ticket(turn, policy_sha256=policy().sha256)
    assert store.lookup(ticket).state == "ABSENT"
    assert store.reserve(ticket)
    assert not store.reserve(ticket)
    assert store.lookup(ticket).state == "UNKNOWN"
    payload = (directory / (ticket.claim_id + ".pending.json")).read_bytes()
    assert turn.messages[0].text.encode() not in payload
    assert b"messages" not in payload and b"reply" not in payload
    assert (directory / (ticket.claim_id + ".pending.json")).stat().st_mode & 0o777 == 0o400
    store.publish(ticket, answer(turn))
    assert store.lookup(ticket).result == answer(turn)
    store.publish(ticket, answer(turn))
    assert not tuple(directory.glob("staged-result-*"))


def test_local_handoff_conflicting_ticket_or_result_never_overwrites(handoff) -> None:
    store, directory = handoff
    turn = staged(1)
    ticket = chat_worker_ticket(turn, policy_sha256=policy().sha256)
    store.reserve(ticket)
    original = answer(turn)
    store.publish(ticket, original)
    leaf = directory / (ticket.claim_id + ".result.json")
    expected = leaf.read_bytes()
    with pytest.raises(ChatWorkerFault) as failure:
        store.publish(ticket, original.model_copy(update={"reply": "different"}))
    assert failure.value.code == ChatWorkerError.INVALID and leaf.read_bytes() == expected
    other = ticket.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ChatWorkerFault):
        store.lookup(other)
    assert leaf.read_bytes() == expected


def test_wrong_ticket_is_denied_before_result_bytes_are_read(handoff, monkeypatch) -> None:
    store, _ = handoff
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    store.reserve(ticket)
    store.publish(ticket, answer(staged(1)))
    read_leaves = []
    original = store._read

    def record(leaf, *, limit):
        read_leaves.append(leaf)
        return original(leaf, limit=limit)

    monkeypatch.setattr(store, "_read", record)
    with pytest.raises(ChatWorkerFault):
        store.lookup(ticket.model_copy(update={"request_sha256": "sha256:" + "f" * 64}))
    assert read_leaves == [ticket.claim_id + ".pending.json"]


def test_marker_durability_failure_never_starts_or_retries_a_model(worker, monkeypatch) -> None:
    application, native, directory = worker
    original = os.fsync
    calls = 0

    def fail_once(descriptor):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic durability uncertainty")
        return original(descriptor)

    monkeypatch.setattr("eom_orchestrator.general_chat_handoff.os.fsync", fail_once)
    assert application.handle(request()).error_code == ChatWorkerError.RECOVERY
    assert application.handle(request()).error_code == ChatWorkerError.RECOVERY
    assert not native.calls
    assert len(tuple(directory.glob("*.pending.json"))) == 1


def test_result_publication_failure_retains_unknown_claim_without_inference_retry(
    worker, monkeypatch
) -> None:
    application, native, directory = worker
    original = application.handoff._write

    def fail_result(descriptor, payload):
        if b'"reply"' in payload:
            raise OSError("synthetic result publication error")
        return original(descriptor, payload)

    monkeypatch.setattr(application.handoff, "_write", fail_result)
    assert application.handle(request()).error_code == ChatWorkerError.RECOVERY
    assert application.handle(request()).error_code == ChatWorkerError.RECOVERY
    assert len(native.calls) == 1
    assert len(tuple(directory.glob("*.pending.json"))) == 1
    assert not tuple(directory.glob("*.result.json"))
    assert not tuple(directory.glob("staged-result-*"))


def test_pending_claim_survives_restart_and_never_becomes_executable_again(handoff) -> None:
    store, directory = handoff
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    store.reserve(ticket)
    with ChatLocalHandoff(directory, worker_uid=os.getuid()) as restarted:
        assert restarted.lookup(ticket).state == "UNKNOWN"
        assert not restarted.reserve(ticket)
        restarted.publish(ticket, answer(staged(1)))
        assert restarted.lookup(ticket).state == "KNOWN"


def test_many_concurrent_exact_reservations_admit_at_most_one(handoff) -> None:
    store, _ = handoff
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)

    def reserve(_):
        try:
            return store.reserve(ticket)
        except ChatWorkerFault:
            # Reading a not-yet-fsynced marker is fail-closed, never a second start.
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        assert sum(pool.map(reserve, range(20))) == 1
    assert store.lookup(ticket).state == "UNKNOWN"


@pytest.mark.parametrize("shape", ["symlink", "fifo", "directory", "writable", "oversized", "json"])
def test_local_handoff_treats_untrusted_files_as_explicit_errors(handoff, shape: str) -> None:
    store, directory = handoff
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    leaf = directory / (ticket.claim_id + ".pending.json")
    if shape == "symlink":
        leaf.symlink_to(directory / "absent")
    elif shape == "fifo":
        os.mkfifo(leaf, 0o400)
    elif shape == "directory":
        leaf.mkdir()
    else:
        leaf.write_bytes(b"x" * 5000 if shape == "oversized" else b"{}")
        leaf.chmod(0o600 if shape == "writable" else 0o400)
    with pytest.raises(ChatWorkerFault):
        store.lookup(ticket)
    assert leaf.exists() or leaf.is_symlink()


def test_result_without_its_pending_identity_is_not_invented_as_known(handoff) -> None:
    store, directory = handoff
    turn = staged(1)
    ticket = chat_worker_ticket(turn, policy_sha256=policy().sha256)
    leaf = directory / (ticket.claim_id + ".result.json")
    leaf.write_bytes(canonical_json_bytes(answer(turn).model_dump(mode="json")))
    leaf.chmod(0o400)
    with pytest.raises(ChatWorkerFault) as failure:
        store.lookup(ticket)
    assert failure.value.code == ChatWorkerError.RECOVERY


def test_closed_handoff_cannot_use_a_recycled_directory_descriptor(handoff, tmp_path: Path) -> None:
    store, _ = handoff
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    store.close()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    descriptor = os.open(unrelated, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ChatWorkerFault):
            store.reserve(ticket)
        with pytest.raises(ChatWorkerFault):
            store.lookup(ticket)
        assert not tuple(unrelated.iterdir())
    finally:
        os.close(descriptor)


def test_native_executes_once_then_replays_exact_result_even_after_auth_loss(worker) -> None:
    application, native, _ = worker
    first = application.handle(request())
    native.ready = False
    second = application.handle(request())
    assert first.value == second.value and second.status == "SUCCEEDED"
    assert len(native.calls) == 1
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    assert application.handle(request(ChatWorkerLookup(ticket=ticket))).value == first.value
    probe = application.handle(request(ChatWorkerProbe()))
    assert probe.value.ready is False


def test_unknown_native_outcome_retains_pending_receipt_no_auto_retry(worker) -> None:
    application, native, directory = worker

    def fail(turn):
        native.calls.append(turn)
        raise RuntimeError("must never export raw private native output")

    native.answer = fail
    first = application.handle(request())
    second = application.handle(request())
    assert first.error_code == second.error_code == ChatWorkerError.RECOVERY
    assert len(native.calls) == 1
    assert len(tuple(directory.glob("*.pending.json"))) == 1
    assert not tuple(directory.glob("*.result.json"))
    assert "private" not in str(first.model_dump())


def test_policy_or_boot_change_never_dispatches_a_turn(worker) -> None:
    application, native, directory = worker
    different = policy().model_copy(update={"model": "other-synthetic-model"})
    assert (
        application.handle(request(selected_policy=different)).error_code
        == ChatWorkerError.NOT_READY
    )
    changed_boot = request(ChatWorkerExecute(boot_id="chatboot_" + "c" * 32, turn=staged(1)))
    assert application.handle(changed_boot).error_code == ChatWorkerError.NOT_READY
    assert not native.calls and not tuple(directory.iterdir())


def test_other_claim_is_busy_while_probes_and_read_only_lookup_remain_available(worker) -> None:
    application, native, _ = worker
    entered, release = Event(), Event()
    original = native.answer

    def blocked(turn):
        entered.set()
        assert release.wait(2)
        return original(turn)

    native.answer = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(application.handle, request())
        try:
            assert entered.wait(2)
            other = application.handle(request(ChatWorkerExecute(boot_id=BOOT, turn=staged(2))))
            assert other.error_code == ChatWorkerError.BUSY
            assert application.handle(request(ChatWorkerProbe())).value.ready
            ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
            lookup = application.handle(request(ChatWorkerLookup(ticket=ticket)))
            assert lookup.value.state == "UNKNOWN"
        finally:
            release.set()
        assert running.result(2).status == "SUCCEEDED"
    assert len(native.calls) == 1


def test_real_private_socket_probe_execute_and_lookup(rpc) -> None:
    client, _, native, _ = rpc
    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
        client.answer(staged(1))
    client.check_admission()
    assert client.answer(staged(1)) == answer(staged(1))
    assert client.answer(staged(1)) == answer(staged(1))
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    assert client.lookup(ticket).result == answer(staged(1))
    assert len(native.calls) == 1


def test_real_socket_result_recovery_after_disconnect_does_not_repeat_generation(rpc) -> None:
    client, server, native, _ = rpc
    entered, release = Event(), Event()
    original = native.answer

    def blocked(turn):
        entered.set()
        assert release.wait(2)
        return original(turn)

    native.answer = blocked
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(str(server.endpoint.path))
    sent = request()
    send_chat_frame(
        connection,
        canonical_json_bytes(sent.model_dump(mode="json")),
        limit=256000,
        deadline=monotonic() + 2,
    )
    try:
        assert entered.wait(2)
        connection.close()
        release.set()
        # The generation thread may still be fsyncing. A read-only lookup waits
        # for the known result without ever reissuing EXECUTE.
        ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
        with ThreadPoolExecutor(max_workers=1) as pool:

            def read_result():
                for _ in range(100):
                    output = client.lookup(ticket)
                    if output.state == "KNOWN":
                        return output
                    Event().wait(0.01)
                raise AssertionError("synthetic local result not published")

            assert pool.submit(read_result).result(3).result == answer(staged(1))
        assert len(native.calls) == 1
    finally:
        connection.close()
        release.set()


def test_rebooted_worker_requires_new_admission_but_old_known_result_is_readable(
    rpc, handoff
) -> None:
    client, server, native, _ = rpc
    client.check_admission()
    client.answer(staged(1))
    replacement = SyntheticNative()
    replacement.ready = False
    server.worker = ChatWorkerApplication(
        replacement, handoff[0], policy=policy(), boot_id="chatboot_" + "c" * 32
    )
    ticket = chat_worker_ticket(staged(1), policy_sha256=policy().sha256)
    assert client.lookup(ticket).result == answer(staged(1))
    replacement.ready = True
    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
        client.check_admission()
    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
        client.answer(staged(2))
    assert len(native.calls) == 1 and not replacement.calls


def test_private_worker_peer_denial_happens_before_native_or_local_file_use(
    worker, tmp_path
) -> None:
    application, native, directory = worker
    runtime = tmp_path / "wrong-peer-rpc"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    endpoint = ChatSocketEndpoint(runtime / "worker.sock", os.getuid(), os.getgid())
    with ChatWorkerRpcServer(
        application, endpoint=endpoint, owner_uid=os.getuid() + 10000
    ) as server:
        thread = Thread(target=server.serve)
        thread.start()
        try:
            client = ChatWorkerClient(endpoint=endpoint, policy=policy())
            with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
                client.check_admission()
        finally:
            server.stop()
            thread.join(2)
    assert not native.calls and not tuple(directory.iterdir())


def test_execute_transport_failure_is_unknown_and_never_automatically_replayed(
    rpc, monkeypatch
) -> None:
    client, _, native, _ = rpc
    client.check_admission()
    calls = []

    def unavailable(endpoint, document, **kwargs):
        calls.append(document)
        raise ChatTransportError("UNAVAILABLE")

    monkeypatch.setattr(
        "eom_orchestrator.general_chat_worker_client.exchange_chat_frame", unavailable
    )
    with pytest.raises(ChatError, match="GENERAL_CHAT_RECONCILIATION_REQUIRED"):
        client.answer(staged(1))
    assert len(calls) == 1 and not native.calls
