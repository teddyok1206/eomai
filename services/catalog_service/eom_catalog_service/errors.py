"""Catalog application errors with stable machine codes."""

from enum import StrEnum


class CatalogErrorCode(StrEnum):
    CATALOG_ARTIFACT_COMMIT_FAILED = "CATALOG_ARTIFACT_COMMIT_FAILED"
    CATALOG_CONTENT_PACK_STAGING_INVALID = "CATALOG_CONTENT_PACK_STAGING_INVALID"
    CATALOG_CONCURRENCY_CONFLICT = "CATALOG_CONCURRENCY_CONFLICT"
    CATALOG_QUERY_INVALID = "CATALOG_QUERY_INVALID"
    CATALOG_CURSOR_INVALID = "CATALOG_CURSOR_INVALID"
    CATALOG_EXPORT_FAILED = "CATALOG_EXPORT_FAILED"
    CATALOG_REGISTRY_STAGING_INVALID = "CATALOG_REGISTRY_STAGING_INVALID"


class CatalogError(RuntimeError):
    def __init__(self, code: str | CatalogErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
