"""Autonomous reads without a model, DB or NAS; legacy contracts remain closed."""

from __future__ import annotations

import json
import os
import socket
import struct
from pathlib import Path
from threading import Thread
from time import monotonic

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_agent_native import NativeChatTools, native_chat_tools
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    receive_chat_stream,
    receive_chat_worker_request,
    send_chat_stream,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_tool_broker import ChatToolBroker, agent_tool_knowledge
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import (
    AgentChatTurnInput,
    ChatKnowledgeCatalogReply,
    read_chat_input,
    read_chat_result,
    validate_agent_citations,
)
from eom_protocol.general_chat_tools import (
    ChatDiscoveryCard,
    ChatReadArguments,
    ChatReadCommand,
    ChatSearchArguments,
    ChatSearchCommand,
    ChatToolOutcome,
    ChatToolRequest,
    failed_tool,
)
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerExecute,
    ChatWorkerRequest,
    chat_worker_ticket,
    read_chat_worker_request,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_general_chat_grounding_contract import context, item, result
from tests.unit.test_general_chat_grounding_contract import request as v2_request
from tests.unit.test_general_chat_native import Channel, answer_item, event, final_event, session

RPC = "chatwrpc_" + "a" * 32


def request():
    value = v2_request().model_dump(mode="json")
    value.update(
        protocol_version="general-chat-turn/3.0",
        prompt_revision="general-chat-agent/1.0.0",
        knowledge=None,
    )
    return read_chat_input(value)


def arguments(kind="RECENT", **changes):
    value = dict(
        kind=kind,
        source="ALL",
        terms=[],
        administration_year=None,
        administration_month=None,
        target_school_level=None,
        target_grade=None,
        subject_key=None,
        item_number=None,
    )
    value.update(changes)
    return ChatSearchArguments.model_validate(value)


class Evidence:
    def __init__(self):
        self.payloads = {}
        self.intents = {}

    def publish(self, *, payload, schema_ref, intent, created_at):
        prior = self.intents.get(intent)
        if prior is not None:
            assert self.payloads[prior] == payload
            return prior
        number = len(self.payloads) + 1
        pointer = ArtifactMemberPointer(
            artifact_id=f"artifact_{number:032x}",
            artifact_revision_id=f"rev_{number:032x}",
            member_path="chat/evidence.json",
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=sha256_bytes(payload),
        )
        self.payloads[pointer] = payload
        self.intents[intent] = pointer
        return pointer

    def read(self, pointers):
        return tuple(self.payloads[p] for p in pointers)


class Knowledge:
    def __init__(self):
        self.calls = []
        self.outcome = ChatToolOutcome(
            status="SUCCEEDED",
            cards=(
                ChatDiscoveryCard(
                    item=item(),
                    display_name="합성 문항",
                    approval="APPROVED",
                    source_kind="GENERATED",
                    graph_membership="UNAVAILABLE",
                ),
            ),
            snapshot=None,
            truncated=False,
            context=None,
            error_code=None,
        )

    def search(self, **values):
        self.calls.append(("search", values))
        return self.outcome

    def resolve(self, **values):
        self.calls.append(("read", values))
        assert values["selection"] == context().selection
        return ChatKnowledgeCatalogReply(
            status="SUCCEEDED", context=context(), agent_state=None, error_code=None
        )


class Port:
    def __init__(self, prepared=None):
        self.prepared = request() if prepared is None else prepared
        self.evidence, self.knowledge = Evidence(), Knowledge()
        self.ticket = chat_worker_ticket(
            self.prepared, policy_sha256=source_chat_worker_policy(model="test-model").sha256
        )
        self.broker = ChatToolBroker(
            rpc_request_id=RPC,
            ticket=self.ticket,
            actor_guard=lambda: "operator_" + "1" * 32,
            knowledge=self.knowledge,
            evidence=self.evidence,
        )
        self.sequence = 0

    def call(self, command):
        self.sequence += 1
        intent = ChatToolRequest.model_validate(
            dict(rpc_request_id=RPC, ticket=self.ticket, sequence=self.sequence, command=command)
        )
        return self.broker.execute(intent)


def read_command():
    return ChatReadCommand(arguments=ChatReadArguments(references=(item(),)))


def test_additive_schema_mirrors_and_v3_envelope_roundtrip():
    from eom_orchestrator.general_chat_stdio import native_chat_command

    root = Path(__file__).resolve().parents[2]
    for path in (root / "schemas/general-chat").glob("*-v3.schema.json"):
        assert (
            path.read_bytes()
            == (root / "packages/protocol/eom_protocol/schemas" / path.name).read_bytes()
        )
        Draft202012Validator.check_schema(json.loads(path.read_bytes()))
    staged = request()
    assert isinstance(staged, AgentChatTurnInput)
    policy = source_chat_worker_policy(model="test-model")
    envelope = ChatWorkerRequest(
        schema_version="general-chat-worker-request/3.0",
        request_id=RPC,
        policy_sha256=policy.sha256,
        command=ChatWorkerExecute(boot_id="chatboot_" + "1" * 32, turn=staged),
    )
    assert read_chat_worker_request(envelope.model_dump(mode="json")) == envelope
    old = envelope.model_dump(mode="json")
    old["schema_version"] = "general-chat-worker-request/2.0"
    with pytest.raises(SchemaError):
        read_chat_worker_request(old)
    for spec in native_chat_tools():
        Draft202012Validator.check_schema(spec["inputSchema"])
    command = native_chat_command(model="test-model")
    assert 'features.code_mode={enabled=false,direct_only_tool_namespaces=["functions"]}' in command
    assert "features.code_mode_host=false" in command
    assert "features.shell_tool=false" in command


@pytest.mark.skipif(not Path("/usr/local/bin/codex").exists(), reason="pinned CLI unavailable")
def test_exact_launcher_parses_in_installed_strict_cli_without_auth_or_inference(tmp_path):
    import subprocess

    from eom_orchestrator.general_chat_stdio import native_chat_command

    command = native_chat_command(model="synthetic-model")
    probe = subprocess.run(
        command,
        input=b"",
        capture_output=True,
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "CODEX_HOME": str(tmp_path),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "RUST_LOG": "off",
        },
        timeout=15,
        check=False,
    )
    assert probe.returncode == 0, "strict native launcher configuration was rejected"


def test_model_search_read_answer_is_bound_to_canonical_tool_pointers():
    port = Port()
    tools = NativeChatTools(port.prepared, port)
    discovered = json.loads(tools.call("search_eom_items", arguments().model_dump(mode="json")))
    assert discovered["cards"][0]["item"] == item().model_dump(mode="json")
    tools.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
    reply = canonical_json_bytes(result().answer.model_dump(mode="json")).decode()
    completed = tools.result(reply=reply, failure=None)
    assert read_chat_result(completed.model_dump(mode="json"), request=port.prepared) == completed
    resolved = agent_tool_knowledge(port.prepared, completed, port.evidence)
    assert resolved.context == context()
    assert validate_agent_citations(
        port.prepared, completed, resolved.context
    ).used_source_keys == ("S1",)
    assert len(completed.tool_records) == 2
    document = completed.model_dump(mode="json")
    assert "text" not in document and "sources" not in document
    assert [kind for kind, _ in port.knowledge.calls] == ["search", "read"]


@pytest.mark.parametrize("patch", ["claim", "hash", "sequence", "rpc", "pointer", "context"])
def test_forged_or_cross_turn_tool_evidence_is_rejected(patch):
    port = Port()
    tools = NativeChatTools(port.prepared, port)
    tools.call("search_eom_items", arguments().model_dump(mode="json"))
    tools.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
    completed = tools.result(
        reply=canonical_json_bytes(result().answer.model_dump(mode="json")).decode(), failure=None
    )
    pointer = completed.tool_records[1]
    if patch == "pointer":
        port.evidence.payloads[pointer] += b" "
    else:
        value = json.loads(port.evidence.payloads[pointer])
        if patch == "claim":
            value["request"]["ticket"]["claim_id"] = "chatclaim_" + "9" * 32
        elif patch == "hash":
            value["request"]["ticket"]["request_sha256"] = "sha256:" + "9" * 64
        elif patch == "sequence":
            value["request"]["sequence"] = 4
        elif patch == "rpc":
            value["request"]["rpc_request_id"] = "chatwrpc_" + "9" * 32
        else:
            value["outcome"]["context"]["sources"][0]["text"] = "tampered"
        payload = canonical_json_bytes(value)
        changed = pointer.model_copy(update={"sha256": sha256_bytes(payload)})
        port.evidence.payloads[changed] = payload
        completed = completed.model_copy(
            update={"tool_records": (completed.tool_records[0], changed)}
        )
    with pytest.raises((ChatError, ValueError, ValidationError, SchemaError)):
        agent_tool_knowledge(port.prepared, completed, port.evidence)


def test_not_offered_second_read_and_search_budget_are_honest_errors():
    port = Port()
    denied = port.call(read_command().model_dump(mode="json"))
    assert denied.record.outcome.error_code == "CHAT_KNOWLEDGE_NOT_OFFERED"
    assert not port.knowledge.calls
    port.call(ChatSearchCommand(arguments=arguments()).model_dump(mode="json"))
    denied = port.call(read_command().model_dump(mode="json"))
    assert denied.record.outcome.error_code == "CHAT_KNOWLEDGE_READ_LIMIT"
    port = Port()
    for _ in range(4):
        port.call(ChatSearchCommand(arguments=arguments()).model_dump(mode="json"))
    assert (
        port.call(
            ChatSearchCommand(arguments=arguments()).model_dump(mode="json")
        ).record.outcome.error_code
        == "CHAT_KNOWLEDGE_READ_LIMIT"
    )


@pytest.mark.parametrize("status", ["EMPTY", "FORBIDDEN", "UNAVAILABLE"])
def test_empty_denied_unavailable_do_not_create_item_evidence(status):
    port = Port()
    port.knowledge.outcome = (
        ChatToolOutcome(
            status="EMPTY", cards=(), snapshot=None, truncated=False, context=None, error_code=None
        )
        if status == "EMPTY"
        else failed_tool("CHAT_KNOWLEDGE_" + status)
    )
    outcome = port.call(
        ChatSearchCommand(arguments=arguments()).model_dump(mode="json")
    ).record.outcome
    assert not outcome.cards and outcome.context is None
    assert outcome.status == ("EMPTY" if status == "EMPTY" else "FAILED")


def tool_events(tool, arguments, call_id):
    started = dict(
        type="dynamicToolCall",
        id=call_id,
        tool=tool,
        arguments=arguments,
        status="inProgress",
        namespace=None,
    )
    call = event("item/tool/call", callId=call_id, tool=tool, arguments=arguments, namespace=None)
    call["id"] = "request-" + call_id
    return [
        event("item/started", item=started),
        call,
        event("item/completed", item={**started, "status": "completed", "success": True}),
    ]


@pytest.mark.parametrize("early_events", [False, True])
def test_actual_native_dynamic_exchange_uses_only_two_scoped_tools(early_events):
    events = tool_events("search_eom_items", arguments().model_dump(mode="json"), "call1")
    events += tool_events(
        "read_eom_items", read_command().arguments.model_dump(mode="json"), "call2"
    )
    answer = canonical_json_bytes(result().answer.model_dump(mode="json")).decode()
    events += [event("item/completed", item=answer_item(text=answer)), final_event()]
    channel = Channel(events)
    channel.early_events = early_events
    native, channel = session(channel)
    port = Port()
    completed = native.answer(port.prepared, tools=port)
    assert completed.status == "SUCCEEDED" and len(completed.tool_records) == 2
    responses = [
        value for value in channel.sent if str(value.get("id", "")).startswith("request-call")
    ]
    assert len(responses) == 2 and all(value["result"]["success"] for value in responses)
    started = next(
        value["params"] for value in channel.sent if value.get("method") == "thread/start"
    )
    assert [value["name"] for value in started["dynamicTools"]] == [
        "search_eom_items",
        "read_eom_items",
    ]
    assert started["environments"] == []
    assert native.ready


@pytest.mark.parametrize("patch", ["tool", "thread", "turn", "namespace", "call", "server_request"])
def test_native_unknown_or_mismatched_requests_poison_without_query(patch):
    events = tool_events("search_eom_items", arguments().model_dump(mode="json"), "call1")
    target = events[1]
    if patch == "tool":
        target["params"]["tool"] = "delete_item"
    elif patch == "thread":
        target["params"]["threadId"] = "other"
    elif patch == "turn":
        target["params"]["turnId"] = "other"
    elif patch == "namespace":
        target["params"]["namespace"] = "shell"
    elif patch == "call":
        target["params"]["callId"] = "other"
    else:
        target["method"] = "item/permissions/requestApproval"
    native, channel = session(Channel(events))
    port = Port()
    completed = native.answer(port.prepared, tools=port)
    assert completed.status == "FAILED" and not port.knowledge.calls
    assert channel.closed and not native.ready and not completed.reply


def test_same_socket_stream_preserves_frame_boundaries_and_legacy_eof():
    left, right = socket.socketpair()
    with left, right:
        deadline = monotonic() + 3
        send_chat_stream(left, {"a": 1}, deadline=deadline)
        send_chat_stream(left, {"b": 2}, deadline=deadline)
        value, streamed = receive_chat_worker_request(right, deadline=deadline)
        assert value == {"a": 1} and streamed
        assert receive_chat_stream(right, deadline=deadline) == {"b": 2}
        send_chat_stream(right, {"tool_reply": True}, deadline=deadline)
        assert receive_chat_stream(left, deadline=deadline) == {"tool_reply": True}
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b'{"legacy":true}\n')
        left.shutdown(socket.SHUT_WR)
        assert receive_chat_worker_request(right, deadline=monotonic() + 3) == (
            {"legacy": True},
            False,
        )


def test_real_v3_socket_tools_handoff_lookup_and_no_generation_replay(tmp_path):
    selected = source_chat_worker_policy(model="synthetic-model")
    evidence, knowledge = Evidence(), Knowledge()

    class SyntheticNative:
        calls = 0

        def require_admission(self, policy):
            assert policy == selected

        def answer(self, prepared, *, tools):
            self.calls += 1
            exchange = NativeChatTools(prepared, tools)
            exchange.call("search_eom_items", arguments().model_dump(mode="json"))
            exchange.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
            return exchange.result(
                reply=canonical_json_bytes(result().answer.model_dump(mode="json")).decode(),
                failure=None,
            )

    def broker(envelope):
        ticket = chat_worker_ticket(envelope.command.turn, policy_sha256=selected.sha256)
        return ChatToolBroker(
            rpc_request_id=envelope.request_id,
            ticket=ticket,
            actor_guard=lambda: "operator_" + "1" * 32,
            knowledge=knowledge,
            evidence=evidence,
        )

    runtime, local = tmp_path / "rpc", tmp_path / "handoff"
    runtime.mkdir(mode=0o750)
    local.mkdir(mode=0o700)
    native = SyntheticNative()
    endpoint = ChatSocketEndpoint(runtime / "worker.sock", os.getuid(), os.getgid())
    with ChatLocalHandoff(local, worker_uid=os.getuid()) as handoff:
        application = ChatWorkerApplication(
            native, handoff, policy=selected, boot_id="chatboot_" + "1" * 32
        )
        with ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid()) as server:
            thread = Thread(target=server.serve)
            thread.start()
            try:
                client = ChatWorkerClient(endpoint=endpoint, policy=selected, tools=broker)
                client.check_admission()
                prepared = request()
                completed = client.answer(prepared)
                assert completed.status == "SUCCEEDED" and len(completed.tool_records) == 2
                ticket = chat_worker_ticket(prepared, policy_sha256=selected.sha256)
                assert client.lookup(ticket).result == completed
                assert client.answer(prepared) == completed
                assert native.calls == 1 and len(knowledge.calls) == 2
                assert agent_tool_knowledge(prepared, completed, evidence).context == context()
            finally:
                server.stop()
                thread.join(3)
                assert not thread.is_alive()


@pytest.mark.parametrize(
    "payload",
    [
        b"BAD!",
        b"EOM3" + struct.pack("!I", 0),
        b"EOM3" + struct.pack("!I", 256001),
        b"EOM3" + struct.pack("!I", 4) + b"{}",
    ],
)
def test_stream_invalid_oversized_truncated_frames_fail(payload):
    left, right = socket.socketpair()
    with left, right:
        left.sendall(payload)
        left.shutdown(socket.SHUT_WR)
        with pytest.raises(ChatTransportError):
            receive_chat_stream(right, deadline=monotonic() + 3)
