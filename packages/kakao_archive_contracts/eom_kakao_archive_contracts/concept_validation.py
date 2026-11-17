"""Closed, wheel-owned concept assistance schemas. No network or execution authority."""

import json
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from .render import sha256
from .study_validation import load_study_schema
from .validation import load_schema

CONCEPT_SCHEMA_SHA256 = "sha256:d0975dcedc5a8b51935fe2695f385e79c85377d952aa89b3d9291a45502abfda"


def load_concept_schema() -> dict[str, Any]:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/concept-assistance-v1.schema.json")
        .read_bytes()
    )
    if sha256(raw) != CONCEPT_SCHEMA_SHA256:
        raise ValueError("KAKAO_CONCEPT_SCHEMA_HASH_MISMATCH")
    schema: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_concept_contract(kind: Literal["request", "result", "context"], value: object) -> None:
    schema = load_concept_schema()
    registry: Registry[Any] = Registry()
    for predecessor in (load_schema(), load_study_schema()):
        registry = registry.with_resource(predecessor["$id"], Resource.from_contents(predecessor))
    schema.pop("oneOf")
    schema["$ref"] = "#/$defs/" + kind
    try:
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(
            value
        )
    except ValidationError as error:
        raise ValueError("KAKAO_CONCEPT_SCHEMA_INVALID") from error
