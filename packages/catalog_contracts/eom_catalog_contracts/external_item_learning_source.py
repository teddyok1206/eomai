"""Pinned source-only input for a future creative Item analysis workflow.

This is an authority-free value: Catalog must resolve and reauthorize every
pointer before Orchestrator stages any worker input. It is not an Item Revision.
"""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_preview import ExternalItemPreviewManifest
from eom_catalog_contracts.models import FrozenModel, Sha256

EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA = "external-item-learning-source-v1"
EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA_REF = "eom://schemas/external-item/learning-source/1.0"


class ExternalItemLearningSource(FrozenModel):
    """One exact archive row and its validated PDF derivative, never latest."""

    schema_version: Literal["external-item-learning-source/1.0"] = (
        "external-item-learning-source/1.0"
    )
    import_id: str = Field(pattern=r"^extimport_[0-9a-f]{32}$")
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    origin_kind: Literal["PAST_EXAM_VARIATION", "FREE_AUTHORING"]
    observation_sha256: Sha256
    selected_edition: int = Field(strict=True, ge=2, le=3)
    preview_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    preview_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    preview_manifest: ExternalItemPreviewManifest
    input_sha256: Sha256

    @model_validator(mode="after")
    def exact_preview_and_hash(self) -> Self:
        if (
            self.source_id != self.preview_manifest.source_id
            or self.source_revision_id != self.preview_manifest.source_revision_id
            or self.selected_edition != self.preview_manifest.edition
        ):
            raise ValueError("creative learning source differs from its preview")
        if self.input_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"input_sha256"})
        ):
            raise ValueError("creative learning input hash differs")
        return self
