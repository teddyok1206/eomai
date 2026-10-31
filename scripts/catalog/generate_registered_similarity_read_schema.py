#!/usr/bin/env python3
"""Closed completed-read4 carrier for existing public context3 and registered context4."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "knowledge/system-rag-similarity-read-v4.schema.json"


def schema():
    body = json.loads(
        (ROOT / "schemas/knowledge/system-rag-similarity-read-v3.schema.json").read_bytes()
    )
    body["$id"] = "eom://schemas/knowledge/system-rag-similarity-read/4.0"
    body["title"] = "Exact past/creative/registered public completed QUERY read V4"
    body["$defs"]["request"]["properties"]["schema_version"]["const"] = (
        "system-rag-similarity-read-request/4.0"
    )
    body["$defs"]["reply"]["properties"]["schema_version"]["const"] = (
        "system-rag-similarity-read-reply/4.0"
    )
    choices = body["$defs"]["reply"]["properties"]["result"]["anyOf"]
    choices.insert(
        1, {"$ref": "eom://schemas/knowledge/public-solution-similarity/4.0#/$defs/context"}
    )
    body["$defs"]["reply"]["allOf"][0]["then"]["properties"]["result"]["allOf"][0] = {
        "oneOf": choices[:2],
    }
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    raw = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for path in (
        ROOT / "schemas" / NAME,
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / NAME,
    ):
        if arguments.check:
            if path.read_bytes() != raw:
                raise SystemExit("registered similarity read schema differs: " + str(path))
        else:
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
