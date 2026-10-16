"""Owned-turn read only: no public-corpus query, enrollment, dispatch or publication."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    build_private_chat_query_basis,
    private_chat_query_text_sha256,
)
from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_MESSAGE_SCHEMA
from eom_protocol.general_chat_grounding import GROUNDED_MESSAGE_SCHEMA

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_evidence import chat_pointer, require_evidence, user_evidence
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import ChatError


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatQuery:
    """Temporary bounded text at the canonical read boundary, not DB/wire/corpus data."""

    basis: PrivateChatQueryBasis
    text: str

    def __post_init__(self) -> None:
        value = PrivateChatQueryBasis.model_validate(raw_similarity_contract_value(self.basis))
        if value.query_text_sha256 != private_chat_query_text_sha256(self.text):
            raise ValueError("private Chat projection differs from its pinned text hash")


def _owned_message_hint(
    repository: GeneralChatRepository, *, actor_id: str, conversation_id: str, turn_id: str
) -> ArtifactMemberPointer:
    with repository.read_snapshot() as session:
        repository.require_actor(session, actor_id)
        repository.owned(session, actor_id, conversation_id)
        turn = repository.turn(session, turn_id)
        if turn.conversation_id != conversation_id:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return chat_pointer(
            turn.input_artifact_id,
            turn.input_revision_id,
            turn.input_sha256,
            CHAT_MESSAGE_SCHEMA,
        )


def read_owned_private_chat_query(
    repository: GeneralChatRepository,
    evidence: ChatEvidencePort,
    *,
    actor_id: str,
    conversation_id: str,
    turn_id: str,
) -> PreparedPrivateChatQuery:
    """Reuse owner authorization, one exact Artifact read, then a fresh ownership fence.

    The authenticated owner supplies actor_id. This library leaf is not an exposed
    worker tool or a grant to search any public Item/profile/Graph index.
    """
    hint = _owned_message_hint(
        repository, actor_id=actor_id, conversation_id=conversation_id, turn_id=turn_id
    )
    try:
        pointers = evidence.resolve_family((hint,))
        if type(pointers) is not tuple or len(pointers) != 1:
            raise ValueError("message family resolution differs")
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointers[0]))
        if pointer.schema_ref not in {CHAT_MESSAGE_SCHEMA, GROUNDED_MESSAGE_SCHEMA} or (
            pointer.model_copy(update={"schema_ref": CHAT_MESSAGE_SCHEMA}) != hint
        ):
            raise ValueError("resolved message pointer differs")
        payloads = evidence.read((pointer,))
        if type(payloads) is not tuple or len(payloads) != 1:
            raise ValueError("message member read differs")
        payload = payloads[0]
        if type(payload) is not bytes or not 0 < len(payload) <= 256000:
            raise ValueError("message member byte budget differs")
        require_evidence(pointer, payload, schema_ref=pointer.schema_ref)
        message = user_evidence(payload, conversation_id=conversation_id, turn_id=turn_id)
        expected_schema = (
            CHAT_MESSAGE_SCHEMA
            if message.schema_version == "general-chat-message/1.0"
            else GROUNDED_MESSAGE_SCHEMA
        )
        if pointer.schema_ref != expected_schema or canonical_json_bytes(message) != payload:
            raise ValueError("message schema or canonical bytes differ")
        result = PreparedPrivateChatQuery(
            basis=build_private_chat_query_basis(
                conversation_id=conversation_id,
                turn_id=turn_id,
                message=pointer,
                text=message.text,
            ),
            text=message.text,
        )
    except Exception:
        raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
    # Do not reuse the old repeatable-read snapshot to claim current revocation safety.
    if hint != _owned_message_hint(
        repository, actor_id=actor_id, conversation_id=conversation_id, turn_id=turn_id
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return result
