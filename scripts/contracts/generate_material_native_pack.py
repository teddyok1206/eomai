"""Render the standalone Registry schema from the canonical native metadata contract.

The Registry loads a released Content Pack without repository/schema lookup or network.
Only its artifact-member definition is inlined; the canonical contract remains the owner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT / "content/packs/uploaded-material-item/1.1.0/metadata-schemas/item-metadata.schema.json"
)


def native_pack_metadata_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(
        (ROOT / "schemas/material-learning/item-metadata-v2.schema.json").read_text()
    )
    types = json.loads(
        (ROOT / "schemas/material-learning/material-learning-types-v1.schema.json").read_text()
    )
    schema["$id"] = "eom://metadata/uploaded-material-item@2.0"
    schema["properties"]["native_binding"] = types["$defs"]["artifactMember"]

    def require_standalone(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                raise ValueError("native pack schema has an unresolved reference")
            for child in value.values():
                require_standalone(child)
        elif isinstance(value, list):
            for child in value:
                require_standalone(child)

    require_standalone(schema)
    return schema


def render_schema() -> str:
    return json.dumps(native_pack_metadata_schema(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_schema()
    if args.check:
        if TARGET.read_text() != expected:
            raise SystemExit("native Content Pack schema differs from its canonical contract")
    else:
        print(expected, end="")


if __name__ == "__main__":
    main()
