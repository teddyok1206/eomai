#!/usr/bin/env python3
"""Generate the API view schema accepting historical and exhaustive paired reviews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "schemas/api/v1/paired-document-review-view-v1.schema.json"
OUTPUT = "paired-document-review-view-v2.schema.json"


def view_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(SOURCE.read_text(encoding="utf-8"))
    value["$id"] = "https://eom.local/schemas/api/v1/paired-document-review-view-v2.schema.json"
    value["title"] = "EOM Paired Document Review View V2"
    value["properties"]["result"] = {
        "oneOf": [
            {
                "$ref": (
                    "https://eom.local/schemas/workflow/roles/"
                    "paired-document-review-result-v3.schema.json#/$defs/output"
                )
            },
            {
                "$ref": (
                    "https://eom.local/schemas/workflow/roles/"
                    "paired-document-review-result-v2.schema.json#/$defs/output"
                )
            },
            {"type": "null"},
        ]
    }
    return value


def main() -> None:
    payload = json.dumps(view_schema(), ensure_ascii=False, indent=2) + "\n"
    for directory in (
        ROOT / "schemas/api/v1",
        ROOT / "packages/api_contracts/eom_api_contracts/schemas",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / OUTPUT).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
