#!/usr/bin/env python3
"""Generate immutable item-workflow V6 schemas without changing historical V5 bytes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/roles"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/roles"
V5_SHA256 = {
    "authoring": "9cc1b0579b186fb9d26329734b8f82ed814ae2cff22a17a2c76af2cfc61def9e",
    "image": "957f9ec6863df0de76540d9f8a666299e45883239f806bafb745bf37f23fcfc4",
    "review": "aa50f25d107e02ead3c8711802adb69171050f078011ef6a2480b208cfe11d4a",
    "registration": "97aa836b02139b98a769ce4a70fc9e03dbef288970cb5b9beb71972975ef8283",
}
DETERMINISTIC_REASONS = [
    "DATA_VISUALIZATION",
    "SCIENTIFIC_SCHEMATIC",
    "GEOMETRIC_DIAGRAM",
    "MAP_OR_SPATIAL_DIAGRAM",
]
HYBRID_REASONS = [
    "HUMAN_OR_ANIMAL_REQUIRED",
    "ORGANIC_OBJECT_REQUIRED",
    "REALISTIC_NATURAL_SCENE_REQUIRED",
    "COMPLEX_NATURAL_TEXTURE_REQUIRED",
]


def _replace_v5_names(value: object) -> object:
    if isinstance(value, str):
        return value.replace("V5", "V6").replace("result-v5", "result-v6")
    if isinstance(value, list):
        return [_replace_v5_names(item) for item in value]
    if isinstance(value, dict):
        return {key.replace("V5", "V6"): _replace_v5_names(item) for key, item in value.items()}
    return value


def _line_plan(schema: dict[str, Any]) -> None:
    properties = schema["properties"]
    properties["route_reason"] = {"type": "string", "const": "DATA_VISUALIZATION"}
    schema["required"].append("route_reason")


def _vector_plan(schema: dict[str, Any]) -> None:
    properties = schema["properties"]
    properties["production_route"] = {
        "type": "string",
        "enum": ["DETERMINISTIC_SVG", "HYBRID_LOCAL_GENERATIVE"],
    }
    properties["route_reason"] = {
        "type": "string",
        "enum": [*DETERMINISTIC_REASONS, *HYBRID_REASONS],
    }
    properties["generation_prompt"] = {
        "anyOf": [
            {"type": "string", "minLength": 1, "maxLength": 4000},
            {"type": "null"},
        ]
    }
    schema["required"].append("route_reason")
    deterministic = deepcopy(schema)
    deterministic["properties"]["production_route"] = {
        "type": "string",
        "const": "DETERMINISTIC_SVG",
    }
    deterministic["properties"]["route_reason"] = {
        "type": "string",
        "enum": DETERMINISTIC_REASONS,
    }
    deterministic["properties"]["generation_prompt"] = {"type": "null"}
    deterministic["properties"]["negative_prompt"] = {"type": "null"}
    hybrid = deepcopy(schema)
    hybrid["properties"]["kind"] = {
        "type": "string",
        "enum": ["natural_scene", "composite"],
    }
    hybrid["properties"]["production_route"] = {
        "type": "string",
        "const": "HYBRID_LOCAL_GENERATIVE",
    }
    hybrid["properties"]["route_reason"] = {
        "type": "string",
        "enum": HYBRID_REASONS,
    }
    hybrid["properties"]["generation_prompt"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 4000,
    }
    schema.clear()
    schema["anyOf"] = [deterministic, hybrid]


def _load_v5(role: str) -> dict[str, Any]:
    path = CANONICAL / f"{role}-result-v5.schema.json"
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != V5_SHA256[role]:
        raise RuntimeError(f"historical {role} V5 schema bytes changed")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError(f"historical {role} V5 schema is not an object")
    replaced = _replace_v5_names(value)
    if not isinstance(replaced, dict):
        raise RuntimeError("generated schema is not an object")
    return replaced


def _generate(role: str) -> dict[str, Any]:
    schema = _load_v5(role)
    schema["$id"] = f"https://eom.local/schemas/workflow/roles/{role}-result-v6.schema.json"
    schema["properties"]["protocol_version"] = {
        "type": "string",
        "const": "workflow-role/1.13.0",
    }
    if role == "authoring":
        _line_plan(schema["$defs"]["GeneratedLineGraphImageBriefV6"])
        _vector_plan(schema["$defs"]["GeneratedVectorImageBriefV6"])
    elif role == "image":
        _line_plan(schema["$defs"]["GeneratedLineGraphDrawingV6"])
        _vector_plan(schema["$defs"]["GeneratedVectorDrawingV6"])
    Draft202012Validator.check_schema(schema)
    return schema


def main() -> None:
    for role in ("authoring", "image", "review", "registration"):
        payload = (
            json.dumps(_generate(role), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        for root in (CANONICAL, PACKAGED):
            (root / f"{role}-result-v6.schema.json").write_bytes(payload)


if __name__ == "__main__":
    main()
