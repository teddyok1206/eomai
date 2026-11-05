"""Saved ranking metadata, never a replacement for current source authorization."""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
)
from eom_catalog_contracts.similarity_context import MAX_SIMILARITY_CONTEXT_BYTES
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection

# Preserve the complete existing context limit plus the small identity/hash carrier.
MAX_SAVED_PUBLIC_RANKING_BYTES = MAX_SIMILARITY_CONTEXT_BYTES + 4096


class CompletedPublicSimilarityRanking(FrozenModel):
    schema_version: Literal["completed-public-similarity-ranking/1.0"] = (
        "completed-public-similarity-ranking/1.0"
    )
    operator_id: str
    selection: CompletedSimilarityQuerySelection
    context: SupportedPublicSolutionSimilarityContext
    dependency_sha256: Sha256
    snapshot_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "completed-public-similarity-ranking-v1", MAX_SAVED_PUBLIC_RANKING_BYTES
        )

    @model_validator(mode="after")
    def exact_saved_result(self) -> Self:
        if (
            self.context.status == "FAILED"
            or self.context.query_execution is None
            or self.context.population is None
            or self.context.request.consumer_purpose != "ITEM_DATABASE_SEARCH"
            or self.selection.context_request_sha256 != self.context.request.request_sha256
            or self.snapshot_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"snapshot_sha256"}))
        ):
            raise ValueError("COMPLETED_PUBLIC_RANKING_INVALID")
        return self
