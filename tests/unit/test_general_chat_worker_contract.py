from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.general_chat import read_chat_turn_input, read_chat_turn_result
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def request_document():
    messages = [{"role": "user", "text": "안녕하세요"}]
    return {
        "protocol_version": "general-chat-turn/1.0",
        "conversation_id": "chat_" + "1" * 32,
        "turn_id": "chatturn_" + "2" * 32,
        "claim_id": "chatclaim_" + "3" * 32,
        "prompt_revision": "general-chat/1.0.0",
        "context_sha256": content_sha256(messages),
        "messages": messages,
    }


def result_document(request):
    return {
        **{
            key: request[key]
            for key in (
                "protocol_version",
                "conversation_id",
                "turn_id",
                "claim_id",
                "prompt_revision",
            )
        },
        "request_sha256": content_sha256(request),
        "status": "SUCCEEDED",
        "reply": "안녕하세요. 무엇을 도와드릴까요?",
        "failure_code": None,
    }


def test_input_result_schema_and_frozen_models_share_pinned_identity():
    document = request_document()
    request = read_chat_turn_input(document)
    result = read_chat_turn_result(result_document(document), request=request)
    assert result.status == "SUCCEEDED"
    assert result.claim_id == request.claim_id
    assert canonical_json_bytes(request.model_dump(mode="json")) == canonical_json_bytes(document)
    with pytest.raises(ValidationError):
        request.claim_id = "chatclaim_" + "4" * 32
    for name in ("input", "result"):
        leaf = f"general-chat-turn-{name}.schema.json"
        assert (ROOT / "schemas/general-chat" / leaf).read_bytes() == (
            ROOT / "packages/protocol/eom_protocol/schemas" / leaf
        ).read_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversation_id", "chat_" + "4" * 32),
        ("turn_id", "chatturn_" + "4" * 32),
        ("claim_id", "chatclaim_" + "4" * 32),
        ("request_sha256", "sha256:" + "f" * 64),
    ],
)
def test_other_conversation_stale_claim_or_modified_request_result_rejected(field, value):
    document = request_document()
    request = read_chat_turn_input(document)
    result = result_document(document)
    result[field] = value
    with pytest.raises(ValueError):
        read_chat_turn_result(result, request=request)


def test_modified_context_rejected_even_when_schema_valid():
    document = request_document()
    document["messages"][0]["text"] = "다른 질문"
    with pytest.raises(ValidationError, match="context hash mismatch"):
        read_chat_turn_input(document)


def test_context_bounded_and_must_end_with_new_user_message():
    document = request_document()
    messages = [{"role": "user", "text": "x" * 32000}] * 5
    document.update(messages=messages, context_sha256=content_sha256(messages))
    with pytest.raises(ValidationError, match="materialization budget"):
        read_chat_turn_input(document)
    messages = [{"role": "assistant", "text": "not a user turn"}]
    document.update(messages=messages, context_sha256=content_sha256(messages))
    with pytest.raises(ValidationError, match="new user message"):
        read_chat_turn_input(document)


@pytest.mark.parametrize(
    "patch",
    [
        {"reply": ""},
        {"status": "FAILED", "failure_code": "CODEX_TIMEOUT"},
        {"failure_code": "CODEX_TURN_FAILED"},
        {"native_thread_id": "caller-chosen"},
    ],
)
def test_success_cannot_include_empty_or_failed_or_internal_worker_data(patch):
    document = request_document()
    result = result_document(document)
    result.update(patch)
    with pytest.raises((SchemaError, ValidationError)):
        read_chat_turn_result(result, request=read_chat_turn_input(document))


def test_failed_result_preserves_failure_without_publishing_partial_answer():
    document = request_document()
    result = result_document(document)
    result.update(status="FAILED", reply="", failure_code="CODEX_TIMEOUT")
    validated = read_chat_turn_result(result, request=read_chat_turn_input(document))
    assert validated.failure_code == "CODEX_TIMEOUT" and not validated.reply


def test_input_and_result_do_not_declare_storage_or_worker_credentials():
    for name in ("input", "result"):
        schema = json.loads(
            (ROOT / "schemas/general-chat" / f"general-chat-turn-{name}.schema.json").read_bytes()
        )
        assert schema["additionalProperties"] is False
        assert (
            not {"owner_id", "auth", "nas_path", "database_url", "native_thread_id"}
            & schema["properties"].keys()
        )
