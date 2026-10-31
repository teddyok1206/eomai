#!/usr/bin/env python3
"""Closed INDEX source-proof carrier; preserve allocation and numerical protocols."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def schema():
    body = json.loads((ROOT / "schemas/workflow/embedding-batch-plan-v1.3.schema.json").read_text())
    body["$id"] = "eom://schemas/workflow/embedding-batch-plan/1.6"
    body["title"] = "Registered public INDEX proofs over unchanged allocation and numeric frames"
    body["$defs"]["anchor"] = {
        "$ref": "eom://schemas/knowledge/public-solution-similarity/4.0#/$defs/anchor"
    }
    for kind in ("selection", "request"):
        body["$defs"][kind]["properties"]["schema_version"]["const"] = "embedding-batch-plan/1.6"
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    raw = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (
        ROOT / "schemas/workflow",
        ROOT / "packages/workflow/eom_workflow/resources",
    ):
        path = directory / "embedding-batch-plan-v1.6.schema.json"
        if arguments.check:
            if path.read_bytes() != raw:
                raise SystemExit("registered public INDEX metadata differs: " + str(path))
        else:
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
