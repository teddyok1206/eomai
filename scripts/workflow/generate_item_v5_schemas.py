#!/usr/bin/env python3
"""Generate the immutable item-workflow V5 role schema family from reviewed V4 sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/roles"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/roles"
V4_SHA256 = {
    "authoring": "574f6e639b490e4ccdb5575eb69ab1f5449d9ef0cdcfdb10ff5c5502ba71fee8",
    "image": "98f31f61396be3acd262c4adb07b4f560ed0469bd7d4c4b854a4c1a16846bd1f",
    "review": "97734037944887cce2d28527b811c68824fc5d0efb1ad8e68f050f8263785acd",
    "registration": "0f6d39e3bdeaaf527bf3563621f76270f6f7d30e89cded3829f30f4e56f6b308",
}


def _text(*, maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _string_array(*, minimum: int, maximum: int, item_maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "items": _text(maximum=item_maximum),
    }


def _line_brief() -> dict[str, Any]:
    properties = {
        "kind": {"type": "string", "const": "line_graph"},
        "production_route": {"type": "string", "const": "DETERMINISTIC_SVG"},
        "background_style": {"type": "string", "enum": ["WHITE", "GRID", "PAPER"]},
        "block_id": {"type": "string", "const": "block_image"},
        "alt_text": _text(maximum=1000),
        "x_axis_label": {"type": "string", "pattern": r"^[A-Za-z0-9 ()/_-]{1,24}$"},
        "y_axis_label": {"type": "string", "pattern": r"^[A-Za-z0-9 ()/_-]{1,24}$"},
        "series_label": {"type": "string", "pattern": r"^[A-Za-z0-9 ()/_-]{1,24}$"},
        "x_values": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "integer"}},
        "y_values": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "integer"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _vector_brief() -> dict[str, Any]:
    properties = {
        "kind": {
            "type": "string",
            "enum": ["diagram", "apparatus", "map", "particle_model", "natural_scene", "composite"],
        },
        "production_route": {
            "type": "string",
            "enum": [
                "DETERMINISTIC_SVG",
                "LOCAL_GENERATIVE_BACKGROUND",
                "HUMAN_REVIEWED_BACKGROUND",
            ],
        },
        "background_style": {"type": "string", "enum": ["WHITE", "GRID", "PAPER"]},
        "block_id": {"type": "string", "const": "block_image"},
        "alt_text": _text(maximum=1000),
        "scene_description": _text(maximum=4000),
        "scientific_constraints": _string_array(minimum=1, maximum=16, item_maximum=500),
        "required_labels": _string_array(minimum=0, maximum=16, item_maximum=64),
        "generation_prompt": _text(maximum=4000),
        "negative_prompt": {
            "anyOf": [
                {"type": "string", "maxLength": 2000},
                {"type": "null"},
            ]
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _line_drawing() -> dict[str, Any]:
    schema = _line_brief()
    properties = schema["properties"]
    properties.update(
        {
            "width_px": {"type": "integer", "const": 800},
            "height_px": {"type": "integer", "const": 500},
            "stroke_color": {"type": "string", "enum": ["blue", "green", "orange"]},
            "point_style": {"type": "string", "enum": ["circle", "square"]},
        }
    )
    schema["required"] = list(properties)
    return schema


def _vector_drawing() -> dict[str, Any]:
    schema = _vector_brief()
    properties = schema["properties"]
    properties.update(
        {
            "width_px": {"type": "integer", "const": 800},
            "height_px": {"type": "integer", "const": 500},
            "svg_overlay": {"type": "string", "minLength": 64, "maxLength": 65536},
        }
    )
    schema["required"] = list(properties)
    return schema


def _load_v4(role: str) -> dict[str, Any]:
    path = CANONICAL / f"{role}-result-v4.schema.json"
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != V4_SHA256[role]:
        raise RuntimeError(f"historical {role} V4 schema bytes changed")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError(f"historical {role} V4 schema is not an object")
    return value


def _generate(role: str) -> dict[str, Any]:
    schema = _load_v4(role)
    schema["$id"] = f"https://eom.local/schemas/workflow/roles/{role}-result-v5.schema.json"
    schema["properties"]["protocol_version"] = {
        "type": "string",
        "const": "workflow-role/1.12.0",
    }
    if role == "authoring":
        schema["$defs"]["GeneratedImageBrief"] = {
            "anyOf": [
                {"$ref": "#/$defs/GeneratedLineGraphImageBriefV5"},
                {"$ref": "#/$defs/GeneratedVectorImageBriefV5"},
            ]
        }
        schema["$defs"]["GeneratedLineGraphImageBriefV5"] = _line_brief()
        schema["$defs"]["GeneratedVectorImageBriefV5"] = _vector_brief()
    elif role == "image":
        schema["$defs"]["GeneratedImageOutput"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "drawing": {
                    "anyOf": [
                        {"$ref": "#/$defs/GeneratedLineGraphDrawingV5"},
                        {"$ref": "#/$defs/GeneratedVectorDrawingV5"},
                    ]
                },
                "summary": _text(maximum=2000),
            },
            "required": ["drawing", "summary"],
        }
        schema["$defs"].pop("GeneratedLineGraphDrawing", None)
        schema["$defs"]["GeneratedLineGraphDrawingV5"] = _line_drawing()
        schema["$defs"]["GeneratedVectorDrawingV5"] = _vector_drawing()
    Draft202012Validator.check_schema(schema)
    return schema


def main() -> None:
    for role in ("authoring", "image", "review", "registration"):
        payload = (
            json.dumps(_generate(role), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        for root in (CANONICAL, PACKAGED):
            target = root / f"{role}-result-v5.schema.json"
            target.write_bytes(payload)


if __name__ == "__main__":
    main()
