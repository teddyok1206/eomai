"""Small owner-local preparation/read values; no wire authority or runtime admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.embedding_reference_query import (
    EmbeddingReferenceQueryResult,
)
from eom_catalog_contracts.embedding_reference_query_v11 import SupportedReferenceQueryInput
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, PopulationSource
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import KnowledgeSolutionEvidencePointer
from eom_catalog_contracts.similarity_context import (
    SimilarityContext,
    SimilarityContextRequest,
    SimilarityFailureCode,
    SimilarityUnavailableReason,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    ResolvedPinnedEmbeddingIndex,
)


class SimilarityContextReadError(ValueError):
    def __init__(self, code: SimilarityFailureCode) -> None:
        self.code = code
        super().__init__(code)


def similarity_context_error_from_registry(
    error: EmbeddingRegistryError,
) -> SimilarityContextReadError:
    """Keep official registry denial/unavailability meanings at both read adapters."""
    if error.code == "EMBEDDING_REGISTRY_FORBIDDEN":
        return SimilarityContextReadError("SOURCE_ACCESS_DENIED")
    if error.code == "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE":
        return SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    return SimilarityContextReadError("SOURCE_POINTER_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedSimilaritySource:
    source: PopulationSource
    profile: InferenceTransferProfilePointer | None
    solution_evidence: KnowledgeSolutionEvidencePointer | None


@dataclass(frozen=True, slots=True)
class PreparedSimilarityContext:
    """Exact local pointers plus anchor-only text at a bounded preparation boundary."""

    request_sha256: str
    sources: tuple[PreparedSimilaritySource, ...]
    query_texts: tuple[tuple[ExperimentView, str], ...]
    graph_scores: tuple[tuple[str, int], ...] = ()
    graph_evidence: ArtifactMemberPointer | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedReferenceQueryRead:
    """A mandatory owner-resolved committed QUERY file set, never a launch request.

    The owner verifies actual caller, committed lifecycle, schema/media, raw member
    hashes, exact request derivation and genuine execution admission. Binary bytes
    exist only at this explicit bounded local numeric boundary, not DB/wire/context.
    """

    request: SupportedReferenceQueryInput
    result: EmbeddingReferenceQueryResult
    result_member: ArtifactMemberPointer
    shard_member: ArtifactMemberPointer
    binary: bytes


@dataclass(frozen=True, slots=True)
class SimilarityQueryUnavailable:
    reason: SimilarityUnavailableReason


class SimilarityContextSourceReadPort(Protocol):
    """Existing Catalog owner operations; each call uses actual current read authority."""

    def prepare_similarity_context(
        self, caller: EmbeddingRegistryCaller, request: SimilarityContextRequest
    ) -> PreparedSimilarityContext: ...

    def read_similarity_views(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]: ...

    def reauthorize_similarity_context(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> None:
        """Recheck the full exact population, including unselected/no-report sources."""
        ...


class SimilarityReferenceQueryReadPort(Protocol):
    def resolve_reference_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead | SimilarityQueryUnavailable:
        """Only admitted committed QUERY; never benchmark replay or DOCUMENT relabeling."""
        ...


class SimilarityContextReadPort(Protocol):
    """Existing common application's public read operation, not a new source authority."""

    def compose(
        self, caller: EmbeddingRegistryCaller, request: SimilarityContextRequest
    ) -> SimilarityContext: ...
