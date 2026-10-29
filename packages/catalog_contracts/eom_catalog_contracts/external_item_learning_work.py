"""Immutable source/page pins for one creative Item analysis worker claim.

This value records an input, not operator authority, an accepted Item, or a
permission for a worker to read Catalog/NAS directly.
"""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_learning_pages import (
    ExternalItemLearningPageSet,
    validate_external_item_learning_page_set_for_source,
)
from eom_catalog_contracts.external_item_learning_result import (
    ExternalItemLearningResult,
    validate_external_item_learning_result_for_source,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.models import FrozenModel, Sha256

EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA = "external-item-learning-work-input-v1"
EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA_REF = "eom://schemas/external-item/learning-work-input/1.0"


class ExternalItemLearningPageArtifact(FrozenModel):
    """Pinned primary member plus exact enclosing file-set manifest identity."""

    artifact_type: Literal["control_external_item_learning_pages"] = (
        "control_external_item_learning_pages"
    )
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["page-set-manifest.json"] = "page-set-manifest.json"
    schema_ref: Literal["eom://schemas/external-item/learning-page-set/1.0"] = (
        "eom://schemas/external-item/learning-page-set/1.0"
    )
    media_type: Literal["application/json"] = "application/json"
    sha256: Sha256
    file_set_manifest_sha256: Sha256


class ExternalItemLearningWorkInput(FrozenModel):
    """One exact visual/extraction input; retry never resolves a new page set."""

    schema_version: Literal["external-item-learning-work-input/1.0"] = (
        "external-item-learning-work-input/1.0"
    )
    request_id: str = Field(pattern=r"^extlearnreq_[0-9a-f]{32}$")
    source: ExternalItemLearningSource
    page_set: ExternalItemLearningPageSet
    page_artifact: ExternalItemLearningPageArtifact
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_source_and_page_artifact(self) -> Self:
        validate_external_item_learning_page_set_for_source(self.page_set, self.source)
        primary_sha256 = sha256_bytes(canonical_json_bytes(self.page_set.model_dump(mode="json")))
        if self.page_artifact.sha256 != primary_sha256:
            raise ValueError("creative learning page Artifact differs from its manifest")
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("creative learning work input hash differs")
        return self


def validate_external_item_learning_result_for_work(
    result: ExternalItemLearningResult | ExternalItemLearningResultV2,
    work: ExternalItemLearningWorkInput,
) -> None:
    """Close worker output over one exact source and its staged visual pages."""

    source = work.source
    validate_external_item_learning_result_for_source(
        result,
        source.input_sha256,
        source.source_id,
        source.source_revision_id,
        source.external_number,
    )
    page_count = len(work.page_set.pages)
    if any(region.physical_page > page_count for region in result.regions):
        raise ValueError("creative learning region is outside the staged pages")
