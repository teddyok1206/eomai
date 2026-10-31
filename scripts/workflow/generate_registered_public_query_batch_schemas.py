#!/usr/bin/env python3
"""Successor metadata only; original routes, allocations and numeric batches stay pinned."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def schemas():
    batch = (ROOT / "schemas/workflow/embedding-batch-plan-v1.4.schema.json").read_text()
    batch = batch.replace(
        "eom://schemas/workflow/embedding-batch-plan/1.4",
        "eom://schemas/workflow/embedding-batch-plan/1.5",
    )
    batch = batch.replace('"embedding-batch-plan/1.4"', '"embedding-batch-plan/1.5"')
    batch = batch.replace(
        "eom://schemas/knowledge/public-solution-similarity/3.0",
        "eom://schemas/knowledge/public-solution-similarity/4.0",
    )
    body = json.loads(batch)
    body["title"] = "Registered public-solution QUERY pins over unchanged numerical batch2"
    preparation = json.loads(
        (ROOT / "schemas/workflow/reference-query-routed-preparation-v2.schema.json").read_bytes()
    )
    preparation["$id"] = "eom://schemas/workflow/reference-query-routed-preparation/3.0"
    preparation["title"] = "Pinned registered public QUERY preparation, never authority"
    preparation["properties"]["schema_version"]["const"] = "reference-query-routed-preparation/3.0"
    preparation["properties"]["parent"]["$ref"] = (
        "eom://schemas/workflow/embedding-batch-plan/1.5#/$defs/request"
    )
    return {
        "embedding-batch-plan-v1.5.schema.json": body,
        "reference-query-routed-preparation-v3.schema.json": preparation,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    for name, body in schemas().items():
        raw = (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode()
        for directory in (
            ROOT / "schemas/workflow",
            ROOT / "packages/workflow/eom_workflow/resources",
        ):
            path = directory / name
            if arguments.check:
                if path.read_bytes() != raw:
                    raise SystemExit("registered public QUERY metadata differs: " + str(path))
            else:
                path.write_bytes(raw)


if __name__ == "__main__":
    main()
