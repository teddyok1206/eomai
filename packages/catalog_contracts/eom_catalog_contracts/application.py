"""Typed private protocol for orchestrator-owned Catalog application operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, RootModel, field_validator, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.models import ActorId, FrozenModel

ItemRevisionId = Annotated[str, Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")]

# The socket framing and filesystem identity are part of the private protocol,
# not an implementation detail of either endpoint.
CATALOG_APPLICATION_SOCKET_PATH = "/run/eom-catalog-api/manager.sock"
CATALOG_APPLICATION_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CATALOG_APPLICATION_SOCKET_MODE = 0o660
CATALOG_APPLICATION_RUNTIME_DIRECTORY_MODE = 0o750


class CatalogApplicationErrorCode(StrEnum):
    CATALOG_APPLICATION_INTERNAL_ERROR = "CATALOG_APPLICATION_INTERNAL_ERROR"
    CATALOG_APPLICATION_REQUEST_INVALID = "CATALOG_APPLICATION_REQUEST_INVALID"
    CATALOG_APPLICATION_UNAVAILABLE = "CATALOG_APPLICATION_UNAVAILABLE"
    CATALOG_ARTIFACT_COMMIT_FAILED = "CATALOG_ARTIFACT_COMMIT_FAILED"
    CATALOG_CONTENT_PACK_STAGING_INVALID = "CATALOG_CONTENT_PACK_STAGING_INVALID"
    CATALOG_CONCURRENCY_CONFLICT = "CATALOG_CONCURRENCY_CONFLICT"
    CATALOG_QUERY_INVALID = "CATALOG_QUERY_INVALID"
    CATALOG_CURSOR_INVALID = "CATALOG_CURSOR_INVALID"
    CATALOG_EXPORT_FAILED = "CATALOG_EXPORT_FAILED"
    CATALOG_REGISTRY_STAGING_INVALID = "CATALOG_REGISTRY_STAGING_INVALID"


class ReviewedItemContentImportCommand(FrozenModel):
    operation: Literal["IMPORT_REVIEWED_ITEM_CONTENT"] = "IMPORT_REVIEWED_ITEM_CONTENT"
    base_revision_id: ItemRevisionId
    expected_version: int = Field(ge=1)
    reviewed_by: ActorId
    review_reason: str = Field(min_length=10, max_length=2000)
    content: AssessmentItemContent

    @field_validator("review_reason")
    @classmethod
    def safe_review_reason(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("review reason contains a control character")
        return value


class ItemContentQuery(FrozenModel):
    operation: Literal["GET_ITEM_CONTENT"] = "GET_ITEM_CONTENT"
    item_revision_id: ItemRevisionId


CatalogApplicationRequestValue = Annotated[
    ReviewedItemContentImportCommand | ItemContentQuery,
    Field(discriminator="operation"),
]


class CatalogApplicationRequest(RootModel[CatalogApplicationRequestValue]):
    root: CatalogApplicationRequestValue


class ReviewedItemContentImportResult(FrozenModel):
    item_id: str = Field(pattern=r"^item_[a-z0-9]{8,59}$")
    item_revision_id: ItemRevisionId
    resource_version: int = Field(ge=1)
    content_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    content_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CatalogApplicationResponse(FrozenModel):
    status: Literal["OK", "ERROR"]
    operation: Literal["IMPORT_REVIEWED_ITEM_CONTENT", "GET_ITEM_CONTENT"]
    result: ReviewedItemContentImportResult | None = None
    content: AssessmentItemContent | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> CatalogApplicationResponse:
        present = sum(value is not None for value in (self.result, self.content, self.error_code))
        if present != 1:
            raise ValueError("catalog application response must contain exactly one payload")
        if self.status == "ERROR":
            if self.error_code is None:
                raise ValueError("catalog application error response requires error_code")
            return self
        if self.error_code is not None:
            raise ValueError("catalog application success response cannot contain error_code")
        if self.operation == "IMPORT_REVIEWED_ITEM_CONTENT" and self.result is None:
            raise ValueError("catalog import response requires result")
        if self.operation == "GET_ITEM_CONTENT" and self.content is None:
            raise ValueError("catalog content response requires content")
        return self
