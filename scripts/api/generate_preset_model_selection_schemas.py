#!/usr/bin/env python3
"""Generate canonical and packaged administrator model-selection wire schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eom_api_contracts.preset_model_selection import (
    PresetModelEvaluationRequest,
    PresetModelOptionsView,
    PresetModelValidationView,
)

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / "schemas/api/v1",
    ROOT / "packages/api_contracts/eom_api_contracts/schemas",
)
MODELS = {
    "preset-model-evaluation-request-v1.schema.json": PresetModelEvaluationRequest,
    "preset-model-options-view-v1.schema.json": PresetModelOptionsView,
    "preset-model-validation-view-v1.schema.json": PresetModelValidationView,
}


def generate(*, check: bool) -> None:
    drift: list[str] = []
    for name, model in MODELS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://eom.local/schemas/api/v1/{name}"
        payload = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
        for directory in TARGETS:
            target = directory / name
            if target.exists() and target.read_bytes() == payload:
                continue
            if check:
                drift.append(str(target.relative_to(ROOT)))
            else:
                target.write_bytes(payload)
    if drift:
        raise SystemExit("model-selection schema drift: " + ", ".join(drift))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
