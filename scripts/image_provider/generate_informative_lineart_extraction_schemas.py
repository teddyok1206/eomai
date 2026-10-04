#!/usr/bin/env python3
"""Generate additive learned extraction messages before isolated worker behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.informative_lineart_extraction import (
    INFORMATIVE_EXTRACTION_COMMAND_SCHEMA_REF,
    INFORMATIVE_EXTRACTION_RESULT_SCHEMA_REF,
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, family, ref in (
        (
            LocalImageInformativeLineartExtractionCommand,
            "command",
            INFORMATIVE_EXTRACTION_COMMAND_SCHEMA_REF,
        ),
        (
            LocalImageInformativeLineartExtractionResult,
            "result",
            INFORMATIVE_EXTRACTION_RESULT_SCHEMA_REF,
        ),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = ref
        Draft202012Validator.check_schema(schema)
        payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        filename = f"local-image-informative-lineart-extraction-{family}-v1.schema.json"
        for directory in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            (directory / filename).write_bytes(payload)
        print(
            f"informative-lineart-extraction-{family}=sha256:{hashlib.sha256(payload).hexdigest()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
