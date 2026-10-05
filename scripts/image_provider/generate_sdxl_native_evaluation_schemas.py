#!/usr/bin/env python3
"""Generate only the native-trained evaluation successor; preserve predecessor bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    LocalImageSdxlNativeEvaluationResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for family, model in (
        ("command", LocalImageSdxlNativeEvaluationCommand),
        ("result", LocalImageSdxlNativeEvaluationResult),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = (
            f"eom://schemas/image-provider/local-image-sdxl-lora-evaluation-{family}/1.2"
        )
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        filename = f"local-image-sdxl-lora-evaluation-{family}-v3.schema.json"
        for directory in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (directory / filename).write_bytes(payload)
        print(f"sdxl-lora-evaluation-{family}-v3=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
