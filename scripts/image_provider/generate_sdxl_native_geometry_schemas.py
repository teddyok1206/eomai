#!/usr/bin/env python3
"""Generate only the native-geometry successor; never rewrite released schemas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_native_geometry import (
    LocalImageSdxlNativeGeometryCommand,
    LocalImageSdxlNativeGeometryResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for family, model in (
        ("command", LocalImageSdxlNativeGeometryCommand),
        ("result", LocalImageSdxlNativeGeometryResult),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = (
            f"eom://schemas/image-provider/local-image-sdxl-lora-evaluation-{family}/1.3"
        )
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        filename = f"local-image-sdxl-lora-evaluation-{family}-v4.schema.json"
        for directory in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (directory / filename).write_bytes(payload)
        print(f"sdxl-lora-evaluation-{family}-v4=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
