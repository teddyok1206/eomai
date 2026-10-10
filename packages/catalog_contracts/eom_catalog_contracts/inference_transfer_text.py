"""Pure exact profile-text value recipe, without runtime or retrieval dependencies."""

from __future__ import annotations

from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile


def concrete_profile_text(profile: InferenceTransferProfile) -> str:
    """Keep every ordered claim, including units, negation and final judgments."""
    return "\n".join(f"{claim.facet}: {claim.text}" for claim in profile.claims)
