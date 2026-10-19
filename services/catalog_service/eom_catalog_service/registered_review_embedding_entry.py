"""Pure registered-review inputs for the existing incremental encoding planner.

This internal value is not a source authorization, wire protocol or publication
contract. The Catalog resolver owns provenance and current access. Source-plan1
and index1 remain closed to profile1 until a compatible successor is installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    ExperimentMetadataField,
    ExperimentView,
)
from eom_catalog_contracts.registered_review_profile import (
    RegisteredReviewProfile,
    registered_review_profile_text,
)


@dataclass(frozen=True, slots=True)
class RegisteredReviewEmbeddingEntry:
    """Materialized values only; no file paths, model backend or mutable state."""

    profile: RegisteredReviewProfile
    content: CanonicalExperimentItemText | None
    metadata: tuple[ExperimentMetadataField, ...] = ()


def validate_registered_review_embedding_entry(
    entry: RegisteredReviewEmbeddingEntry,
) -> RegisteredReviewEmbeddingEntry:
    """Revalidate nested frozen values; no forged copy is an authority boundary."""
    profile = RegisteredReviewProfile.model_validate(raw_similarity_contract_value(entry.profile))
    content = (
        None
        if entry.content is None
        else CanonicalExperimentItemText.model_validate(
            raw_similarity_contract_value(entry.content)
        )
    )
    if not isinstance(entry.metadata, tuple) or len(entry.metadata) > 32:
        raise ValueError("registered-review metadata exceeds its immutable bound")
    metadata = tuple(
        ExperimentMetadataField.model_validate(raw_similarity_contract_value(value))
        for value in entry.metadata
    )
    source = profile.source_basis.source.artifact_member
    if content is not None and content.original_source != source:
        raise ValueError("registered-review question text source differs")
    keys = tuple((value.key, value.value, value.basis) for value in metadata)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("registered-review metadata must be sorted and unique")
    if any(
        value.basis != "ORIGINAL_ITEM" or value.source_sha256 != source.sha256 for value in metadata
    ):
        raise ValueError("registered-review metadata must cite its exact original Item")
    return RegisteredReviewEmbeddingEntry(profile=profile, content=content, metadata=metadata)


def registered_review_embedding_view_text(
    entry: RegisteredReviewEmbeddingEntry, view: ExperimentView
) -> str | None:
    """Preserve complete conclusions; never include internal IDs as numerical features.

    The historical view name CONCRETE_FACETS denotes the concrete-profile view,
    not an assertion that a review conclusion contains a decisive inference.
    Missing content or metadata remains unavailable/empty for the common planner.
    Callers first validate this internal entry, just as for legacy staged values.
    """
    if view == "CONTENT_ONLY":
        return None if entry.content is None else entry.content.text
    if view == "CONCRETE_FACETS":
        return registered_review_profile_text(entry.profile)
    if view == "METADATA_ONLY":
        return "\n".join(f"{value.key}: {value.value}" for value in entry.metadata)
    raise ValueError("INFERENCE_EXPERIMENT_VIEW_INVALID")
