"""Native read-intent/replay boundary; synthetic data, zero model or DB/NAS calls."""

from __future__ import annotations

import json
import os
from threading import Thread

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_rag_broker import ChatRagToolBroker, rag_tool_knowledge
from eom_orchestrator.general_chat_rag_native import (
    RAG_CHAT_INSTRUCTIONS,
    NativeRagChatTools,
    native_rag_tools,
    rag_chat_output_schema,
    rag_chat_text,
)
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer
from eom_protocol.general_chat_grounding import (
    ChatKnowledgeCatalogReply,
    ChatKnowledgeSelection,
    chat_knowledge_context,
)
from eom_protocol.general_chat_rag_knowledge import ChatRagCatalogReply
from eom_protocol.general_chat_rag_tools import ChatToolRequestV2
from eom_protocol.general_chat_rag_turn import validate_rag_citations
from eom_protocol.general_chat_turn_contracts import read_chat_input, read_chat_result
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerExecute,
    ChatWorkerRequest,
    ChatWorkerTicket,
    chat_worker_ticket,
    read_chat_worker_request,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from tests.unit.general_chat_rag_fixtures import HASH, context, request, result, scope, source
from tests.unit.test_general_chat_agent_search import (
    RPC,
    Evidence,
    Knowledge,
    arguments,
    read_command,
    tool_events,
)
from tests.unit.test_general_chat_grounding_contract import context as item_context
from tests.unit.test_general_chat_native import Channel, answer_item, event, final_event, session

ACTOR = "operator_" + "1" * 32
RAG_ARGUMENTS = {"terms": ["에너지"], "source_classes": ["TEXTBOOK"]}


class Catalog(Knowledge):
    def __init__(self):
        super().__init__()
        self.rag_calls = []
        self.rag_value = context()
        self.rag_failure = None
        self.outcome = self.outcome.model_copy(update={"snapshot": scope().snapshot})

    def resolve(self, **values):
        self.calls.append(("read", values))
        assert values["selection"] == ChatKnowledgeSelection(
            references=read_command().arguments.references,
            snapshot=scope().snapshot,
        )
        return ChatKnowledgeCatalogReply(
            status="SUCCEEDED",
            context=pinned_item_context(),
            agent_state=None,
            error_code=None,
        )

    def rag(self, query):
        self.rag_calls.append(query)
        if self.rag_failure is not None:
            raise self.rag_failure
        return ChatRagCatalogReply(
            status="EMPTY" if self.rag_value is None else "SUCCEEDED",
            scope=query.command.scope,
            context=self.rag_value,
            error_code=None,
        )


def pinned_item_context():
    old = item_context()
    return chat_knowledge_context(
        selection=old.selection.model_copy(update={"snapshot": scope().snapshot}),
        sources=old.sources,
        limitations=old.limitations,
    )


class Port:
    def __init__(self, prepared=None, guard=None):
        self.prepared = request() if prepared is None else prepared
        self.catalog, self.evidence = Catalog(), Evidence()
        self.ticket = ChatWorkerTicket(
            conversation_id=self.prepared.conversation_id,
            turn_id=self.prepared.turn_id,
            claim_id=self.prepared.claim_id,
            request_sha256=sha256_bytes(
                canonical_json_bytes(self.prepared.model_dump(mode="json"))
            ),
            policy_sha256=HASH,
        )
        self.broker = ChatRagToolBroker(
            rpc_request_id=RPC,
            ticket=self.ticket,
            prepared=self.prepared,
            actor_guard=(lambda: ACTOR) if guard is None else guard,
            knowledge=self.catalog,
            rag_knowledge=self.catalog,
            evidence=self.evidence,
        )

    def call(self, command):
        return self.broker.execute(
            ChatToolRequestV2.model_validate(
                {
                    "rpc_request_id": RPC,
                    "ticket": self.ticket,
                    "sequence": self.broker.transcript.sequence + 1,
                    "command": command,
                }
            )
        )


def answer(*keys):
    value = result(request(knowledge=context())).answer.model_dump(mode="json")
    value["answer_sections"][0]["citation_keys"] = list(keys or ("R1",))
    return canonical_json_bytes(value).decode()


def test_native_definitions_are_closed_and_local_output_schema():
    specs = native_rag_tools()
    assert [tool["name"] for tool in specs] == [
        "search_eom_items",
        "read_eom_items",
        "retrieve_eom_knowledge",
    ]
    for tool in specs:
        Draft202012Validator.check_schema(tool["inputSchema"])
    schema = rag_chat_output_schema()
    Draft202012Validator(schema).validate(json.loads(answer()))
    assert "You have no tools, file access, live search" not in RAG_CHAT_INSTRUCTIONS
    assert "APPROVED ANALYSIS TEXT" in RAG_CHAT_INSTRUCTIONS
    assert "no shell" in RAG_CHAT_INSTRUCTIONS
    text = json.loads(rag_chat_text(request(knowledge=context())))
    assert text["authorized_rag_analysis"] == context().model_dump(mode="json")
    assert "actor_id" not in text and "permissions" not in text["authorized_rag_scope"]


def test_native_retrieval_and_canonical_replay_cite_only_actual_sources():
    port = Port()
    native = NativeRagChatTools(port.prepared, port)
    outcome = json.loads(native.call("retrieve_eom_knowledge", RAG_ARGUMENTS))
    assert outcome["rag_context"] == context().model_dump(mode="json")
    assert port.catalog.rag_calls[0].actor_id == ACTOR
    completed = native.result(reply=answer(), failure=None)
    resolved = rag_tool_knowledge(port.prepared, completed, port.evidence)
    assert resolved.rag == context() and resolved.item is None
    assert resolved.rag_contexts == (context(),)
    receipt = validate_rag_citations(port.prepared, completed, item=None, rag=resolved.rag)
    assert receipt.used_source_keys == ("R1",)
    assert receipt.verified_rag_references == (source().reference,)
    assert receipt.verified_references == ()


def test_item_rag_interleaving_preserves_scope_and_native_result_pins():
    port = Port()
    native = NativeRagChatTools(port.prepared, port)
    native.call("search_eom_items", arguments().model_dump(mode="json"))
    native.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
    native.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
    completed = native.result(reply=answer("S1", "R1"), failure=None)
    resolved = rag_tool_knowledge(port.prepared, completed, port.evidence)
    assert resolved.item == pinned_item_context() and resolved.rag == context()
    assert [reply.record.request.sequence for reply in native.records] == [1, 2, 3]
    assert len(resolved.selections) == 1
    assert [kind for kind, _ in port.catalog.calls] == ["search", "read"]


def test_prepared_followup_reuses_exact_sources_without_new_tool_calls():
    prepared = request(knowledge=context())
    port = Port(prepared)
    native = NativeRagChatTools(prepared, port)
    completed = native.result(reply=answer(), failure=None)
    resolved = rag_tool_knowledge(prepared, completed, port.evidence)
    assert resolved.rag == context() and not completed.tool_records
    assert resolved.rag_contexts == (context(),)
    assert not port.catalog.rag_calls and not port.evidence.payloads


def test_empty_second_query_does_not_erase_first_evidence_and_read_limit_shortcuts():
    port = Port()
    native = NativeRagChatTools(port.prepared, port)
    native.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
    port.catalog.rag_value = None
    assert json.loads(native.call("retrieve_eom_knowledge", RAG_ARGUMENTS))["status"] == "EMPTY"
    assert (
        json.loads(native.call("retrieve_eom_knowledge", RAG_ARGUMENTS))["error_code"]
        == "CHAT_KNOWLEDGE_READ_LIMIT"
    )
    assert len(port.catalog.rag_calls) == 2
    resolved = rag_tool_knowledge(
        port.prepared, native.result(reply=answer(), failure=None), port.evidence
    )
    assert resolved.rag == context()


@pytest.mark.parametrize(
    "code,expected",
    [
        ("GENERAL_CHAT_FORBIDDEN", "CHAT_KNOWLEDGE_FORBIDDEN"),
        ("GENERAL_CHAT_POINTER_INVALID", "CHAT_KNOWLEDGE_POINTER_INVALID"),
        ("GENERAL_CHAT_APPLICATION_UNAVAILABLE", "CHAT_KNOWLEDGE_UNAVAILABLE"),
    ],
)
def test_denied_pointer_or_unavailable_reads_never_offer_partial_evidence(code, expected):
    port = Port()
    port.catalog.rag_failure = ChatError(code)
    native = NativeRagChatTools(port.prepared, port)
    outcome = json.loads(native.call("retrieve_eom_knowledge", RAG_ARGUMENTS))
    assert outcome["error_code"] == expected
    assert outcome["rag_context"] is None and outcome["snapshot"] is None
    with pytest.raises(ValueError):
        native.result(reply=answer(), failure=None)


def test_missing_scope_has_no_catalog_read_and_item_tools_still_available():
    prepared = request().model_copy(update={"rag_scope": None})
    port = Port(prepared)
    native = NativeRagChatTools(prepared, port)
    assert (
        json.loads(native.call("retrieve_eom_knowledge", RAG_ARGUMENTS))["error_code"]
        == "CHAT_KNOWLEDGE_UNAVAILABLE"
    )
    assert not port.catalog.rag_calls
    native.call("search_eom_items", arguments().model_dump(mode="json"))
    assert len(port.catalog.calls) == 1


@pytest.mark.parametrize("extra", ["actor_id", "role", "permissions", "policy", "snapshot", "path"])
def test_model_cannot_supply_authority_or_storage_path(extra):
    port = Port()
    native = NativeRagChatTools(port.prepared, port)
    with pytest.raises((ValueError, SchemaError)):
        native.call("retrieve_eom_knowledge", {**RAG_ARGUMENTS, extra: "injected"})
    assert not port.catalog.rag_calls and not port.evidence.payloads


def test_guard_revocation_after_read_prevents_publication():
    guards = iter((ACTOR, "operator_" + "9" * 32))
    port = Port(guard=lambda: next(guards))
    native = NativeRagChatTools(port.prepared, port)
    with pytest.raises(ChatError, match="FORBIDDEN"):
        native.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
    assert len(port.catalog.rag_calls) == 1 and not port.evidence.payloads


@pytest.mark.parametrize("patch", ["hash", "claim", "sequence", "rpc", "scope", "text"])
def test_cross_turn_or_forged_canonical_records_are_rejected(patch):
    port = Port()
    native = NativeRagChatTools(port.prepared, port)
    native.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
    native.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
    completed = native.result(reply=answer(), failure=None)
    pointer = completed.tool_records[1]
    if patch == "hash":
        port.evidence.payloads[pointer] += b" "
    else:
        value = json.loads(port.evidence.payloads[pointer])
        if patch == "claim":
            value["request"]["ticket"]["claim_id"] = "chatclaim_" + "9" * 32
        elif patch == "sequence":
            value["request"]["sequence"] = 6
        elif patch == "rpc":
            value["request"]["rpc_request_id"] = "chatwrpc_" + "9" * 32
        elif patch == "scope":
            value["outcome"]["rag_context"]["scope"]["policy"]["sha256"] = "sha256:" + "9" * 64
        else:
            value["outcome"]["rag_context"]["sources"][0]["text"] = "tampered"
        payload = canonical_json_bytes(value)
        changed = pointer.model_copy(update={"sha256": sha256_bytes(payload)})
        port.evidence.payloads[changed] = payload
        completed = completed.model_copy(
            update={"tool_records": (completed.tool_records[0], changed)}
        )
    with pytest.raises((ValueError, ChatError, SchemaError)):
        rag_tool_knowledge(port.prepared, completed, port.evidence)


@pytest.mark.parametrize("early_events", [False, True])
def test_real_native_rpc_adapter_exposes_three_tools_and_bound_r_citation(early_events):
    events = tool_events("retrieve_eom_knowledge", RAG_ARGUMENTS, "rag1")
    events += [event("item/completed", item=answer_item(text=answer())), final_event()]
    channel = Channel(events)
    channel.early_events = early_events
    native, _ = session(channel)
    port = Port()
    completed = native.answer(port.prepared, tools=port)
    assert completed.status == "SUCCEEDED" and len(completed.tool_records) == 1
    started = next(
        value["params"] for value in channel.sent if value.get("method") == "thread/start"
    )
    assert len(started["dynamicTools"]) == 3
    assert started["environments"] == [] and started["runtimeWorkspaceRoots"] == []
    outputs = [value for value in channel.sent if value.get("id") == "request-rag1"]
    assert outputs[0]["result"]["success"] is True
    assert native.ready


def test_native_forged_answer_source_fails_without_inference_replay():
    events = tool_events("retrieve_eom_knowledge", RAG_ARGUMENTS, "rag1")
    events += [event("item/completed", item=answer_item(text=answer("R2"))), final_event()]
    native, channel = session(Channel(events))
    port = Port()
    completed = native.answer(port.prepared, tools=port)
    assert completed.status == "FAILED" and not completed.reply
    assert len(completed.tool_records) == 1 and len(port.catalog.rag_calls) == 1
    assert channel.closed


def test_invalid_native_tool_arguments_become_a_known_failure_without_dispatch_or_retry(caplog):
    forged = {**RAG_ARGUMENTS, "actor_id": "operator_" + "f" * 32}
    native, channel = session(Channel(tool_events("retrieve_eom_knowledge", forged, "rag1")))
    port = Port()
    completed = native.answer(port.prepared, tools=port)
    assert completed.status == "FAILED" and completed.failure_code == "CODEX_PROTOCOL_INVALID"
    assert not completed.reply and not completed.tool_records and not port.catalog.rag_calls
    assert channel.closed
    assert "stage=ARGUMENTS category=schema validator=additionalProperties" in caplog.text
    assert "operator_" + "f" * 32 not in caplog.text


def test_v4_worker_envelope_and_policy_do_not_reinterpret_v3_bytes():
    selected = source_chat_worker_policy(model="synthetic-model", protocol=4)
    assert selected.schema_version.endswith("/4.0")
    assert selected.rag_prompt_sha256 == sha256_bytes(RAG_CHAT_INSTRUCTIONS.encode())
    assert read_chat_input(request().model_dump(mode="json")) == request()
    envelope = ChatWorkerRequest(
        schema_version="general-chat-worker-request/4.0",
        request_id=RPC,
        policy_sha256=selected.sha256,
        command=ChatWorkerExecute(boot_id="chatboot_" + "1" * 32, turn=request()),
    )
    assert read_chat_worker_request(envelope.model_dump(mode="json")) == envelope
    old = envelope.model_dump(mode="json")
    old["schema_version"] = "general-chat-worker-request/3.0"
    with pytest.raises(SchemaError):
        read_chat_worker_request(old)
    assert source_chat_worker_policy(model="synthetic-model").rag_prompt_sha256 is None
    assert "rag_prompt_sha256" not in source_chat_worker_policy(model="synthetic-model").model_dump(
        mode="json"
    )


def test_real_v4_duplex_handoff_lookup_replays_output_without_generation(tmp_path):
    selected = source_chat_worker_policy(model="synthetic-model", protocol=4)
    catalog, evidence = Catalog(), Evidence()

    class SyntheticNative:
        calls = 0

        def require_admission(self, policy):
            assert policy == selected

        def answer(self, prepared, *, tools):
            self.calls += 1
            exchange = NativeRagChatTools(prepared, tools)
            exchange.call("search_eom_items", arguments().model_dump(mode="json"))
            exchange.call("retrieve_eom_knowledge", RAG_ARGUMENTS)
            exchange.call("read_eom_items", read_command().arguments.model_dump(mode="json"))
            return exchange.result(reply=answer("S1", "R1"), failure=None)

    def broker(envelope):
        prepared = envelope.command.turn
        return ChatRagToolBroker(
            rpc_request_id=envelope.request_id,
            ticket=chat_worker_ticket(prepared, policy_sha256=selected.sha256),
            prepared=prepared,
            actor_guard=lambda: ACTOR,
            knowledge=catalog,
            rag_knowledge=catalog,
            evidence=evidence,
        )

    runtime, local = tmp_path / "rpc", tmp_path / "handoff"
    runtime.mkdir(mode=0o750)
    local.mkdir(mode=0o700)
    native = SyntheticNative()
    endpoint = ChatSocketEndpoint(runtime / "worker.sock", os.getuid(), os.getgid())
    with ChatLocalHandoff(local, worker_uid=os.getuid()) as handoff:
        application = ChatWorkerApplication(
            native,
            handoff,
            policy=selected,
            boot_id="chatboot_" + "1" * 32,
        )
        with ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=os.getuid()) as server:
            thread = Thread(target=server.serve)
            thread.start()
            try:
                client = ChatWorkerClient(endpoint=endpoint, policy=selected, tools=broker)
                client.check_admission()
                prepared = request()
                completed = client.answer(prepared)
                assert completed.status == "SUCCEEDED" and len(completed.tool_records) == 3
                assert (
                    read_chat_result(completed.model_dump(mode="json"), request=prepared)
                    == completed
                )
                ticket = chat_worker_ticket(prepared, policy_sha256=selected.sha256)
                assert client.lookup(ticket).result == completed
                assert client.answer(prepared) == completed
                assert native.calls == 1 and len(catalog.rag_calls) == 1
                resolved = rag_tool_knowledge(prepared, completed, evidence)
                assert resolved.rag == context() and resolved.item == pinned_item_context()
            finally:
                server.stop()
                thread.join(3)
                assert not thread.is_alive()
