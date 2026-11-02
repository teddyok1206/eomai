"""Regenerate only the new visual-presentation contracts; predecessors are untouched."""

import json
from pathlib import Path

from eom_catalog_contracts.creative_bitmap_presentation import CreativeBitmapPresentationManifest
from eom_catalog_contracts.creative_visual_presentation import (
    CreativeVisualPresentationManifest,
    ItemVisualPresentationQuery,
    ItemVisualPresentationResponse,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    for model, folder, stem, schema_id in (
        (
            CreativeBitmapPresentationManifest,
            "external-item",
            "creative-visual-presentation-v1-1",
            "creative-visual-presentation",
        ),
        (
            CreativeVisualPresentationManifest,
            "external-item",
            "creative-visual-presentation-v1",
            "creative-visual-presentation",
        ),
        (
            ItemVisualPresentationQuery,
            "item-registry",
            "catalog-item-visual-presentation-request-v1",
            "catalog-item-visual-presentation-request",
        ),
        (
            ItemVisualPresentationResponse,
            "item-registry",
            "catalog-item-visual-presentation-response-v1",
            "catalog-item-visual-presentation-response",
        ),
    ):
        value = model.model_json_schema(mode="validation")
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        version = "1.1" if model is CreativeBitmapPresentationManifest else "1.0"
        value["$id"] = f"eom://schemas/{folder}/{schema_id}/{version}"
        Draft202012Validator.check_schema(value)
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        for target in (
            ROOT / "schemas" / folder / (stem + ".schema.json"),
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources"
            / folder
            / (stem + ".schema.json"),
        ):
            target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
