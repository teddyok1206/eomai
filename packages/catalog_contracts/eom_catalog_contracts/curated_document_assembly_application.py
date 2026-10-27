"""Private Catalog request for pinning a mixed-source assembly selection."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_draft import CuratedDocumentAssemblyDraftV1
from eom_catalog_contracts.models import FrozenModel, UtcDatetime


class CuratedDocumentAssemblyCreateCommandV1(FrozenModel):
    operation: Literal["CREATE_CURATED_DOCUMENT_ASSEMBLY"] = "CREATE_CURATED_DOCUMENT_ASSEMBLY"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    draft: CuratedDocumentAssemblyDraftV1


class CuratedDocumentAssemblyCreateResponseV1(FrozenModel):
    operation: Literal["CREATE_CURATED_DOCUMENT_ASSEMBLY"] = "CREATE_CURATED_DOCUMENT_ASSEMBLY"
    status: Literal["OK", "ERROR"]
    manifest: CuratedDocumentAssemblyManifestV1 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_result_branch(self) -> Self:
        if (self.status == "OK") != (self.manifest is not None and self.error_code is None):
            raise ValueError("curated assembly result branch is invalid")
        if self.status == "ERROR" and self.error_code is None:
            raise ValueError("curated assembly error requires a code")
        return self


class CuratedDocumentAssemblyReadQueryV1(FrozenModel):
    operation: Literal["READ_CURATED_DOCUMENT_ASSEMBLY"] = "READ_CURATED_DOCUMENT_ASSEMBLY"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")


class CuratedDocumentAssemblyReadResponseV1(FrozenModel):
    operation: Literal["READ_CURATED_DOCUMENT_ASSEMBLY"] = "READ_CURATED_DOCUMENT_ASSEMBLY"
    status: Literal["OK", "ERROR"]
    manifest: CuratedDocumentAssemblyManifestV1 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_result_branch(self) -> Self:
        if (self.status == "OK") != (self.manifest is not None and self.error_code is None):
            raise ValueError("curated assembly read result branch is invalid")
        if self.status == "ERROR" and self.error_code is None:
            raise ValueError("curated assembly read error requires a code")
        return self


class CuratedDocumentAssemblyListQueryV1(FrozenModel):
    operation: Literal["LIST_CURATED_DOCUMENT_ASSEMBLIES"] = "LIST_CURATED_DOCUMENT_ASSEMBLIES"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    )


class CuratedDocumentAssemblyListEntryV1(FrozenModel):
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    created_at: UtcDatetime
    placement_count: int = Field(ge=1, le=200)
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CuratedDocumentAssemblyListResponseV1(FrozenModel):
    operation: Literal["LIST_CURATED_DOCUMENT_ASSEMBLIES"] = "LIST_CURATED_DOCUMENT_ASSEMBLIES"
    status: Literal["OK", "ERROR"]
    values: tuple[CuratedDocumentAssemblyListEntryV1, ...] = Field(max_length=50)
    next_cursor: str | None = Field(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    )
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_result_branch(self) -> Self:
        if self.status == "OK" and self.error_code is None:
            return self
        if (
            self.status == "ERROR"
            and not self.values
            and self.next_cursor is None
            and self.error_code
        ):
            return self
        raise ValueError("curated assembly list result branch is invalid")
