#!/usr/bin/env python3
"""Generate public API schema for native-panel annotated document-review PDFs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / "schemas/api/v1",
    ROOT / "packages/api_contracts/eom_api_contracts/schemas",
)


def schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/api/v1/document-review-annotation-v2.schema.json",
        "title": "EOM Document Review Annotation V2 Create Request",
        "type": "object",
        "additionalProperties": False,
        "required": ["include_all_findings", "annotation_profile"],
        "properties": {
            "include_all_findings": {"const": True},
            "annotation_profile": {"const": "NUMBERED_BOXES_WITH_NATIVE_COMMENTS"},
        },
    }


def main() -> None:
    payload = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        (target / "document-review-annotation-v2.schema.json").write_bytes(payload)


if __name__ == "__main__":
    main()
