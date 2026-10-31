"""A local owner result, never permission to replace a source or mark it accepted."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import validate_contract


class CreativePreviewPreparationResult(FrozenModel):
    schema_version: Literal["creative-preview-preparation-result/1.0"] = (
        "creative-preview-preparation-result/1.0"
    )
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    edition: int = Field(strict=True, ge=1, le=3)
    status: Literal["READY", "DEFERRED"]
    error_code: Literal["OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING"] | None = None

    @model_validator(mode="after")
    def exact_status(self) -> Self:
        if (self.status == "READY") != (self.error_code is None):
            raise ValueError("CREATIVE_PREVIEW_RESULT_INVALID")
        validate_contract("creative-preview-preparation-result-v1", self.model_dump(mode="json"))
        return self
