"""Successor transport and representative answers without model consumption."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_orchestrator.general_chat_grounded_prompt import (
    grounded_chat_output_schema,
    grounded_chat_result,
)
from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_protocol.general_chat_grounding import (
    ChatAgentState,
    read_grounded_chat_input,
    validate_chat_citations,
)
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerExecute,
    ChatWorkerLookup,
    ChatWorkerRequest,
    chat_worker_ticket,
    read_chat_worker_reply,
    read_chat_worker_request,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from tests.unit.test_general_chat_grounding_contract import request
from tests.unit.test_general_chat_worker_handoff import BOOT


def agent_request():
    prepared = request().model_copy(
        update={
            "knowledge": None,
            "agent_state": ChatAgentState(
                observed_at=datetime(2026, 10, 8, tzinfo=UTC),
                permissions=("general_chat:read", "item:read"),
                item_count=12,
                graph_node_count=40,
                workflow_counts=(),
            ),
        }
    )
    return read_grounded_chat_input(prepared.model_dump(mode="json"))


def agent_result(prepared=None):
    prepared = prepared or agent_request()
    return grounded_chat_result(
        prepared,
        reply=(
            '{"answer_sections":[{"section_id":"section_1",'
            '"markdown":"EOM의 문항 미리보기에서 자료를 확인할 수 있습니다.",'
            '"support_kind":"GENERAL_KNOWLEDGE","citation_keys":[]}],"limitations":[]}'
        ),
        failure=None,
    )


def test_plain_representative_snapshot_cannot_claim_internal_citations():
    prepared = agent_request()
    result = agent_result(prepared)
    receipt = validate_chat_citations(prepared, result)
    assert receipt.verified_references == receipt.used_source_keys == ()
    schema = grounded_chat_output_schema(prepared)
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(result.answer.model_dump(mode="json"))
    with pytest.raises(ValueError, match="observation hash"):
        validate_chat_citations(
            prepared, result.model_copy(update={"agent_state_sha256": "sha256:" + "f" * 64})
        )


def test_v2_worker_executes_once_and_recovers_exact_grounded_result(tmp_path):
    selected = source_chat_worker_policy(model="synthetic-model")
    root = tmp_path / "handoff"
    root.mkdir(mode=0o700)
    handoff = ChatLocalHandoff(root, worker_uid=os.getuid())
    calls = []

    class Native:
        def require_admission(self, policy):
            assert policy == selected

        def answer(self, turn):
            calls.append(turn)
            return agent_result(turn)

    worker = ChatWorkerApplication(Native(), handoff, policy=selected, boot_id=BOOT)
    prepared = agent_request()
    execute = ChatWorkerRequest(
        schema_version="general-chat-worker-request/2.0",
        request_id="chatwrpc_" + uuid4().hex,
        policy_sha256=selected.sha256,
        command=ChatWorkerExecute(boot_id=BOOT, turn=prepared),
    )
    first = worker.handle(execute)
    read_chat_worker_reply(first.model_dump(mode="json"), request=execute)
    assert first.schema_version == "general-chat-worker-reply/2.0"
    assert worker.handle(execute).value == first.value
    lookup = execute.model_copy(
        update={
            "command": ChatWorkerLookup(
                ticket=chat_worker_ticket(prepared, policy_sha256=selected.sha256)
            )
        }
    )
    assert worker.handle(lookup).value == first.value
    assert calls == [prepared]
    with pytest.raises(SchemaError):
        read_chat_worker_request(
            execute.model_copy(
                update={"schema_version": "general-chat-worker-request/1.0"}
            ).model_dump(mode="json")
        )
    handoff.close()
