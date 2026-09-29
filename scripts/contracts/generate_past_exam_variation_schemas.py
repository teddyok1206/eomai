#!/usr/bin/env python3
"""Generate successor wire schemas for one-to-one past-exam variation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _write_pair(
    relative: str,
    package_relative: str,
    file_name: str,
    value: dict[str, object],
) -> None:
    Draft202012Validator.check_schema(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for root in (ROOT / relative, ROOT / package_relative):
        path = root / file_name
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"generated variation schema drifted: {path}")
        path.write_bytes(payload)


def _catalog_application_v17() -> dict[str, object]:
    source = json.loads(
        (
            ROOT / "schemas/catalog-application/catalog-application-request-v16.schema.json"
        ).read_text(encoding="utf-8")
    )
    if not isinstance(source, dict):
        raise ValueError("Catalog application V16 is not an object")
    value = deepcopy(source)
    value["$id"] = "eom://schemas/catalog-application/catalog-application-request-v17"
    value["title"] = "EOM Catalog Item Production Evidence Request V17"
    properties = value["properties"]
    assert isinstance(properties, dict)
    properties["requirement"] = {
        "oneOf": [
            {"$ref": "eom://schemas/knowledge/educational-retrieval-requirement/1.0"},
            {"$ref": "eom://schemas/knowledge/educational-retrieval-requirement/2.0"},
        ]
    }
    return value


def _workflow_start_v4() -> dict[str, object]:
    source = json.loads(
        (ROOT / "schemas/api/v1/workflow-start-v3.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(source, dict):
        raise ValueError("Workflow Start V3 is not an object")
    value = deepcopy(source)
    value["$id"] = "eom://schemas/api/v1/workflow-start/4.0"
    value["title"] = "Workflow Start Request V4"
    value["oneOf"] = [
        {"$ref": "eom://schemas/api/v1/workflow-start/3.0"},
        {"$ref": "#/$defs/past_exam_variation_start"},
    ]
    definitions = value["$defs"]
    assert isinstance(definitions, dict)
    historical = definitions["content_team_v4_start"]
    assert isinstance(historical, dict)
    successor = deepcopy(historical)
    properties = successor["properties"]
    assert isinstance(properties, dict)
    properties["definition_version"] = {"const": "1.14.0"}
    properties["registry_mode"] = {"const": "CREATE_ITEM", "default": "CREATE_ITEM"}
    properties["item_id"] = {"type": "null", "default": None}
    properties["base_revision_id"] = {"type": "null", "default": None}
    properties["educational_retrieval"] = {
        "$ref": "eom://schemas/knowledge/educational-retrieval-requirement/2.0"
    }
    definitions["past_exam_variation_start"] = successor
    return value


def _resolved_execution_plan_v16() -> dict[str, object]:
    source = json.loads(
        (ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v12.schema.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(source, dict):
        raise ValueError("Resolved Execution Plan V12 is not an object")
    value = deepcopy(source)
    value["$id"] = "eom://schemas/workflow/resolved-execution-plan/16.0"
    value["title"] = "Resolved Execution Plan V16"
    properties = value["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": "resolved-execution-plan/16.0"}
    properties["workflow_definition_key"] = {"const": "generic-item-development"}
    properties["workflow_definition_version"] = {"const": "1.14.0"}
    properties["retrieval_requirement"] = {
        "$ref": "eom://schemas/knowledge/educational-retrieval-requirement/2.0"
    }
    properties["resolver_version"] = {"const": "16.0.0"}
    return value


def main() -> None:
    _write_pair(
        "schemas/catalog-application",
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        "catalog-application-request-v17.schema.json",
        _catalog_application_v17(),
    )
    _write_pair(
        "schemas/api/v1",
        "packages/api_contracts/eom_api_contracts/schemas",
        "workflow-start-v4.schema.json",
        _workflow_start_v4(),
    )
    _write_pair(
        "schemas/workflow/control-plane",
        "packages/workflow/eom_workflow/resources/control-plane",
        "resolved-execution-plan-v16.schema.json",
        _resolved_execution_plan_v16(),
    )


if __name__ == "__main__":
    main()
