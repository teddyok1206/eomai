#!/usr/bin/env python3
"""Generate bounded object-support plan/command/result resources, preserving frozen bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_image_contracts.sdxl_photo_object_support_plan import (
    PLAN_SCHEMA,
    LocalImageSdxlPhotoObjectSupportPlan,
)
from eom_image_contracts.sdxl_photo_style_execution import LocalImageSdxlPhotoObjectSupportCommand
from eom_image_contracts.sdxl_photo_style_result import LocalImageSdxlPhotoObjectSupportResult
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for model, family in (
        (LocalImageSdxlPhotoObjectSupportPlan, "plan"),
        (LocalImageSdxlPhotoObjectSupportCommand, "command"),
        (LocalImageSdxlPhotoObjectSupportResult, "result"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = PLAN_SCHEMA.replace("-plan/", "-" + family + "/")
        Draft202012Validator.check_schema(schema)
        raw = (json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        name = "local-image-sdxl-photo-style-" + family + "-v7.schema.json"
        for folder in (
            ROOT / "schemas/image-provider",
            ROOT / "packages/image_contracts/eom_image_contracts/schemas",
        ):
            path = folder / name
            if path.exists():
                if path.read_bytes() != raw:
                    raise ValueError("frozen object-support schema bytes changed")
            else:
                path.write_bytes(raw)
        print("sdxl-photo-style-" + family + "-v7=sha256:" + hashlib.sha256(raw).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
