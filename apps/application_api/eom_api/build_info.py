"""Release metadata embedded in the non-editable Application API wheel."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from eom_api_contracts.system import ApiReleaseBuildInfo
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError as PydanticValidationError

BuildInfo = ApiReleaseBuildInfo
_MAX_BUILD_INFO_BYTES = 4096
_MAX_BUILD_INFO_SCHEMA_BYTES = 64 * 1024
_BUILD_INFO_SCHEMA = "api-release-build-info-v1.schema.json"


class BuildInfoError(RuntimeError):
    """The installed wheel does not carry valid immutable release identity."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate object key")
        value[key] = item
    return value


def get_build_info() -> BuildInfo:
    resource = files("eom_api").joinpath("build-info.json")
    schema_resource = files("eom_api_contracts").joinpath("schemas", _BUILD_INFO_SCHEMA)
    try:
        payload = resource.read_bytes()
        if not 1 <= len(payload) <= _MAX_BUILD_INFO_BYTES:
            raise ValueError("resource size is outside the release contract")
        text = payload.decode("ascii")
        raw = json.loads(text, object_pairs_hook=_unique_object)
        if not isinstance(raw, dict):
            raise ValueError("resource root must be an object")
        canonical = (
            json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("ascii")
        if payload != canonical:
            raise ValueError("resource is not canonical JSON")
        schema_payload = schema_resource.read_bytes()
        if not 1 <= len(schema_payload) <= _MAX_BUILD_INFO_SCHEMA_BYTES:
            raise ValueError("release schema size is outside its bound")
        schema = json.loads(schema_payload.decode("ascii"), object_pairs_hook=_unique_object)
        if not isinstance(schema, dict):
            raise ValueError("release schema root must be an object")
        Draft202012Validator.check_schema(schema)
        if tuple(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(raw)):
            raise ValueError("resource violates its JSON Schema")
        return ApiReleaseBuildInfo.model_validate(raw)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        PydanticValidationError,
        SchemaError,
        ValueError,
    ) as exc:
        raise BuildInfoError("embedded API release identity is unavailable or invalid") from exc
