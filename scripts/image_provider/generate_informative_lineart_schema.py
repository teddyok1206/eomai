#!/usr/bin/env python3
"""Generate the additive learned extractor schema before runtime implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.informative_lineart import (
    INFORMATIVE_LINEART_MANIFEST_SCHEMA_REF,
    LocalImageInformativeLineartManifest,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    schema = LocalImageInformativeLineartManifest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = INFORMATIVE_LINEART_MANIFEST_SCHEMA_REF
    Draft202012Validator.check_schema(schema)
    payload = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    filename = "local-image-informative-lineart-manifest-v1.schema.json"
    for directory in (
        ROOT / "schemas/image-provider",
        ROOT / "packages/image_contracts/eom_image_contracts/schemas",
    ):
        (directory / filename).write_bytes(payload)
    print(f"informative-lineart-manifest=sha256:{hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
