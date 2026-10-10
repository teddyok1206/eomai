"""Small application-owned ports for optional, already-authorized candidate ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
)


@dataclass(frozen=True)
class EmbeddingRankerProvenance:
    """The exact recipe behind scores; fake backends cannot masquerade as a real model."""

    kind: Literal["PINNED_MODEL", "TEST_ONLY"]
    model_spec: LocalEmbeddingModelSpec | None

    def __post_init__(self) -> None:
        if self.kind not in {"PINNED_MODEL", "TEST_ONLY"} or (
            (self.kind == "PINNED_MODEL") != (self.model_spec is not None)
        ):
            raise ValueError("embedding model provenance is inconsistent")
        if self.model_spec is not None:
            if not isinstance(self.model_spec, LocalEmbeddingModelSpec):
                raise ValueError("embedding model provenance lacks a typed recipe")
            LocalEmbeddingModelSpec.model_validate(self.model_spec.model_dump(mode="json"))


@dataclass(frozen=True)
class ScoredInferenceTransferProfile:
    profile: InferenceTransferProfilePointer
    cosine_similarity: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.cosine_similarity, bool)
            or not isinstance(self.cosine_similarity, (float, int))
            or not math.isfinite(self.cosine_similarity)
            or not -1.0 <= self.cosine_similarity <= 1.0
        ):
            raise ValueError("invalid cosine similarity")


class InferenceTransferCandidateRanker(Protocol):
    @property
    def provenance(self) -> EmbeddingRankerProvenance: ...

    def rank(
        self,
        query_profile: InferenceTransferProfile,
        eligible_profiles: tuple[InferenceTransferProfile, ...],
        *,
        top_k: int,
    ) -> tuple[ScoredInferenceTransferProfile, ...]:
        """Rank only exact profiles admitted by the application, not an arbitrary corpus."""
        ...


class LocalTextEmbeddingBackend(Protocol):
    @property
    def provenance(self) -> EmbeddingRankerProvenance: ...

    @property
    def dimension(self) -> int: ...

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        """Return bounded vectors in input order; errors never produce substitute vectors."""
        ...
