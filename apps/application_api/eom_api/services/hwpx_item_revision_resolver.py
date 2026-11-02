"""HWPX Item resolver that keeps Catalog-owned NAS validation outside the API sandbox."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts import (
    InspectItemRevisionHwpxEligibilityQueryV1,
    ItemRevisionHwpxEligibilityV1,
)
from eom_catalog_contracts.item_visual_render_revision import item_visual_render_revision
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
        revision = self._registry.inspect_revision(item_revision_id)
        # Only the historical block-content family has imported source rasters.
        # AI/content-team and Markdown-only source paths keep their existing I/O.
        components = revision.get("components", ())
        if not any(
            value.get("component_type") == "ITEM_CONTENT"
            and value.get("schema_ref")
            in {
                "eom.assessment.item-content/1.0",
                "eom://schemas/item-registry/assessment-item-content-v1",
            }
            for value in components
            if isinstance(value, dict)
        ):
            return revision
        return item_visual_render_revision(
            revision, self._catalog.load_item_visual_presentation(item_revision_id)
        )

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
