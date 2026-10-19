"""Public compatibility imports for the shared source-plan2 staged value.

The source-phase entry now has one schema-first contract shape. It still grants
no source authority, file permission or index publication permission.
"""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.mixed_embedding_index import (
    RegisteredReviewEmbeddingEntry as RegisteredReviewEmbeddingEntry,
)
from eom_catalog_contracts.mixed_embedding_index import (
    registered_review_embedding_text as registered_review_embedding_view_text,
)

__all__ = [
    "RegisteredReviewEmbeddingEntry",
    "registered_review_embedding_view_text",
    "validate_registered_review_embedding_entry",
]


def validate_registered_review_embedding_entry(
    entry: RegisteredReviewEmbeddingEntry,
) -> RegisteredReviewEmbeddingEntry:
    return RegisteredReviewEmbeddingEntry.model_validate(raw_similarity_contract_value(entry))
