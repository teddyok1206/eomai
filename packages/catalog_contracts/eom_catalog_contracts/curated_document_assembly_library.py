"""Owned assembly presentation metadata; immutable selection/delivery V1 stays separate."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_application import (
    CuratedDocumentAssemblyListEntryV1,
)
from eom_catalog_contracts.curated_document_assembly_draft import (
    CuratedDocumentAssemblyDraftV1,
    CuratedPlacement,
    validate_curated_placements,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

LIBRARY_SCHEMA = "catalog-curated-document-assembly-library-v1"


class CuratedDocumentAssemblyDraftV2(FrozenModel):
    schema_version: Literal["curated-document-assembly-draft/2.0"]
    title: str = Field(max_length=200, pattern=r"^[^\r\n\t]*$")
    placements: tuple[CuratedPlacement, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_unique_placements(self) -> Self:
        validate_curated_placements(self.placements)
        return self

    @field_validator("title")
    @classmethod
    def canonical_title(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("assembly title must not have outer whitespace")
        return value

    def selection(self) -> CuratedDocumentAssemblyDraftV1:
        return CuratedDocumentAssemblyDraftV1(
            schema_version="curated-document-assembly-draft/1.0", placements=self.placements
        )


class _LibraryApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime


class CuratedDocumentAssemblyCreateCommandV2(_LibraryApiIdentity):
    operation: Literal["CREATE_CURATED_DOCUMENT_ASSEMBLY_V2"] = (
        "CREATE_CURATED_DOCUMENT_ASSEMBLY_V2"
    )
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    draft: CuratedDocumentAssemblyDraftV2


class CuratedDocumentAssemblyCreateResponseV2(FrozenModel):
    operation: Literal["CREATE_CURATED_DOCUMENT_ASSEMBLY_V2"] = (
        "CREATE_CURATED_DOCUMENT_ASSEMBLY_V2"
    )
    status: Literal["OK", "ERROR"]
    manifest: CuratedDocumentAssemblyManifestV1 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def result_branch(self) -> Self:
        if (self.status == "OK") != (self.manifest is not None and self.error_code is None):
            raise ValueError("titled assembly result branch is invalid")
        if self.status == "ERROR" and (self.manifest is not None or self.error_code is None):
            raise ValueError("titled assembly error branch is invalid")
        return self


class CuratedDocumentAssemblyListQueryV2(_LibraryApiIdentity):
    operation: Literal["LIST_CURATED_DOCUMENT_ASSEMBLIES_V2"] = (
        "LIST_CURATED_DOCUMENT_ASSEMBLIES_V2"
    )
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    )


class CuratedDocumentAssemblyListEntryV2(CuratedDocumentAssemblyListEntryV1):
    title: str = Field(max_length=200, pattern=r"^[^\r\n\t]*$")


class CuratedDocumentAssemblyListResponseV2(FrozenModel):
    operation: Literal["LIST_CURATED_DOCUMENT_ASSEMBLIES_V2"] = (
        "LIST_CURATED_DOCUMENT_ASSEMBLIES_V2"
    )
    status: Literal["OK", "ERROR"]
    values: tuple[CuratedDocumentAssemblyListEntryV2, ...] = Field(max_length=50)
    next_cursor: str | None = Field(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    )
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def result_branch(self) -> Self:
        if self.status == "OK" and self.error_code is None:
            return self
        if (
            self.status == "ERROR"
            and not self.values
            and self.next_cursor is None
            and self.error_code
        ):
            return self
        raise ValueError("titled assembly list branch is invalid")


class CuratedDocumentAssemblyRemovalInput(FrozenModel):
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256


class CuratedDocumentAssemblyRemoveCommandV1(_LibraryApiIdentity):
    operation: Literal["REMOVE_CURATED_DOCUMENT_ASSEMBLY"] = "REMOVE_CURATED_DOCUMENT_ASSEMBLY"
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    selection: CuratedDocumentAssemblyRemovalInput


class CuratedDocumentAssemblyRemovalReceipt(FrozenModel):
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    removed_at: UtcDatetime


class CuratedDocumentAssemblyRemoveResponseV1(FrozenModel):
    operation: Literal["REMOVE_CURATED_DOCUMENT_ASSEMBLY"] = "REMOVE_CURATED_DOCUMENT_ASSEMBLY"
    status: Literal["OK", "ERROR"]
    receipt: CuratedDocumentAssemblyRemovalReceipt | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def result_branch(self) -> Self:
        if (self.status == "OK") != (self.receipt is not None and self.error_code is None):
            raise ValueError("assembly removal branch is invalid")
        if self.status == "ERROR" and (self.receipt is not None or self.error_code is None):
            raise ValueError("assembly removal error requires a code without a receipt")
        return self


type CuratedAssemblyLibraryRequest = (
    CuratedDocumentAssemblyCreateCommandV2
    | CuratedDocumentAssemblyListQueryV2
    | CuratedDocumentAssemblyRemoveCommandV1
)
type CuratedAssemblyLibraryResponse = (
    CuratedDocumentAssemblyCreateResponseV2
    | CuratedDocumentAssemblyListResponseV2
    | CuratedDocumentAssemblyRemoveResponseV1
)

LIBRARY_REQUEST_TYPES: MappingProxyType[str, type[CuratedAssemblyLibraryRequest]] = (
    MappingProxyType(
        {
            "CREATE_CURATED_DOCUMENT_ASSEMBLY_V2": CuratedDocumentAssemblyCreateCommandV2,
            "LIST_CURATED_DOCUMENT_ASSEMBLIES_V2": CuratedDocumentAssemblyListQueryV2,
            "REMOVE_CURATED_DOCUMENT_ASSEMBLY": CuratedDocumentAssemblyRemoveCommandV1,
        }
    )
)
LIBRARY_RESPONSE_TYPES: MappingProxyType[str, type[CuratedAssemblyLibraryResponse]] = (
    MappingProxyType(
        {
            "CREATE_CURATED_DOCUMENT_ASSEMBLY_V2": CuratedDocumentAssemblyCreateResponseV2,
            "LIST_CURATED_DOCUMENT_ASSEMBLIES_V2": CuratedDocumentAssemblyListResponseV2,
            "REMOVE_CURATED_DOCUMENT_ASSEMBLY": CuratedDocumentAssemblyRemoveResponseV1,
        }
    )
)


def parse_curated_library_request(value: dict[str, object]) -> CuratedAssemblyLibraryRequest:
    validate_contract(LIBRARY_SCHEMA, value)
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in LIBRARY_REQUEST_TYPES:
        raise ValueError("invalid assembly library request operation")
    return LIBRARY_REQUEST_TYPES[operation].model_validate(value)


def parse_curated_library_response(value: dict[str, object]) -> CuratedAssemblyLibraryResponse:
    validate_contract(LIBRARY_SCHEMA, value)
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in LIBRARY_RESPONSE_TYPES:
        raise ValueError("invalid assembly library response operation")
    return LIBRARY_RESPONSE_TYPES[operation].model_validate(value)
