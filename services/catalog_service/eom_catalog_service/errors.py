"""Catalog service exceptions backed by stable contract-layer codes."""

from eom_catalog_contracts import CatalogApplicationErrorCode

CatalogErrorCode = CatalogApplicationErrorCode


class CatalogError(RuntimeError):
    def __init__(self, code: str | CatalogErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
