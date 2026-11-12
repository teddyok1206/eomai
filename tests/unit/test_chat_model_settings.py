"""Model settings stay turn-pinned, owner-only and compatible with old handoffs."""

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_runtime_selection import native_runtime_from_environment
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.general_chat_model_settings import ChatModelSettingsPin, read_chat_model_settings
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerExecute,
    ChatWorkerLookup,
    ChatWorkerProbe,
    ChatWorkerRequest,
    chat_worker_ticket,
    read_chat_worker_request,
)
from jsonschema import ValidationError as SchemaError

from tests.unit.test_general_chat_resident import answer, staged
from tests.unit.test_general_chat_runtime_selection import selected_environment
from tests.unit.test_general_chat_worker_handoff import handoff as handoff

ROOT = Path(__file__).resolve().parents[2]


def settings_value(**change):
    value = dict(
        schema_version="general-chat-model-settings/1.0",
        settings_id="general-chat",
        revision_id="chatmodelrev_" + "a" * 32,
        revision_number=2,
        model="synthetic-model",
        reasoning_effort="medium",
        created_by="operator_" + "b" * 32,
        created_at=datetime(2026, 11, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    )
    value.update(change)
    return value | {"sha256": sha256_bytes(canonical_json_bytes(value))}


def selected_policy(*, model="synthetic-model", effort="medium"):
    return source_chat_worker_policy(
        model=model,
        protocol=4,
        native_runtime=native_runtime_from_environment(selected_environment()),
        reasoning_effort=effort,
        model_settings=ChatModelSettingsPin(
            revision_id="chatmodelrev_" + "a" * 32, sha256="sha256:" + "b" * 64
        ),
    )


def request(policy, command=None):
    command = command or ChatWorkerProbe()
    return read_chat_worker_request(
        ChatWorkerRequest(
            schema_version="general-chat-worker-request/5.0",
            request_id="chatwrpc_" + uuid4().hex,
            policy_sha256=command.ticket.policy_sha256
            if isinstance(command, ChatWorkerLookup)
            else policy.sha256,
            selected_policy=None if isinstance(command, ChatWorkerLookup) else policy,
            command=command,
        ).model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "leaf",
    (
        "general-chat-model-settings",
        "general-chat-worker-policy-v6",
        "general-chat-worker-request-v5",
        "general-chat-worker-reply-v5",
        "general-chat-dispatch-v6",
    ),
)
def test_new_schema_mirrors_preserve_released_families(leaf):
    assert (ROOT / "schemas/general-chat" / (leaf + ".schema.json")).read_bytes() == (
        ROOT / "packages/protocol/eom_protocol/schemas" / (leaf + ".schema.json")
    ).read_bytes()


def test_canonical_settings_hash_and_frozen_pin():
    value = settings_value()
    parsed = read_chat_model_settings(value)
    assert parsed.pin.revision_id == parsed.revision_id
    assert parsed.pin.sha256 == parsed.sha256
    changed = deepcopy(value)
    changed["reasoning_effort"] = "high"
    with pytest.raises(ValueError, match="hash"):
        read_chat_model_settings(changed)


@pytest.mark.parametrize("field", ("auth", "slot_id", "prompt", "path", "permission"))
def test_settings_do_not_admit_authority_or_runtime_paths(field):
    value = settings_value()
    value[field] = "untrusted"
    with pytest.raises(SchemaError):
        read_chat_model_settings(value)


@pytest.mark.parametrize("effort", ("minimal", "low", "medium", "high", "xhigh"))
def test_policy_and_handoff_pin_exact_settings(effort):
    policy = selected_policy(effort=effort)
    assert policy.schema_version == "general-chat-worker-policy/6.0"
    assert request(policy).selected_policy.reasoning_effort == effort
    changed = request(policy).model_dump(mode="json")
    changed["policy_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        read_chat_worker_request(changed)


class Native:
    def __init__(self, policy):
        self.policy = policy
        self.selections = []
        self.answers = []

    def require_admission(self, policy):
        assert policy == self.policy

    def select_policy(self, policy):
        self.policy = policy
        self.selections.append(policy)

    def answer(self, turn, **_):
        self.answers.append(self.policy)
        return answer(turn)


def application(handoff):
    initial = source_chat_worker_policy(
        model="old-model",
        protocol=4,
        native_runtime=native_runtime_from_environment(selected_environment()),
    )
    native = Native(initial)
    return ChatWorkerApplication(
        native, handoff[0], policy=initial, boot_id="chatboot_" + "b" * 32
    ), native


def test_switch_only_on_idle_probe_and_exact_replay_does_not_generate_twice(handoff):
    app, native = application(handoff)
    selected = selected_policy()
    assert app.handle(request(selected)).value.ready
    turn = staged(1)
    execute = request(selected, ChatWorkerExecute(boot_id=app.boot_id, turn=turn))
    result = app.handle(execute)
    assert result.status == "SUCCEEDED" and app.handle(execute) == result
    assert native.selections == [selected] and native.answers == [selected]
    newer = selected_policy(model="other-model", effort="high")
    assert app.handle(request(newer)).value.ready
    historical = request(
        newer, ChatWorkerLookup(ticket=chat_worker_ticket(turn, policy_sha256=selected.sha256))
    )
    assert app.handle(historical).value.state == "KNOWN"
    assert len(native.answers) == 1


def test_policy_switch_cannot_happen_in_execute_or_while_answering(handoff):
    app, native = application(handoff)
    selected = selected_policy()
    execute = request(selected, ChatWorkerExecute(boot_id=app.boot_id, turn=staged(1)))
    assert app.handle(execute).status == "FAILED"
    app._execution_lock.acquire()
    try:
        assert app.handle(request(selected)).error_code == "GENERAL_CHAT_WORKER_BUSY"
    finally:
        app._execution_lock.release()
    assert not native.selections and not native.answers


@pytest.mark.parametrize("field", ("prompt_sha256", "rag_prompt_sha256", "native_runtime"))
def test_switch_cannot_replace_installed_prompt_or_executable(handoff, field):
    app, native = application(handoff)
    value = selected_policy().model_dump(mode="json")
    value[field] = (
        "sha256:" + "f" * 64
        if field != "native_runtime"
        else value[field] | {"cli_binary_sha256": "sha256:" + "f" * 64}
    )
    from eom_protocol.general_chat_worker_messages import read_chat_worker_policy

    policy = read_chat_worker_policy(value)
    assert app.handle(request(policy)).status == "FAILED"
    assert not native.selections


def test_actual_private_rpc_switch_heartbeat_replay_and_busy_turn_are_isolated(handoff, tmp_path):
    app, native = application(handoff)
    root = tmp_path / "rpc"
    root.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(root / "worker.sock", os.getuid(), os.getgid())
    selected = [selected_policy()]
    client = ChatWorkerClient(
        endpoint=endpoint, policy=selected[0], policy_supplier=lambda: selected[0]
    )
    with ChatWorkerRpcServer(app, endpoint=endpoint, owner_uid=os.getuid()) as server:
        runner = Thread(target=server.serve)
        runner.start()
        try:
            client.check_admission()
            first = client.answer(staged(1))
            assert client.answer(staged(1)) == first and len(native.answers) == 1
            with ThreadPoolExecutor(max_workers=2) as pool:
                tuple(pool.map(lambda _: client.check_admission(), range(8)))
            assert len(native.answers) == 1
            entered, finish = Event(), Event()
            answer_once = native.answer

            def blocking(turn, **values):
                entered.set()
                assert finish.wait(5)
                return answer_once(turn, **values)

            native.answer = blocking
            with ThreadPoolExecutor(max_workers=1) as pool:
                turn = pool.submit(client.answer, staged(2))
                assert entered.wait(5)
                selected[0] = selected_policy(model="new-model", effort="high")
                from eom_orchestrator.general_chat_state import ChatError

                try:
                    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_BUSY"):
                        client.before_claim()
                    client.check_admission()
                finally:
                    finish.set()
                assert turn.result(timeout=5).status == "SUCCEEDED"
            client.before_claim()
            assert client.execution_identity.policy == selected[0]
            assert (
                client.lookup(
                    chat_worker_ticket(staged(1), policy_sha256=native.answers[0].sha256)
                ).state
                == "KNOWN"
            )
            assert len(native.answers) == 2 and native.answers[0] == native.answers[1]
        finally:
            server.stop()
            runner.join(5)
            assert not runner.is_alive()


@pytest.mark.parametrize("effort", ("minimal", "low", "medium", "high", "xhigh"))
def test_native_turn_transmits_selected_effort_without_changing_tools_or_sandbox(effort):
    from eom_orchestrator.general_chat_native import CodexChatSession

    from tests.unit.test_general_chat_native import CWD, MODEL, Channel
    from tests.unit.test_general_chat_native import request as native_request

    channel = Channel()
    session = CodexChatSession(channel, model=MODEL, cwd=CWD, reasoning_effort=effort)
    session.initialize()
    session.answer(native_request())
    turn = next(value for value in channel.sent if value.get("method") == "turn/start")
    assert turn["params"]["effort"] == effort
    assert turn["params"]["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
