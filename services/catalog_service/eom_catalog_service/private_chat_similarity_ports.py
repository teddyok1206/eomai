"""Owner-local private and official-source read values; never authority from wire data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_private_chat_query import (
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
)
from eom_catalog_contracts.private_chat_query_basis import PrivateChatQueryBasis
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.similarity_context_ports import PreparedSimilaritySource


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatSimilarity:
    """Temporary owned text and current official source pointers at the read boundary."""

    request_sha256: str
    query_basis: PrivateChatQueryBasis
    query_text: str
    sources: tuple[PreparedSimilaritySource, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedPrivateChatQueryRead:
    """Owner-verified committed file set after actual session/purpose/native admission."""

    request: EmbeddingPrivateChatQueryInput
    result: EmbeddingPrivateChatQueryResult
    result_member: ArtifactMemberPointer
    shard_member: ArtifactMemberPointer
    binary: bytes


@dataclass(frozen=True, slots=True)
class PrivateChatQueryUnavailable:
    reason: Literal["QUERY_NOT_OFFERED", "INPUT_OVERFLOW"]


class PrivateChatSimilarityReadPort(Protocol):
    """Current private ownership AND official Catalog authority, not a default provider."""

    def prepare_private_chat_similarity(
        self, caller: EmbeddingRegistryCaller, request: PrivateChatSimilarityRequest
    ) -> PreparedPrivateChatSimilarity: ...

    def resolve_private_chat_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> VerifiedPrivateChatQueryRead | PrivateChatQueryUnavailable: ...

    def read_private_chat_similarity_index(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]: ...

    def reauthorize_private_chat_similarity(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> None:
        """Fresh ownership/session and complete public source/index scope before delivery."""
        ...
