"""HWPX Item resolver that keeps Catalog-owned NAS validation outside the API sandbox."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts import (
    InspectItemRevisionHwpxEligibilityQueryV1,
    ItemRevisionHwpxEligibilityV1,
)
from eom_catalog_service.registry_service import RegistryService

from eom_api.services.catalog_application_client import CatalogApplicationClient


class CatalogBackedHwpxItemRevisionResolver:
    """Compose indexed Registry reads with one Catalog-owned eligibility proof lookup."""

    def __init__(
        self,
        registry: RegistryService,
        catalog: CatalogApplicationClient,
    ) -> None:
        self._registry = registry
        self._catalog = catalog

    def inspect_revision(self, item_revision_id: str) -> dict[str, Any]:
        return self._registry.inspect_revision(item_revision_id)

    def inspect_revisions(self, item_revision_ids: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
        return self._registry.inspect_revisions(item_revision_ids)

    def inspect_item(self, item_id: str) -> dict[str, Any]:
        return self._registry.inspect_item(item_id)

    def require_hwpx_review_eligibility(
        self, item_revision_id: str
    ) -> ItemRevisionHwpxEligibilityV1:
        return self._catalog.inspect_item_revision_hwpx_eligibility(
            InspectItemRevisionHwpxEligibilityQueryV1(item_revision_id=item_revision_id)
        )
