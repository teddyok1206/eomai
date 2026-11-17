"""Explicit study-family validation against wheel-owned, hash-pinned schemas."""

import json
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from .render import sha256
from .validation import load_schema

STUDY_SCHEMA_SHA256 = "sha256:9a8b2bdbe5c850528ece17100143e3968b670b610396138c59b54013e5ebdca7"


def load_study_schema() -> dict[str, Any]:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/worker-study-render-v1.schema.json")
        .read_bytes()
    )
    if sha256(raw) != STUDY_SCHEMA_SHA256:
        raise ValueError("KAKAO_STUDY_RENDER_SCHEMA_HASH_MISMATCH")
    value: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(value)
    return value


def validate_study_contract(kind: Literal["command", "manifest", "result"], value: object) -> None:
    schema = load_study_schema()
    predecessor = load_schema()
    registry: Registry[Any] = Registry().with_resource(
        predecessor["$id"], Resource.from_contents(predecessor)
    )
    schema.pop("oneOf")
    schema["$ref"] = "#/$defs/" + kind
    try:
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(
            value
        )
    except ValidationError as error:
        raise ValueError("KAKAO_STUDY_RENDER_SCHEMA_INVALID") from error
