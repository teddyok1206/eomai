#!/usr/bin/env python3
"""Synchronize canonical science-assessment corpus schemas into the Catalog wheel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = ROOT / "schemas" / "legacy-assessment"
PACKAGE_ROOT = (
    ROOT
    / "packages"
    / "catalog_contracts"
    / "eom_catalog_contracts"
    / "resources"
    / "legacy-assessment"
)
SCHEMAS = (
    "science-assessment-web-acquisition-v1.schema.json",
    "science-assessment-web-corpus-manifest-v1.schema.json",
    "science-assessment-web-corpus-plan-v1.schema.json",
)


def main() -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    for name in SCHEMAS:
        PACKAGE_ROOT.joinpath(name).write_bytes(CANONICAL_ROOT.joinpath(name).read_bytes())


if __name__ == "__main__":
    main()
