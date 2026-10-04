#!/usr/bin/env python3
"""Generate only the source-initialized successor; preserve released comparison bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    LocalImageSdxlCannyReferenceResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, family in (
        (LocalImageSdxlCannyReferenceCommand, "sdxl-canny-reference-command"),
        (LocalImageSdxlCannyReferenceResult, "sdxl-canny-reference-result"),
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
