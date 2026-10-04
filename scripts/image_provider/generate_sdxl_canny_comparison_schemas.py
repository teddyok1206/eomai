#!/usr/bin/env python3
"""Freeze reviewed spatial-comparison messages before GPU backend behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_canny_comparison import (
    LocalImageSdxlCannyComparisonCommand,
    LocalImageSdxlCannyComparisonResult,
    LocalImageSdxlCannyDetailReview,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, family in (
        (LocalImageSdxlCannyDetailReview, "sdxl-canny-detail-review"),
        (LocalImageSdxlCannyComparisonCommand, "sdxl-canny-comparison-command"),
        (LocalImageSdxlCannyComparisonResult, "sdxl-canny-comparison-result"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = "eom://schemas/image-provider/local-image-" + family + "/1.0"
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        name = "local-image-" + family + "-v1.schema.json"
        for folder in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (folder / name).write_bytes(payload)
        print(f"{family}=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
