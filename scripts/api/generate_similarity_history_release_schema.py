"""Mechanical successor for additive owned-search metadata; frozen schema15 stays unchanged."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_15.schema.json").read_bytes()
    )
    schema["$id"] = "eom://operations/release-operator-context/1.16"
    for definition, version in (
        ("context", "release-operator-context/1.16"),
        ("receipt", "release-operator-admission/1.16"),
    ):
        properties = schema["$defs"][definition]["properties"]
        properties["schema_version"] = {"const": version}
        properties["migration_revision"] = {"const": "20261102_0069"}
    raw = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
    for path in (
        ROOT / "scripts/api/release_operator_context_v1_16.schema.json",
        ROOT / "schemas/operations/release-operator-context-v1_16.schema.json",
    ):
        if args.check:
            if path.read_bytes() != raw:
                raise SystemExit("owned search history release schema differs")
        else:
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
