#!/usr/bin/env python3
"""Generate additive receipt-pinned BASE/LORA comparison messages before worker behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_learned_comparison import (
    SDXL_LEARNED_COMMAND_SCHEMA_REF,
    SDXL_LEARNED_RESULT_SCHEMA_REF,
    LocalImageSdxlLearnedComparisonCommand,
    LocalImageSdxlLearnedComparisonResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, family, ref in (
        (LocalImageSdxlLearnedComparisonCommand, "command", SDXL_LEARNED_COMMAND_SCHEMA_REF),
        (LocalImageSdxlLearnedComparisonResult, "result", SDXL_LEARNED_RESULT_SCHEMA_REF),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = ref
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        filename = f"local-image-sdxl-learned-comparison-{family}-v1.schema.json"
        for directory in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (directory / filename).write_bytes(payload)
        print(f"sdxl-learned-comparison-{family}=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
