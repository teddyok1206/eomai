#!/usr/bin/env python3
"""Extend only the native request's metadata carrier; retain numerical QUERY2 closure."""

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "reference-query-workflow-request-v4.schema.json"
SCHEMA_ID = "eom://schemas/workflow/reference-query-workflow-request/4.0"


def schema():
    previous = json.loads(
        (ROOT / "schemas/workflow/reference-query-execution-v2.schema.json").read_bytes()
    )
    request = copy.deepcopy(previous["$defs"]["request"])
    assert request["$id"] == "eom://schemas/workflow/reference-query-workflow-request/3.0"
    request["$id"] = SCHEMA_ID
    request["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    request["title"] = "Registered public solution metadata over unchanged numerical QUERY2"
    request["properties"]["schema_version"] = {"const": "reference-query-workflow-request/4.0"}
    request["properties"]["context_request"] = {
        "$ref": "eom://schemas/knowledge/public-solution-similarity/4.0#/$defs/request"
    }
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    raw = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for path in (
        ROOT / "schemas/workflow" / NAME,
        ROOT / "packages/workflow/eom_workflow/resources" / NAME,
    ):
        if arguments.check:
            if path.read_bytes() != raw:
                raise SystemExit("registered native query request schema differs: " + str(path))
        else:
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
