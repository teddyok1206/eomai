"""Add Office-native successors without changing any released predecessor bytes."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> dict:
    return json.loads((ROOT / "schemas/external-item" / name).read_bytes())


def _write(stem: str, value: dict) -> None:
    Draft202012Validator.check_schema(value)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    for folder in (
        ROOT / "schemas/external-item",
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/external-item",
    ):
        (folder / (stem + ".schema.json")).write_text(payload, encoding="utf-8")


def main() -> None:
    work = _read("external-item-learning-work-input-v1.schema.json")
    work["$id"] = "eom://schemas/external-item/learning-work-input/2.0"
    work["title"] = "Office-native Item learning input with exact picture-use Artifact"
    work["properties"]["schema_version"]["const"] = "external-item-learning-work-input/2.0"
    work["required"].append("office_artifact")
    office = copy.deepcopy(work["$defs"]["page_artifact"])
    office["properties"]["artifact_type"]["const"] = "control_office_picture_use_catalog"
    office["properties"]["member_path"]["const"] = "picture-use-catalog.json"
    office["properties"]["schema_ref"]["const"] = (
        "eom://schemas/image-provider/office-picture-use-catalog/1.0"
    )
    work["$defs"]["office_artifact"] = office
    work["properties"]["office_artifact"] = {"$ref": "#/$defs/office_artifact"}
    _write("external-item-learning-work-input-v2", work)

    binding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["block_id", "picture_use_id", "source_region_id", "selection_reason"],
        "properties": {
            "block_id": {"type": "string", "pattern": "^block_[a-z][a-z0-9_]{0,63}$"},
            "picture_use_id": {"type": "string", "pattern": "^officeobj_[0-9a-f]{32}$"},
            "source_region_id": {
                "$ref": "eom://schemas/external-item/learning-result/1.0#/$defs/regionId"
            },
            "selection_reason": {"type": "string", "minLength": 1, "maxLength": 1500},
        },
    }
    result = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/external-item/office-visual-bindings/1.0",
        "title": "Original Office picture-use bindings for an unchanged source analysis",
        "type": "object",
        "additionalProperties": False,
        "required": ["office_catalog_sha256", "bindings"],
        "properties": {
            "office_catalog_sha256": {
                "$ref": "eom://schemas/external-item/learning-result/1.0#/$defs/sha256"
            },
            "bindings": {
                "type": "array",
                "maxItems": 64,
                "items": {"$ref": "#/$defs/officeBinding"},
            },
        },
        "$defs": {"officeBinding": binding},
    }
    _write("office-visual-bindings-v1", result)

    for category, previous, stem in (
        ("roles", "external-item-learning-input-v2", "external-item-learning-input-v3"),
        ("roles", "external-item-learning-result-v2", "external-item-learning-result-v3"),
        ("control-plane", "resolved-execution-plan-v28", "resolved-execution-plan-v32"),
    ):
        schema = json.loads(
            (ROOT / "schemas/workflow" / category / (previous + ".schema.json")).read_bytes()
        )
        schema["$id"] = schema["$id"].replace(previous, stem).replace("/28.0", "/32.0")
        properties = schema["properties"]
        if category == "roles":
            properties["protocol_version"]["const"] = "workflow-role/1.36.0"
            if "input" in stem:
                properties["request"]["properties"]["work_input"]["$ref"] = work["$id"]
            else:
                properties["output"]["required"].append("office_visuals")
                properties["output"]["properties"]["office_visuals"] = {"$ref": result["$id"]}
        else:
            schema["title"] = "Office-native Item learning resolved execution plan V32"
            properties["schema_version"]["const"] = "resolved-execution-plan/32.0"
            properties["resolver_version"]["const"] = "32.0.0"
            properties["workflow_definition_version"]["const"] = "3.0.0"
            properties["work_input"]["$ref"] = work["$id"]
        Draft202012Validator.check_schema(schema)
        payload = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        for folder in (
            ROOT / "schemas/workflow" / category,
            ROOT / "packages/workflow/eom_workflow/resources" / category,
        ):
            (folder / (stem + ".schema.json")).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
