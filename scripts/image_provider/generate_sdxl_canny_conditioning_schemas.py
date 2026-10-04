#!/usr/bin/env python3
"""Freeze Canny input-preparation schemas before implementing the CPU worker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_canny_conditioning import (
    PREFIX,
    LocalImageSdxlCannyConditioningCommand,
    LocalImageSdxlCannyConditioningResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, kind in (
        (LocalImageSdxlCannyConditioningCommand, "command"),
        (LocalImageSdxlCannyConditioningResult, "result"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = PREFIX + f"sdxl-canny-conditioning-{kind}/1.0"
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        filename = f"local-image-sdxl-canny-conditioning-{kind}-v1.schema.json"
        for directory in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (directory / filename).write_bytes(payload)
        print(f"sdxl-canny-conditioning-{kind}=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
