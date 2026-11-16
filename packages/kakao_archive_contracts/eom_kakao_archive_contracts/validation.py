"""Wheel-owned schemas; no network resolution or source checkout fallback."""

import json
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .render import sha256

SCHEMA_SHA256 = "sha256:ab665eefbe60d94bcc986310bf8f711013194a7b4556a01b0d5ca2f2e21ae056"


LAYOUT_SCHEMA_SHA256 = "sha256:b925381a7f6784c673029d7a3a38ecef3b3648076c7efa6360ac61f0e3e38f5a"


def load_schema(*, layout: bool = False) -> dict[str, Any]:
    filename = (
        "worker-question-layout-v1.schema.json"
        if layout
        else "worker-question-render-v1.schema.json"
    )
    raw = files("eom_kakao_archive_contracts").joinpath("schemas/" + filename).read_bytes()
    if sha256(raw) != (LAYOUT_SCHEMA_SHA256 if layout else SCHEMA_SHA256):
        raise ValueError("KAKAO_RENDER_SCHEMA_HASH_MISMATCH")
    schema: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_contract(
    kind: Literal["command", "manifest", "result", "layout"], value: object
) -> None:
    schema = load_schema(layout=kind == "layout")
    if kind != "layout":
        schema.pop("oneOf")
        schema["$ref"] = "#/$defs/" + kind
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        raise ValueError("KAKAO_RENDER_SCHEMA_INVALID") from exc
