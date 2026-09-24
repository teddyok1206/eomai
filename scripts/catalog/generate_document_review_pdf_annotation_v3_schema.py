#!/usr/bin/env python3
"""Generate the Graph-grounded native-panel annotation request schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "schemas/catalog/catalog-application/"
    "document-review-pdf-annotation-request-v2.schema.json"
)
OUTPUT = "document-review-pdf-annotation-request-v3.schema.json"
RESULT_SCHEMA = (
    "https://eom.local/schemas/workflow/roles/paired-document-review-result-v3.schema.json"
)


def request_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(SOURCE.read_text(encoding="ascii"))
    value["$id"] = "eom://schemas/catalog-application/document-review-pdf-annotation-request/3.0"
    value["properties"]["schema_version"] = {"const": "document-review-pdf-annotation-request/3.0"}
    value["$defs"]["reviewResultPointer"]["properties"]["schema_ref"] = {"const": RESULT_SCHEMA}
    return value


def main() -> None:
    payload = json.dumps(request_schema(), indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    for directory in (
        ROOT / "schemas/catalog/catalog-application",
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / OUTPUT).write_text(payload, encoding="ascii")


if __name__ == "__main__":
    main()
