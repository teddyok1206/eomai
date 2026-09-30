#!/usr/bin/env python3
"""Generate the API successor for explicit natural/labeled IMAGE presentation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _write_pair(file_name: str, value: dict[str, object]) -> None:
    Draft202012Validator.check_schema(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for root in (
        ROOT / "schemas/api/v1",
        ROOT / "packages/api_contracts/eom_api_contracts/schemas",
    ):
        path = root / file_name
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"generated natural-presentation schema drifted: {path}")
        path.write_bytes(payload)


def _write_web(file_name: str, value: dict[str, object]) -> None:
    Draft202012Validator.check_schema(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path = ROOT / "schemas/web-gui" / file_name
    if path.exists() and path.read_bytes() != payload:
        raise ValueError(f"generated natural-presentation schema drifted: {path}")
    path.write_bytes(payload)


def _workflow_start_v5() -> dict[str, object]:
    source = json.loads(
        (ROOT / "schemas/api/v1/workflow-start-v4.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(source, dict):
        raise ValueError("Workflow Start V4 is not an object")
    value = deepcopy(source)
    value["$id"] = "eom://schemas/api/v1/workflow-start/5.0"
    value["title"] = "Workflow Start Request V5"
    value["oneOf"] = [
        {"$ref": "eom://schemas/api/v1/workflow-start/4.0"},
        {"$ref": "#/$defs/content_team_natural_presentation_start"},
        {"$ref": "#/$defs/past_exam_natural_presentation_start"},
    ]
    definitions = value["$defs"]
    assert isinstance(definitions, dict)
    brief_v4 = definitions["content_team_item_brief_v4"]
    assert isinstance(brief_v4, dict)
    brief_v5 = deepcopy(brief_v4)
    brief_properties = brief_v5["properties"]
    assert isinstance(brief_properties, dict)
    brief_properties["schema_version"] = {"const": "5.0"}
    brief_properties["material_requirement"] = {
        "$ref": "eom://schemas/workflow/content-team-material-requirement/2.0"
    }
    definitions["content_team_item_brief_v5"] = brief_v5

    general_v4 = definitions["content_team_v4_start"]
    assert isinstance(general_v4, dict)
    general_v5 = deepcopy(general_v4)
    general_properties = general_v5["properties"]
    assert isinstance(general_properties, dict)
    general_properties["definition_version"] = {"const": "1.15.0"}
    general_properties["item_brief"] = {"$ref": "#/$defs/content_team_item_brief_v5"}
    definitions["content_team_natural_presentation_start"] = general_v5

    variation_v4 = definitions["past_exam_variation_start"]
    assert isinstance(variation_v4, dict)
    variation_v5 = deepcopy(variation_v4)
    variation_properties = variation_v5["properties"]
    assert isinstance(variation_properties, dict)
    variation_properties["definition_version"] = {"const": "1.15.0"}
    variation_properties["item_brief"] = {"$ref": "#/$defs/content_team_item_brief_v5"}
    definitions["past_exam_natural_presentation_start"] = variation_v5
    return value


def _request_draft_v6() -> dict[str, object]:
    source = json.loads(
        (ROOT / "schemas/web-gui/request-draft-v5.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(source, dict):
        raise ValueError("Request Draft V5 is not an object")
    value = deepcopy(source)
    value["$id"] = "https://eom.local/schemas/web-gui/request-draft-v6.schema.json"
    value["title"] = "EOM Web GUI Request Draft V6"
    properties = value["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": "6.0"}
    properties["material_requirement"] = {
        "$ref": "eom://schemas/workflow/content-team-material-requirement/2.0"
    }
    return value


def main() -> None:
    _write_pair("workflow-start-v5.schema.json", _workflow_start_v5())
    _write_web("request-draft-v6.schema.json", _request_draft_v6())


if __name__ == "__main__":
    main()
