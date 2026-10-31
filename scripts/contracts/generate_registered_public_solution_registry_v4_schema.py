#!/usr/bin/env python3
"""Index4 registration metadata over the existing immutable Registry/CAS use case."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas/knowledge"
PACKAGED = ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
OLD = "eom://schemas/knowledge/public-solution-embedding-registry/3.0"


def build_contract() -> dict[str, Any]:
    old = json.loads((SCHEMAS / "public-solution-embedding-registry-v3.schema.json").read_bytes())
    definitions = {}
    for name, original, version in (
        (
            "command",
            "RegisterPublicSolutionIndexCommand",
            "embedding-registry-registration-command/4.0",
        ),
        (
            "result",
            "PublicSolutionIndexRegistrationResult",
            "embedding-registry-registration-result/4.0",
        ),
    ):
        definition = copy.deepcopy(old["$defs"][original])

        def pin_references(value: Any) -> None:
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and reference.startswith("#/"):
                    value["$ref"] = OLD + reference
                for child in value.values():
                    pin_references(child)
            elif isinstance(value, list):
                for child in value:
                    pin_references(child)

        pin_references(definition)
        properties = definition["properties"]
        properties["schema_version"] = {"const": version}
        properties["index_manifest"]["properties"] = {
            "member_path": {"const": "index.json"},
            "schema_ref": {"const": "eom://schemas/knowledge/embedding-index-manifest/4.0"},
            "media_type": {"const": "application/json"},
        }
        definition["required"] = list(properties)
        definitions[name] = definition
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/knowledge/public-solution-embedding-registry/4.0",
        "title": "Exact index4 registration command and historical replay receipt",
        "$defs": definitions,
        "oneOf": [{"$ref": "#/$defs/" + name} for name in definitions],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = (json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (SCHEMAS, PACKAGED):
        path = directory / "public-solution-embedding-registry-v4.schema.json"
        if arguments.check:
            if not path.is_file() or path.read_bytes() != payload:
                raise SystemExit(f"generated schema differs: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
