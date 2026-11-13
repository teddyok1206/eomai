"""Read native material documents by registered Item identity, never caller paths."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_files import (
    MaterialImportedNativeItemMetadata,
    MaterialNativeWorkbookRow,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract


class MaterialNativeItemReadRequest(FrozenModel):
    operation: Literal["GET_NATIVE_MATERIAL_ITEM_SOURCE", "GET_NATIVE_MATERIAL_ITEM_DOCUMENT"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    source_role: Literal["MAIN", "SOLUTIONS"] | None = None

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        if (self.operation == "GET_NATIVE_MATERIAL_ITEM_SOURCE") != (self.source_role is None):
            raise ValueError("MATERIAL_NATIVE_READ_REQUEST_INVALID")
        validate_contract("material-native-item-read-request-v1", self.model_dump(mode="json"))
        return self


class MaterialNativeItemSource(FrozenModel):
    material_title: str = Field(min_length=1, max_length=200)
    metadata: MaterialImportedNativeItemMetadata
    question: MaterialArtifactMember
    solution: MaterialArtifactMember
    workbook: MaterialNativeWorkbookRow


class MaterialNativeItemReadResponse(FrozenModel):
    operation: Literal["GET_NATIVE_MATERIAL_ITEM_SOURCE", "GET_NATIVE_MATERIAL_ITEM_DOCUMENT"]
    status: Literal["OK", "ERROR"]
    source: MaterialNativeItemSource | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    media_type: Literal["application/vnd.hancom.hwpx", "application/hwp+zip"] | None = None
    content_length: int | None = Field(default=None, strict=True, ge=1, le=50 * 1024 * 1024)
    sha256: Sha256 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str | None) -> str | None:
        if value and any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in value):
            raise ValueError("MATERIAL_NATIVE_DOCUMENT_FILENAME_INVALID")
        return value

    @model_validator(mode="after")
    def exact_response(self) -> Self:
        media = (self.filename, self.media_type, self.content_length, self.sha256)
        if self.status == "ERROR":
            if self.error_code is None or self.source is not None or any(media):
                raise ValueError("MATERIAL_NATIVE_READ_ERROR_RESPONSE_INVALID")
        elif self.error_code is not None:
            raise ValueError("MATERIAL_NATIVE_READ_SUCCESS_RESPONSE_INVALID")
        elif self.operation == "GET_NATIVE_MATERIAL_ITEM_SOURCE":
            if self.source is None or any(media):
                raise ValueError("MATERIAL_NATIVE_SOURCE_RESPONSE_INVALID")
        elif self.source is not None or any(value is None for value in media):
            raise ValueError("MATERIAL_NATIVE_DOCUMENT_RESPONSE_INVALID")
        validate_contract("material-native-item-read-response-v1", self.model_dump(mode="json"))
        return self
