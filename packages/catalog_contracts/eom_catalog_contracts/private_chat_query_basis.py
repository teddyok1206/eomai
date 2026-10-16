"""Exact private user-message references; neither corpus membership nor authority."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

MAX_PRIVATE_CHAT_BASIS_BYTES = 4096


class PrivateChatQueryBasis(FrozenModel):
    """Pin one question without copying its text or claiming an approved Item profile."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["system-rag-private-chat-query-basis/1.0"]
    basis: Literal["PRIVATE_CHAT_QUERY"]
    consumer_purpose: Literal["GENERAL_CHAT_READ"]
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    message: ArtifactMemberPointer
    query_recipe: Literal["private-chat-exact-user-text/1.0"]
    query_text_sha256: Sha256
    basis_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-private-chat-query-basis", MAX_PRIVATE_CHAT_BASIS_BYTES
        )

    @model_validator(mode="after")
    def exact_hash(self) -> PrivateChatQueryBasis:
        if self.basis_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"basis_sha256"})
        ):
            raise ValueError("private Chat basis canonical hash differs")
        return self


def private_chat_query_text_sha256(text: str) -> str:
    """Fixed exact-user-text recipe; never normalize, trim, infer or truncate."""
    if type(text) is not str or not 1 <= len(text) <= 16000 or not text.strip() or "\x00" in text:
        raise ValueError("private Chat query text is invalid")
    return sha256_bytes(text.encode("utf-8"))


def build_private_chat_query_basis(
    *, conversation_id: str, turn_id: str, message: ArtifactMemberPointer, text: str
) -> PrivateChatQueryBasis:
    """Create a pure value from owner-resolved inputs, never resolve or authorize them."""
    document = {
        "schema_version": "system-rag-private-chat-query-basis/1.0",
        "basis": "PRIVATE_CHAT_QUERY",
        "consumer_purpose": "GENERAL_CHAT_READ",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "message": raw_similarity_contract_value(message),
        "query_recipe": "private-chat-exact-user-text/1.0",
        "query_text_sha256": private_chat_query_text_sha256(text),
    }
    return PrivateChatQueryBasis.model_validate(
        {**document, "basis_sha256": content_sha256(document)}
    )
