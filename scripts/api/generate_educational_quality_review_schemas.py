#!/usr/bin/env python3
"""Synchronize canonical educational-quality schemas into the API contract wheel."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/api/v1"
PACKAGED = ROOT / "packages/api_contracts/eom_api_contracts/schemas"
NAMES = (
    "educational-quality-review-command-v1.schema.json",
    "educational-quality-review-workbench-v1.schema.json",
)


def generate(*, check: bool) -> None:
    drift: list[str] = []
    for name in NAMES:
        source = (CANONICAL / name).read_bytes()
        target = PACKAGED / name
        if target.exists() and target.read_bytes() == source:
            continue
        if check:
            drift.append(name)
        else:
            target.write_bytes(source)
    if drift:
        raise SystemExit("educational-quality schema mirrors drifted: " + ", ".join(drift))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generate(check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
