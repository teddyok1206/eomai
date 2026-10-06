#!/usr/bin/env python3
"""Generate only the preparation successor; runtime codecs stay closed to1.6."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_photo_object_support_plan import (
    PLAN_SCHEMA,
    LocalImageSdxlPhotoObjectSupportPlan,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    schema = LocalImageSdxlPhotoObjectSupportPlan.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = PLAN_SCHEMA
    Draft202012Validator.check_schema(schema)
    raw = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    name = "local-image-sdxl-photo-style-plan-v7.schema.json"
    for folder in (
        ROOT / "schemas/image-provider",
        ROOT / "packages/image_contracts/eom_image_contracts/schemas",
    ):
        (folder / name).write_bytes(raw)
    print("sdxl-photo-style-plan-v7=sha256:" + hashlib.sha256(raw).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
