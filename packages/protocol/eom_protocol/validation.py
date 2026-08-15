"""JSON Schema 2020-12 validation for external protocol messages."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

SchemaName = Literal[
    "job-request",
    "worker-input",
    "worker-result",
    "artifact-manifest",
    "error-result",
]


class SchemaValidationError(ValueError):
    """Raised when an external message does not satisfy its protocol schema."""


def load_schema(name: SchemaName) -> dict[str, Any]:
    resource = files("eom_protocol").joinpath("schemas", f"{name}.schema.json")
    data: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SchemaValidationError(f"schema {name} is not a JSON object")
    Draft202012Validator.check_schema(data)
    return data


def validate_message(name: SchemaName, message: object) -> None:
    validator = Draft202012Validator(load_schema(name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(message), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SchemaValidationError(f"{name} at {path}: {error.message}")
