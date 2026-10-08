from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_evidence import dispatch_evidence
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_INPUT_SCHEMA, CHAT_MEMBER
from eom_protocol.general_chat_dispatch import (
    ChatDispatchReceipt,
    ChatExecutionIdentity,
    read_chat_dispatch,
)
from eom_protocol.general_chat_worker_messages import chat_worker_ticket
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_general_chat_resident import RUNTIME, staged
from tests.unit.test_general_chat_worker_handoff import BOOT, policy

ROOT = Path(__file__).resolve().parents[2]


def dispatch() -> ChatDispatchReceipt:
    request = staged(1)
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path=CHAT_MEMBER,
        schema_ref=CHAT_INPUT_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
    )
    return read_chat_dispatch(
        ChatDispatchReceipt(
            runtime_id=RUNTIME,
            identity=ChatExecutionIdentity(boot_id=BOOT, policy=policy()),
            ticket=chat_worker_ticket(request, policy_sha256=policy().sha256),
            input=pointer,
        ).model_dump(mode="json")
    )


def test_dispatch_schema_is_mirrored_offline_frozen_and_pointer_only() -> None:
    leaf = "general-chat-dispatch.schema.json"
    payload = (ROOT / "schemas/general-chat" / leaf).read_bytes()
    assert payload == (ROOT / "packages/protocol/eom_protocol/schemas" / leaf).read_bytes()
    Draft202012Validator.check_schema(json.loads(payload))
    receipt = dispatch()
    assert read_chat_dispatch(receipt.model_dump(mode="json")) == receipt
    assert {"messages", "reply", "auth", "path"}.isdisjoint(ChatDispatchReceipt.model_fields)
    with pytest.raises(ValidationError):
        receipt.runtime_id = RUNTIME
    with pytest.raises(ValidationError):
        receipt.identity.policy.model = "other"


@pytest.mark.parametrize("field", ["auth", "nas_path", "messages", "native_thread_id"])
def test_dispatch_rejects_unrequested_bodies_credentials_and_local_handles(field: str) -> None:
    document = dispatch().model_dump(mode="json")
    document[field] = "untrusted"
    with pytest.raises(SchemaError):
        read_chat_dispatch(document)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("input", "sha256", "sha256:" + "9" * 64),
        ("input", "schema_ref", "eom://schemas/general-chat/turn-result/1.0"),
        ("input", "member_path", "../other"),
        ("input", "media_type", "image/png"),
        ("ticket", "policy_sha256", "sha256:" + "9" * 64),
        ("identity", "boot_id", "chatrt_" + "1" * 32),
    ],
)
def test_dispatch_schema_and_model_guard_exact_pointer_and_execution_value(
    section: str, field: str, value: str
) -> None:
    document = dispatch().model_dump(mode="json")
    document[section][field] = value
    with pytest.raises((SchemaError, ValidationError)):
        read_chat_dispatch(document)


def test_dispatch_evidence_binds_pinned_member_revision_claim_and_request() -> None:
    receipt = dispatch()
    request = staged(1)
    payload = canonical_json_bytes(receipt.model_dump(mode="json"))
    assert dispatch_evidence(payload, request=request, input_pointer=receipt.input) == receipt
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        dispatch_evidence(payload, request=staged(2), input_pointer=receipt.input)
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        dispatch_evidence(
            payload,
            request=request,
            input_pointer=receipt.input.model_copy(
                update={"artifact_revision_id": "rev_" + "9" * 32}
            ),
        )
    for invalid in (b"{", b"[]", b"null"):
        with pytest.raises(ChatError, match="POINTER_INVALID"):
            dispatch_evidence(invalid, request=request, input_pointer=receipt.input)
