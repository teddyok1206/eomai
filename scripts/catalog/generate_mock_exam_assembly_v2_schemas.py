#!/usr/bin/env python3
"""Generate paired V3-content mock-exam Assembly schemas from immutable V1/V2 inputs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas" / "assessment-assembly"
PACKAGED = (
    ROOT
    / "packages"
    / "catalog_contracts"
    / "eom_catalog_contracts"
    / "resources"
    / "assessment-assembly"
)


def _write(name: str, value: dict[str, object]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    for root in (CANONICAL, PACKAGED):
        (root / name).write_text(payload, encoding="utf-8")


def main() -> None:
    plan = json.loads((CANONICAL / "mock-exam-assembly-plan-v1.schema.json").read_text())
    plan["$id"] = "eom://schemas/assessment-assembly/mock-exam-assembly-plan/2.0"
    plan["title"] = "Mock Exam Assembly Plan V2"
    plan["properties"]["schema_version"] = {"const": "mock-exam-assembly-plan/2.0"}
    pointer = plan["$defs"]["contentPointer"]
    pointer["properties"]["schema_ref"] = {"const": "eom.assessment.item-content/3.0"}
    pointer["properties"]["editorial_markdown_schema_ref"] = {
        "const": "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
    }
    pointer["required"].append("editorial_markdown_schema_ref")
    plan["$defs"]["placement"]["properties"]["source_score_display"] = {
        "enum": ["1.5", "2", "2.5", "3"]
    }
    _write("mock-exam-assembly-plan-v2.schema.json", plan)

    manifest = copy.deepcopy(
        json.loads((CANONICAL / "mock-exam-assembly-manifest-v2.schema.json").read_text())
    )
    manifest["$id"] = "eom://schemas/assessment-assembly/mock-exam-assembly-manifest/3.0"
    manifest["title"] = "Mock Exam Assembly Manifest V3"
    manifest["properties"]["schema_version"] = {"const": "mock-exam-assembly-manifest/3.0"}
    manifest["properties"]["plan"] = {
        "$ref": "eom://schemas/assessment-assembly/mock-exam-assembly-plan/2.0"
    }
    _write("mock-exam-assembly-manifest-v3.schema.json", manifest)


if __name__ == "__main__":
    main()
