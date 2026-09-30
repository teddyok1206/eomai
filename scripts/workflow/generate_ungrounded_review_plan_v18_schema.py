#!/usr/bin/env python3
"""Generate the immutable ungrounded review-escalation execution-plan V18 schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1_SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v1.schema.json"
V12_SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v12.schema.json"
TARGETS = (
    ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v18.schema.json",
    ROOT / "packages/workflow/eom_workflow/resources/control-plane/"
    "resolved-execution-plan-v18.schema.json",
)


def main() -> None:
    schema = json.loads(V1_SOURCE.read_text(encoding="utf-8"))
    verification_schema = json.loads(V12_SOURCE.read_text(encoding="utf-8"))
    step = schema["properties"]["steps"]["items"]
    verification_step = verification_schema["properties"]["steps"]["items"]

    schema["$id"] = "eom://schemas/workflow/resolved-execution-plan/18.0"
    schema["title"] = "EOM Ungrounded Review Escalation Resolved Execution Plan V18"
    schema["properties"]["schema_version"]["const"] = "resolved-execution-plan/18.0"
    schema["properties"]["workflow_definition_version"] = {"const": "1.15.0"}
    schema["properties"]["graph_snapshot_revision_id"] = {"type": "null"}
    schema["properties"]["evidence_bundle_revision_id"] = {"type": "null"}
    schema["properties"]["resolver_version"] = {"const": "18.0.0"}
    for field in ("graph_snapshot_revision_id", "evidence_bundle_revision_id"):
        if field not in schema["required"]:
            schema["required"].append(field)

    step["properties"]["evidence_access"] = {"const": "NONE"}
    step["properties"]["escalation_candidate"] = copy.deepcopy(
        verification_step["properties"]["escalation_candidate"]
    )
    step["required"].extend(["evidence_access", "escalation_candidate"])

    payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for target in TARGETS:
        target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
