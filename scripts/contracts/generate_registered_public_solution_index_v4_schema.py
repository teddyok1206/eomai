#!/usr/bin/env python3
"""Closed metadata successor; retain original binding3 and numerical shard identities."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "schemas/knowledge"
PACKAGED = ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
OLD = "eom://schemas/knowledge/public-solution-embedding-index/3.0"
ENTRY = "eom://schemas/knowledge/public-solution-embedding-entry/2.0"


def build_contract() -> dict[str, Any]:
    old = json.loads((KNOWLEDGE / "public-solution-embedding-index-v3.schema.json").read_bytes())
    if not isinstance(old, dict):
        raise ValueError("schema source must be an object")
    definitions = {}
    for new, original in (
        ("registeredProfile", "PublicSolutionProfilePointer"),
        ("registeredBinding", "PublicSolutionEmbeddingSourceBinding"),
        ("publicIndex", "PublicSolutionEmbeddingIndex"),
    ):
        definition = copy.deepcopy(old["$defs"][original])

        def pin_old_refs(value: Any) -> None:
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and reference.startswith("#/$defs/"):
                    value["$ref"] = OLD + reference
                for child in value.values():
                    pin_old_refs(child)
            elif isinstance(value, list):
                for child in value:
                    pin_old_refs(child)

        pin_old_refs(definition)
        definition["required"] = list(definition["properties"])
        definitions[new] = definition
    profile = definitions["registeredProfile"]["properties"]
    profile["schema_ref"] = {"const": ENTRY}
    binding = definitions["registeredBinding"]["properties"]
    binding["schema_version"] = {"const": "embedding-source-binding/4.0"}
    binding["source"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/approvedItemSource",
        "properties": {"source_class": {"const": "APPROVED_ITEM"}},
    }
    binding["profile"] = {"$ref": "#/$defs/registeredProfile"}
    binding["evidence"] = {"$ref": ENTRY + "#/$defs/registeredEvidence"}
    index = definitions["publicIndex"]["properties"]
    index["schema_version"] = {"const": "embedding-index-manifest/4.0"}
    index["bindings"]["items"] = {
        "oneOf": [
            {"$ref": OLD + "#/$defs/PublicSolutionEmbeddingSourceBinding"},
            {"$ref": "#/$defs/registeredBinding"},
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/knowledge/public-solution-embedding-index/4.0",
        "title": (
            "Unchanged public numerical rows with exact historical and registered report bindings"
        ),
        "$defs": definitions,
        "oneOf": [{"$ref": "#/$defs/" + name} for name in definitions],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = (json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (KNOWLEDGE, PACKAGED):
        path = directory / "public-solution-embedding-index-v4.schema.json"
        if arguments.check:
            if not path.is_file() or path.read_bytes() != payload:
                raise SystemExit(f"generated schema differs: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
