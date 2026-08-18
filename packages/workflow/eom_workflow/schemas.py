"""JSON Schema 2020-12 registry for definitions and role messages."""

from __future__ import annotations

import copy
import json
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from typing import Any, cast

from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from eom_workflow.models import (
    AuthoringRoleResult,
    ImageRoleResult,
    RegistrationRoleResult,
    ReviewRoleResult,
    RoleResult,
    RoleWorkerInput,
)

WORKFLOW_RESOURCE_ROOT = resources.files("eom_workflow").joinpath("resources")
ROLE_RESOURCE_ROOT = WORKFLOW_RESOURCE_ROOT.joinpath("roles")
ROLE_RESULT_SCHEMAS: dict[str, str] = {
    "authoring": "authoring-result@1.0",
    "image": "image-result@1.0",
    "review": "review-result@1.0",
    "item_management": "registration-result@1.0",
}
RESULT_SCHEMA_FILES = {
    "authoring-result@1.0": "authoring-result.schema.json",
    "image-result@1.0": "image-result.schema.json",
    "review-result@1.0": "review-result.schema.json",
    "registration-result@1.0": "registration-result.schema.json",
}
INPUT_SCHEMA_FILES = {
    "authoring": "authoring-input.schema.json",
    "image": "image-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
ROLE_SCHEMA_FILES = tuple(sorted({*RESULT_SCHEMA_FILES.values(), *INPUT_SCHEMA_FILES.values()}))


class WorkflowSchemaError(ValueError):
    pass


def load_json_schema(resource: Traversable, logical_name: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowSchemaError(_resource_error(logical_name)) from exc
    if not isinstance(raw, dict):
        raise WorkflowSchemaError(f"workflow schema is not an object: {logical_name}")
    try:
        Draft202012Validator.check_schema(raw)
    except SchemaError as exc:
        raise WorkflowSchemaError(f"workflow schema is invalid: {logical_name}") from exc
    return raw


def load_definition_schema() -> dict[str, Any]:
    logical_name = "workflow-definition.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_role_input_schema(role: str) -> dict[str, Any]:
    try:
        file_name = INPUT_SCHEMA_FILES[role]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown worker role: {role}") from exc
    logical_name = f"roles/{file_name}"
    return load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)


def load_role_result_schema(schema_id: str) -> dict[str, Any]:
    try:
        file_name = RESULT_SCHEMA_FILES[schema_id]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc
    logical_name = f"roles/{file_name}"
    return load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)


def validate_schema_message(schema: dict[str, Any], value: object, name: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise WorkflowSchemaError(f"{name} at {path}: {error.message}")


def validate_role_input(value: object, role: str) -> RoleWorkerInput:
    validate_schema_message(load_role_input_schema(role), value, f"{role}-input")
    try:
        parsed = RoleWorkerInput.model_validate(value)
    except ValidationError as exc:
        raise WorkflowSchemaError(f"{role}-input failed typed validation") from exc
    if parsed.role != role:
        raise WorkflowSchemaError("role input does not match requested role")
    return parsed


def validate_role_result(value: object, role: str, schema_id: str) -> RoleResult:
    validate_schema_message(load_role_result_schema(schema_id), value, schema_id)
    try:
        if role == "authoring":
            return AuthoringRoleResult.model_validate(value)
        if role == "image":
            return ImageRoleResult.model_validate(value)
        if role == "review":
            return ReviewRoleResult.model_validate(value)
        if role == "item_management":
            return RegistrationRoleResult.model_validate(value)
        raise WorkflowSchemaError(f"unknown worker role: {role}")
    except ValidationError as exc:
        raise WorkflowSchemaError(f"{schema_id} failed typed validation") from exc


def constrained_result_schema(schema_id: str, worker_input: RoleWorkerInput) -> dict[str, Any]:
    schema = copy.deepcopy(load_role_result_schema(schema_id))
    properties = _mapping(schema, "properties")
    for key, value in (
        ("job_id", worker_input.job_id),
        ("workflow_id", worker_input.workflow_id),
        ("step_run_id", worker_input.step_run_id),
    ):
        _mapping(properties, key)["const"] = value
    artifact = _mapping(_mapping(schema, "$defs"), "artifact")
    artifact_properties = _mapping(artifact, "properties")
    _mapping(artifact_properties, "logical_artifact_id")["const"] = (
        worker_input.artifact.logical_artifact_id
    )
    _mapping(artifact_properties, "revision_id")["const"] = worker_input.artifact.revision_id
    return schema


def role_schema_bundle_hash() -> str:
    schemas = {
        file_name: load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), f"roles/{file_name}")
        for file_name in ROLE_SCHEMA_FILES
    }
    return content_sha256(schemas)


def _resource_error(logical_name: str) -> str:
    try:
        version = metadata.version("eom-platform")
    except metadata.PackageNotFoundError:
        version = "source"
    return (
        f"workflow schema resource unavailable: {logical_name} "
        f"(package=eom_workflow, distribution=eom-platform@{version})"
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise WorkflowSchemaError(f"schema is missing object: {key}")
    return cast(dict[str, Any], value)
