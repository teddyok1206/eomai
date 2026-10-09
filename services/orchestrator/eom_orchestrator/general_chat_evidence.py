"""Typed chat evidence admission without database, filesystem or process behavior."""

from __future__ import annotations

import json

from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import (
    CHAT_INPUT_SCHEMA,
    CHAT_MEMBER,
    CHAT_MESSAGE_SCHEMA,
    CHAT_RESULT_SCHEMA,
    StoredChatMessage,
    read_stored_chat_message,
)
from eom_protocol.general_chat_dispatch import ChatDispatchReceipt, read_chat_dispatch
from eom_protocol.general_chat_grounding import (
    StoredGroundedChatMessage,
    read_grounding,
)
from eom_protocol.general_chat_turn_contracts import (
    ChatInputContract,
    ChatResultContract,
    read_chat_input,
    read_chat_result_document,
)
from eom_protocol.general_chat_worker_messages import chat_worker_ticket

from eom_orchestrator.general_chat_state import ChatError


def chat_pointer(
    artifact_id: str | None,
    revision_id: str | None,
    digest: str | None,
    schema_ref: str,
) -> ArtifactMemberPointer:
    if artifact_id is None or revision_id is None or digest is None:
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return ArtifactMemberPointer(
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        sha256=digest,
        member_path=CHAT_MEMBER,
        schema_ref=schema_ref,
        media_type="application/json",
    )


def require_evidence(pointer: ArtifactMemberPointer, payload: bytes, *, schema_ref: str) -> None:
    if (
        pointer.sha256 != sha256_bytes(payload)
        or pointer.schema_ref != schema_ref
        or pointer.member_path != CHAT_MEMBER
        or pointer.media_type != "application/json"
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")


def user_evidence(
    payload: bytes, *, conversation_id: str, turn_id: str
) -> StoredChatMessage | StoredGroundedChatMessage:
    document = json.loads(payload)
    message = (
        read_grounding("Message", document, StoredGroundedChatMessage)
        if document.get("schema_version") == "general-chat-message/2.0"
        else read_stored_chat_message(payload)
    )
    if (message.conversation_id, message.turn_id, message.role) != (
        conversation_id,
        turn_id,
        "user",
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return message


def request_evidence(
    payload: bytes, *, conversation_id: str, turn_id: str, claim_id: str
) -> ChatInputContract:
    request = read_chat_input(json.loads(payload))
    if (request.conversation_id, request.turn_id, request.claim_id) != (
        conversation_id,
        turn_id,
        claim_id,
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return request


def result_evidence(
    payload: bytes,
    *,
    conversation_id: str,
    turn_id: str,
    claim_id: str,
    request_sha256: str,
    expected_status: str,
) -> ChatResultContract:
    # Final worker admission uses the JSON Schema reader with its pinned request.
    # This projection reads already-admitted immutable evidence and still binds all identities.
    result = read_chat_result_document(json.loads(payload))
    if (
        result.conversation_id,
        result.turn_id,
        result.claim_id,
        result.request_sha256,
        result.status,
    ) != (
        conversation_id,
        turn_id,
        claim_id,
        request_sha256,
        expected_status,
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return result


def dispatch_evidence(
    payload: bytes, *, request: ChatInputContract, input_pointer: ArtifactMemberPointer
) -> ChatDispatchReceipt:
    try:
        receipt = read_chat_dispatch(json.loads(payload))
        if receipt.input != input_pointer or receipt.ticket != chat_worker_ticket(
            request, policy_sha256=receipt.identity.policy.sha256
        ):
            raise ValueError("dispatch does not bind exact canonical request")
        return receipt
    except Exception:
        raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None


__all__ = [
    "CHAT_INPUT_SCHEMA",
    "CHAT_MESSAGE_SCHEMA",
    "CHAT_RESULT_SCHEMA",
    "chat_pointer",
    "dispatch_evidence",
    "request_evidence",
    "require_evidence",
    "result_evidence",
    "user_evidence",
]
