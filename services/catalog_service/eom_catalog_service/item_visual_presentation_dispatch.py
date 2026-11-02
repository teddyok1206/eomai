"""Read-only display frames through the existing API-only Catalog socket gate."""

import json
from typing import Protocol

from eom_catalog_contracts.creative_visual_presentation import (
    ItemVisualPresentation,
    ItemVisualPresentationQuery,
    ItemVisualPresentationResponse,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes
from jsonschema.exceptions import ValidationError as SchemaError


class ItemVisualPresentationReader(Protocol):
    def load_item_visual_presentation(self, revision_id: str) -> ItemVisualPresentation: ...


def dispatch_item_visual_presentation(reader: ItemVisualPresentationReader, raw: bytes) -> bytes:
    try:
        if not raw.endswith(b"\n") or len(raw) > 4096:
            raise ValueError("invalid display request frame")
        value = json.loads(raw)
        validate_contract("catalog-item-visual-presentation-request-v1", value)
        request = ItemVisualPresentationQuery.model_validate(value)
    except (ValueError, SchemaError):
        response = ItemVisualPresentationResponse(
            status="ERROR", error_code="CATALOG_APPLICATION_REQUEST_INVALID"
        )
    else:
        try:
            response = ItemVisualPresentationResponse(
                status="OK",
                presentation=reader.load_item_visual_presentation(request.item_revision_id),
            )
        except Exception:
            response = ItemVisualPresentationResponse(
                status="ERROR", error_code="ITEM_VISUAL_PRESENTATION_UNAVAILABLE"
            )
    payload = response.model_dump(mode="json")
    validate_contract("catalog-item-visual-presentation-response-v1", payload)
    encoded = canonical_json_bytes(payload) + b"\n"
    if len(encoded) > 4 * 1024 * 1024:
        response = ItemVisualPresentationResponse(
            status="ERROR", error_code="ITEM_VISUAL_PRESENTATION_BUDGET_EXCEEDED"
        )
        return canonical_json_bytes(response.model_dump(mode="json")) + b"\n"
    return encoded
