#!/usr/bin/env python3
"""Generate the closed V2 content-team image/render JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import ContentTeamBuildResultV2, ContentTeamRenderRequestV2
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _close(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties)
        for child in value.values():
            _close(child)
    elif isinstance(value, list):
        for child in value:
            _close(child)


def _write(model: type[Any], name: str) -> None:
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://eom.local/schemas/hwpx/{name}"
    _close(schema)
    Draft202012Validator.check_schema(schema)
    payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name).write_text(
        payload, encoding="utf-8"
    )


def main() -> None:
    _write(ContentTeamRenderRequestV2, "hwpx-content-team-render-request-v2.schema.json")
    _write(ContentTeamBuildResultV2, "hwpx-content-team-build-result-v2.schema.json")


if __name__ == "__main__":
    main()
