"""Explicit study-family validation against wheel-owned, hash-pinned schemas."""

import json
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from .render import sha256
from .validation import load_schema

STUDY_SCHEMA_SHA256 = "sha256:9a8b2bdbe5c850528ece17100143e3968b670b610396138c59b54013e5ebdca7"
STUDY_LAYOUT_SCHEMA_SHA256 = (
    "sha256:b2cb10bed3940628cd651e2c37d43eb461d2a0b3effa24217d6ec74acce615fd"
)


def load_study_schema(*, layout: bool = False) -> dict[str, Any]:
    filename = (
        "worker-study-layout-v1.schema.json" if layout else "worker-study-render-v1.schema.json"
    )
    raw = files("eom_kakao_archive_contracts").joinpath("schemas/" + filename).read_bytes()
    if sha256(raw) != (STUDY_LAYOUT_SCHEMA_SHA256 if layout else STUDY_SCHEMA_SHA256):
        raise ValueError("KAKAO_STUDY_RENDER_SCHEMA_HASH_MISMATCH")
    value: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(value)
    return value


def validate_study_contract(
    kind: Literal["command", "manifest", "result", "layout"], value: object
) -> None:
    schema = load_study_schema(layout=kind == "layout")
    predecessor = load_schema()
    registry: Registry[Any] = Registry().with_resource(
        predecessor["$id"], Resource.from_contents(predecessor)
    )
    if kind == "layout":
        page_schema = load_schema(layout=True)
        registry = registry.with_resource(page_schema["$id"], Resource.from_contents(page_schema))
    else:
        schema.pop("oneOf")
        schema["$ref"] = "#/$defs/" + kind
    try:
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(
            value
        )
    except ValidationError as error:
        raise ValueError("KAKAO_STUDY_RENDER_SCHEMA_INVALID") from error
