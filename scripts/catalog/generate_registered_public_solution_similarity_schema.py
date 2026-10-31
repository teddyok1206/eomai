#!/usr/bin/env python3
"""Metadata4 reuses closed predecessor values and the unchanged numerical QUERY2."""

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "knowledge/public-solution-similarity-v4.schema.json"
OLD = "eom://schemas/knowledge/public-solution-similarity/3.0"
NEW = "eom://schemas/knowledge/public-solution-similarity/4.0"
ENTRY = "eom://schemas/knowledge/public-solution-embedding-entry/2.0"
INDEX = "eom://schemas/knowledge/public-solution-embedding-index/4.0"


def externalize(value):
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            value["$ref"] = OLD + reference
        for child in value.values():
            externalize(child)
    elif isinstance(value, list):
        for child in value:
            externalize(child)


def schema():
    previous = json.loads(
        (ROOT / "schemas/knowledge/public-solution-similarity-v3.schema.json").read_bytes()
    )
    definitions = copy.deepcopy(previous["$defs"])
    externalize(definitions)
    registered = copy.deepcopy(definitions["anchor"])
    registered["properties"].update(
        {
            "source": {"$ref": ENTRY + "#/properties/source"},
            "profile": {"$ref": INDEX + "#/$defs/registeredProfile"},
            "evidence": {"$ref": ENTRY + "#/$defs/registeredEvidence"},
        }
    )
    candidate = copy.deepcopy(registered)
    candidate["required"].append("observation")
    candidate["properties"]["observation"] = definitions["candidate"]["properties"]["observation"]
    index_pin = copy.deepcopy(definitions["indexPin"])
    index_pin["properties"]["index_manifest"] = {
        "allOf": [
            index_pin["properties"]["index_manifest"],
            {
                "properties": {
                    "member_path": {"const": "index.json"},
                    "schema_ref": {
                        "enum": [
                            "eom://schemas/knowledge/embedding-index-manifest/3.0",
                            "eom://schemas/knowledge/embedding-index-manifest/4.0",
                        ]
                    },
                    "media_type": {"const": "application/json"},
                }
            },
        ]
    }
    view, request, context = (
        copy.deepcopy(definitions[key]) for key in ("view", "request", "context")
    )
    view["properties"]["index"] = {"$ref": "#/$defs/indexPin"}
    request["properties"].update(
        {
            "schema_version": {"const": "system-rag-similarity-request/4.0"},
            "anchor": {"$ref": "#/$defs/anchor"},
            "views": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"$ref": "#/$defs/view"},
            },
        }
    )
    context["properties"].update(
        {
            "schema_version": {"const": "system-rag-similarity-context/4.0"},
            "request": {"$ref": "#/$defs/request"},
            "candidates": {"type": "array", "maxItems": 64, "items": {"$ref": "#/$defs/candidate"}},
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": NEW,
        "title": "Pinned past/creative/registered public solution observations over QUERY2",
        "oneOf": [{"$ref": "#/$defs/request"}, {"$ref": "#/$defs/context"}],
        "$defs": {
            "anchor": {
                "oneOf": [{"$ref": OLD + "#/$defs/anchor"}, {"$ref": "#/$defs/registeredAnchor"}]
            },
            "registeredAnchor": registered,
            "indexPin": index_pin,
            "view": view,
            "request": request,
            "candidate": {
                "oneOf": [
                    {"$ref": OLD + "#/$defs/candidate"},
                    {"$ref": "#/$defs/registeredCandidate"},
                ]
            },
            "registeredCandidate": candidate,
            "context": context,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for path in (
        ROOT / "schemas" / NAME,
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / NAME,
    ):
        if arguments.check:
            if path.read_bytes() != payload:
                raise SystemExit("registered public similarity schema differs: " + str(path))
        else:
            path.write_bytes(payload)


if __name__ == "__main__":
    main()
