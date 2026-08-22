"""JSON Schema 2020-12 registry for definitions and role messages."""

from __future__ import annotations

import copy
import json
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from typing import Any, Literal, cast

from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from eom_workflow.models import (
    AuthoringRoleResult,
    GeneratedAuthoringRoleResult,
    GeneratedAuthoringRoleResultV4,
    GeneratedImageRoleResult,
    GeneratedImageRoleResultV4,
    GeneratedRegistrationRoleResult,
    GeneratedRegistrationRoleResultV4,
    GeneratedReviewRoleResult,
    GeneratedReviewRoleResultV4,
    ImageRoleResult,
    KnowledgeAuthoringRoleResult,
    KnowledgeImageRoleResult,
    KnowledgeRegistrationRoleResult,
    KnowledgeReviewRoleResult,
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
ROLE_ALLOWED_RESULT_SCHEMAS: dict[str, frozenset[str]] = {
    "authoring": frozenset(
        {
            "authoring-result@1.0",
            "authoring-result@2.0",
            "authoring-result@3.0",
            "authoring-result@4.0",
        }
    ),
    "image": frozenset(
        {"image-result@1.0", "image-result@2.0", "image-result@3.0", "image-result@4.0"}
    ),
    "review": frozenset(
        {
            "review-result@1.0",
            "review-result@2.0",
            "review-result@3.0",
            "review-result@4.0",
        }
    ),
    "item_management": frozenset(
        {
            "registration-result@1.0",
            "registration-result@2.0",
            "registration-result@3.0",
            "registration-result@4.0",
        }
    ),
}
RESULT_SCHEMA_FILES = {
    "authoring-result@1.0": "authoring-result.schema.json",
    "image-result@1.0": "image-result.schema.json",
    "review-result@1.0": "review-result.schema.json",
    "registration-result@1.0": "registration-result.schema.json",
    "authoring-result@2.0": "authoring-result-v2.schema.json",
    "image-result@2.0": "image-result-v2.schema.json",
    "review-result@2.0": "review-result-v2.schema.json",
    "registration-result@2.0": "registration-result-v2.schema.json",
    "authoring-result@3.0": "authoring-result-v3.schema.json",
    "image-result@3.0": "image-result-v3.schema.json",
    "review-result@3.0": "review-result-v3.schema.json",
    "registration-result@3.0": "registration-result-v3.schema.json",
    "authoring-result@4.0": "authoring-result-v4.schema.json",
    "image-result@4.0": "image-result-v4.schema.json",
    "review-result@4.0": "review-result-v4.schema.json",
    "registration-result@4.0": "registration-result-v4.schema.json",
}
INPUT_SCHEMA_FILES = {
    "authoring": "authoring-input.schema.json",
    "image": "image-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
INPUT_SCHEMA_FILES_V1_1 = INPUT_SCHEMA_FILES
RESULT_SCHEMA_PROTOCOLS = {
    **{schema_id: "workflow-role/1.0.1" for schema_id in ROLE_RESULT_SCHEMAS.values()},
    **{
        schema_id: "workflow-role/1.1.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@2.0")
    },
    **{
        schema_id: "workflow-role/1.2.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@3.0")
    },
    **{
        schema_id: "workflow-role/1.3.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@4.0")
    },
}
PROTOCOL_INPUT_SCHEMAS = {
    "workflow-role/1.0.1": INPUT_SCHEMA_FILES,
    "workflow-role/1.1.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.2.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.3.0": INPUT_SCHEMA_FILES_V1_1,
}
WorkflowProtocolVersion = Literal[
    "workflow-role/1.0.1",
    "workflow-role/1.1.0",
    "workflow-role/1.2.0",
    "workflow-role/1.3.0",
]
ROLE_SCHEMA_FILES = tuple(
    sorted(
        {
            *RESULT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES_V1_1.values(),
        }
    )
)


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


def load_knowledge_item_brief_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_role_input_schema(
    role: str, protocol_version: str = "workflow-role/1.0.1"
) -> dict[str, Any]:
    try:
        file_name = PROTOCOL_INPUT_SCHEMAS[protocol_version][role]
    except KeyError as exc:
        raise WorkflowSchemaError(
            f"unknown worker role or protocol: {role}@{protocol_version}"
        ) from exc
    logical_name = f"roles/{file_name}"
    schema = load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)
    if protocol_version in {
        "workflow-role/1.1.0",
        "workflow-role/1.2.0",
        "workflow-role/1.3.0",
    }:
        schema = copy.deepcopy(schema)
        _mapping(_mapping(schema, "properties"), "protocol_version")["const"] = protocol_version
        request = _mapping(_mapping(schema, "$defs"), "request")
        request_name = _mapping(_mapping(request, "properties"), "request_name")
        request_name.pop("const", None)
        request_name["const"] = (
            "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            if protocol_version in {"workflow-role/1.2.0", "workflow-role/1.3.0"}
            else "KNOWLEDGE_ITEM_REQUEST"
        )
    return schema


def load_role_result_schema(schema_id: str) -> dict[str, Any]:
    try:
        file_name = RESULT_SCHEMA_FILES[schema_id]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc
    logical_name = f"roles/{file_name}"
    schema = load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)
    return _inline_catalog_schema(schema)


def validate_schema_message(schema: dict[str, Any], value: object, name: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise WorkflowSchemaError(f"{name} at {path}: {error.message}")


def validate_role_input(
    value: object, role: str, protocol_version: str = "workflow-role/1.0.1"
) -> RoleWorkerInput:
    validate_schema_message(load_role_input_schema(role, protocol_version), value, f"{role}-input")
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
        if schema_id == "authoring-result@4.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV4.model_validate(value)
        if schema_id == "image-result@4.0" and role == "image":
            return GeneratedImageRoleResultV4.model_validate(value)
        if schema_id == "review-result@4.0" and role == "review":
            return GeneratedReviewRoleResultV4.model_validate(value)
        if schema_id == "registration-result@4.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV4.model_validate(value)
        if schema_id == "authoring-result@3.0" and role == "authoring":
            return GeneratedAuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@3.0" and role == "image":
            return GeneratedImageRoleResult.model_validate(value)
        if schema_id == "review-result@3.0" and role == "review":
            return GeneratedReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@3.0" and role == "item_management":
            return GeneratedRegistrationRoleResult.model_validate(value)
        if schema_id == "authoring-result@2.0" and role == "authoring":
            return KnowledgeAuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@2.0" and role == "image":
            return KnowledgeImageRoleResult.model_validate(value)
        if schema_id == "review-result@2.0" and role == "review":
            return KnowledgeReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@2.0" and role == "item_management":
            return KnowledgeRegistrationRoleResult.model_validate(value)
        if schema_id == "authoring-result@1.0" and role == "authoring":
            return AuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@1.0" and role == "image":
            return ImageRoleResult.model_validate(value)
        if schema_id == "review-result@1.0" and role == "review":
            return ReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@1.0" and role == "item_management":
            return RegistrationRoleResult.model_validate(value)
        raise WorkflowSchemaError(f"result schema does not match worker role: {schema_id}")
    except ValidationError as exc:
        raise WorkflowSchemaError(f"{schema_id} failed typed validation") from exc


def constrained_result_schema(schema_id: str, worker_input: RoleWorkerInput) -> dict[str, Any]:
    schema = load_codex_result_schema(schema_id)
    properties = _mapping(schema, "properties")
    for key, value in (
        ("job_id", worker_input.job_id),
        ("workflow_id", worker_input.workflow_id),
        ("step_run_id", worker_input.step_run_id),
    ):
        _mapping(properties, key)["const"] = value
    definitions = _mapping(schema, "$defs")
    artifact = definitions.get("artifact", definitions.get("ArtifactSpec"))
    if not isinstance(artifact, dict):
        raise WorkflowSchemaError("schema is missing artifact definition")
    artifact_properties = _mapping(artifact, "properties")
    _mapping(artifact_properties, "logical_artifact_id")["const"] = (
        worker_input.artifact.logical_artifact_id
    )
    _mapping(artifact_properties, "revision_id")["const"] = worker_input.artifact.revision_id
    validate_codex_structured_output_schema(schema)
    return schema


def load_codex_result_schema(schema_id: str) -> dict[str, Any]:
    """Project the canonical result contract into Codex's strict JSON Schema subset."""

    schema = copy.deepcopy(load_role_result_schema(schema_id))
    schema.pop("$schema", None)
    schema.pop("$id", None)
    if schema_id == "authoring-result@2.0":
        _project_knowledge_authoring_content(schema)
    _normalize_codex_schema(schema)
    validate_codex_structured_output_schema(schema)
    return schema


def validate_codex_structured_output_schema(schema: dict[str, Any]) -> None:
    """Fail before worker submission when a result projection is not strict-output compatible."""

    unsupported = {
        "allOf",
        "oneOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "prefixItems",
        "minLength",
        "maxLength",
        "uniqueItems",
    }

    def visit(value: object, path: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        found = unsupported.intersection(value)
        if found:
            raise WorkflowSchemaError(
                f"Codex result schema uses unsupported keyword at {'.'.join(path) or '$'}: "
                f"{sorted(found)[0]}"
            )
        if "properties" in value:
            properties = _mapping(value, "properties")
            if value.get("type") != "object" or value.get("additionalProperties") is not False:
                raise WorkflowSchemaError(
                    f"Codex result object is not closed at {'.'.join(path) or '$'}"
                )
            required = value.get("required")
            if not isinstance(required, list) or set(required) != set(properties):
                raise WorkflowSchemaError(
                    f"Codex result object fields are not all required at {'.'.join(path) or '$'}"
                )
            for name, child in properties.items():
                if not isinstance(child, dict) or not any(
                    key in child for key in ("type", "$ref", "anyOf")
                ):
                    raise WorkflowSchemaError(
                        f"Codex result property has no explicit type at "
                        f"{'.'.join((*path, 'properties', name))}"
                    )
                visit(child, (*path, "properties", name))
        if isinstance(value.get("items"), dict):
            visit(value["items"], (*path, "items"))
        if isinstance(value.get("anyOf"), list):
            for index, child in enumerate(value["anyOf"]):
                visit(child, (*path, "anyOf", str(index)))
        definitions = value.get("$defs")
        if isinstance(definitions, dict):
            for name, child in definitions.items():
                visit(child, (*path, "$defs", name))

    if schema.get("type") != "object":
        raise WorkflowSchemaError("Codex result schema root must be an object")
    visit(schema, ())


def result_schema_protocol(schema_id: str) -> WorkflowProtocolVersion:
    try:
        return cast(WorkflowProtocolVersion, RESULT_SCHEMA_PROTOCOLS[schema_id])
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc


def role_schema_bundle_hash(protocol_version: str = "workflow-role/1.0.1") -> str:
    if protocol_version == "workflow-role/1.0.1":
        legacy_files = tuple(sorted({*ROLE_RESULT_SCHEMAS.values(), *INPUT_SCHEMA_FILES.values()}))
        legacy_names = tuple(
            sorted(
                {
                    *(RESULT_SCHEMA_FILES[schema_id] for schema_id in ROLE_RESULT_SCHEMAS.values()),
                    *INPUT_SCHEMA_FILES.values(),
                }
            )
        )
        if len(legacy_files) != 8:
            raise WorkflowSchemaError("legacy workflow schema inventory changed")
        return content_sha256(
            {
                file_name: load_json_schema(
                    ROLE_RESOURCE_ROOT.joinpath(file_name), f"roles/{file_name}"
                )
                for file_name in legacy_names
            }
        )
    try:
        input_files = PROTOCOL_INPUT_SCHEMAS[protocol_version]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown workflow protocol: {protocol_version}") from exc
    result_ids = sorted(
        schema_id
        for schema_id, version in RESULT_SCHEMA_PROTOCOLS.items()
        if version == protocol_version
    )
    schemas = {
        **{
            f"input/{role}": load_role_input_schema(role, protocol_version)
            for role in sorted(input_files)
        },
        **{f"result/{schema_id}": load_role_result_schema(schema_id) for schema_id in result_ids},
    }
    return content_sha256(schemas)


def _inline_catalog_schema(schema: dict[str, Any]) -> dict[str, Any]:
    reference = "eom://schemas/item-registry/assessment-item-content-v1"
    if reference not in json.dumps(schema, ensure_ascii=True):
        return schema
    from eom_catalog_contracts import load_schema

    canonical = load_schema("assessment-item-content")

    def visit(value: object) -> object:
        if isinstance(value, dict):
            if value == {"$ref": reference}:
                return copy.deepcopy(canonical)
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    bundled = visit(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled role result schema is not an object")
    Draft202012Validator.check_schema(bundled)
    return bundled


def _project_knowledge_authoring_content(schema: dict[str, Any]) -> None:
    properties = _mapping(schema, "properties")
    output = _mapping(properties, "output")
    content = _mapping(_mapping(output, "properties"), "content")
    branches = content.get("allOf")
    if not isinstance(branches, list) or len(branches) != 2 or not isinstance(branches[0], dict):
        raise WorkflowSchemaError("knowledge authoring content contract is not projectable")
    item = copy.deepcopy(branches[0])
    item.pop("$schema", None)
    item.pop("$id", None)
    item.pop("title", None)
    item_definitions = item.pop("$defs", None)
    if not isinstance(item_definitions, dict):
        raise WorkflowSchemaError("knowledge authoring item definitions are missing")

    renamed_definitions = {
        f"item_{name}": _rewrite_item_references(value) for name, value in item_definitions.items()
    }
    root_definitions = _mapping(schema, "$defs")
    if set(root_definitions).intersection(renamed_definitions):
        raise WorkflowSchemaError("knowledge authoring item definitions conflict")
    root_definitions.update(renamed_definitions)
    projected = _rewrite_item_references(item)
    if not isinstance(projected, dict):
        raise WorkflowSchemaError("knowledge authoring item projection is invalid")
    content.clear()
    content.update(projected)

    content_properties = _mapping(content, "properties")
    content_properties["locale"] = {"type": "string", "const": "ko-KR"}
    body = _mapping(content_properties, "body")
    body["minItems"] = 6
    body["maxItems"] = 6
    content_properties["interaction"] = {"$ref": "#/$defs/item_singleChoice"}

    table = _mapping(root_definitions, "item_tableBlock")
    table_properties = _mapping(table, "properties")
    table_properties["purpose"] = {"type": "string", "const": "data"}
    table["required"] = list(table_properties)
    headers = _mapping(table_properties, "headers")
    headers["minItems"] = 3
    headers["maxItems"] = 3
    rows = _mapping(table_properties, "rows")
    rows["minItems"] = 1
    rows["maxItems"] = 1
    row = _mapping(rows, "items")
    row["minItems"] = 3
    row["maxItems"] = 3

    image = _mapping(root_definitions, "item_imageBlock")
    image_properties = _mapping(image, "properties")
    image_properties["purpose"] = {"type": "string", "const": "stimulus"}
    image_properties["width_px"] = {"type": "integer", "const": 800}
    image_properties["height_px"] = {"type": "integer", "const": 500}
    artifact_pointer = _mapping(root_definitions, "item_artifactPointer")
    _mapping(artifact_pointer, "properties")["media_type"] = {
        "type": "string",
        "const": "image/png",
    }

    equation = _mapping(root_definitions, "item_equationBlock")
    equation_properties = _mapping(equation, "properties")
    equation_properties["purpose"] = {"type": "string", "const": "stimulus"}
    equation_properties["notation"] = {
        "type": "string",
        "const": "hancom-equation-script",
    }
    equation_properties["source"] = {
        "type": "string",
        "pattern": "^[A-Za-z0-9+\\-*/=() ._^]+$",
    }

    paragraph = _mapping(root_definitions, "item_paragraphBlock")
    _mapping(paragraph, "properties")["purpose"] = {
        "type": "string",
        "enum": ["stem", "prompt"],
    }
    statements = _mapping(root_definitions, "item_statementSetBlock")
    statement_items = _mapping(_mapping(statements, "properties"), "statements")
    statement_items["minItems"] = 3
    statement_items["maxItems"] = 3
    statement = _mapping(root_definitions, "item_statement")
    _mapping(statement, "properties")["label"] = {
        "type": "string",
        "enum": ["ㄱ", "ㄴ", "ㄷ"],
    }

    single_choice = _mapping(root_definitions, "item_singleChoice")
    choices = _mapping(_mapping(single_choice, "properties"), "choices")
    choices["minItems"] = 5
    choices["maxItems"] = 5
    score = _mapping(root_definitions, "item_score")
    _mapping(score, "properties")["points"] = {"type": "integer", "enum": [2, 3]}


def _rewrite_item_references(value: object) -> object:
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
                rewritten[key] = item.replace("#/$defs/", "#/$defs/item_", 1)
            else:
                rewritten[key] = _rewrite_item_references(item)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_item_references(item) for item in value]
    return value


def _normalize_codex_schema(value: object) -> None:
    if not isinstance(value, dict):
        return
    value.pop("minLength", None)
    value.pop("maxLength", None)
    value.pop("uniqueItems", None)
    if "oneOf" in value:
        value["anyOf"] = value.pop("oneOf")
    if "allOf" in value or "prefixItems" in value:
        raise WorkflowSchemaError("Codex result projection retained unsupported composition")

    if "type" not in value:
        if "const" in value:
            constant = value["const"]
            if isinstance(constant, bool):
                value["type"] = "boolean"
            elif isinstance(constant, int):
                value["type"] = "integer"
            elif isinstance(constant, float):
                value["type"] = "number"
            elif isinstance(constant, str):
                value["type"] = "string"
        elif isinstance(value.get("enum"), list) and value["enum"]:
            first = value["enum"][0]
            if all(isinstance(item, str) for item in value["enum"]):
                value["type"] = "string"
            elif all(
                isinstance(item, int) and not isinstance(item, bool) for item in value["enum"]
            ):
                value["type"] = "integer"
            elif isinstance(first, bool) and all(isinstance(item, bool) for item in value["enum"]):
                value["type"] = "boolean"

    properties = value.get("properties")
    if isinstance(properties, dict):
        value["type"] = "object"
        value["additionalProperties"] = False
        value["required"] = list(properties)
        for child in properties.values():
            _normalize_codex_schema(child)
    items = value.get("items")
    if isinstance(items, dict):
        _normalize_codex_schema(items)
    alternatives = value.get("anyOf")
    if isinstance(alternatives, list):
        for child in alternatives:
            _normalize_codex_schema(child)
    definitions = value.get("$defs")
    if isinstance(definitions, dict):
        for child in definitions.values():
            _normalize_codex_schema(child)


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
