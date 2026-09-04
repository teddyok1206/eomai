"""JSON Schema 2020-12 registry for definitions and role messages."""

from __future__ import annotations

import copy
import json
import re
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from typing import Any, Literal, cast

from eom_catalog_contracts import (
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
)
from eom_hwpx_contracts import (
    derive_content_team_equation_sources,
    normalize_content_team_stem,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from eom_workflow.models import (
    AuthoringRoleResult,
    ContentTeamAuthoringRoleResultV7,
    ContentTeamRegistrationRoleResultV7,
    ContentTeamReviewRoleResultV7,
    GeneratedAuthoringRoleResult,
    GeneratedAuthoringRoleResultV4,
    GeneratedAuthoringRoleResultV5,
    GeneratedAuthoringRoleResultV6,
    GeneratedImageRoleResult,
    GeneratedImageRoleResultV4,
    GeneratedImageRoleResultV5,
    GeneratedImageRoleResultV6,
    GeneratedRegistrationRoleResult,
    GeneratedRegistrationRoleResultV4,
    GeneratedRegistrationRoleResultV5,
    GeneratedRegistrationRoleResultV6,
    GeneratedReviewRoleResult,
    GeneratedReviewRoleResultV4,
    GeneratedReviewRoleResultV5,
    GeneratedReviewRoleResultV6,
    ImageRoleResult,
    KnowledgeAnalysisProposalRoleResult,
    KnowledgeAnalysisProposalRoleResultV2,
    KnowledgeAnalysisProposalRoleResultV3,
    KnowledgeAnalysisProposalRoleResultV4,
    KnowledgeAnalysisProposalRoleResultV5,
    KnowledgeAnalysisProposalRoleResultV6,
    KnowledgeAnalysisProposalRoleResultV7,
    KnowledgeAnalysisProposalRoleResultV8,
    KnowledgeAnalysisWorkerRequest,
    KnowledgeAuthoringRoleResult,
    KnowledgeImageRoleResult,
    KnowledgeRegistrationRoleResult,
    KnowledgeReviewRoleResult,
    LegacyItemEditorialCompatibilityRoleResult,
    LegacyItemEditorialCompatibilityWorkerRequest,
    LegacyItemExtractionRoleResult,
    LegacyItemExtractionWorkerRequest,
    RegistrationRoleResult,
    ReviewRoleResult,
    RoleResult,
    RoleWorkerInput,
)

WORKFLOW_RESOURCE_ROOT = resources.files("eom_workflow").joinpath("resources")
ROLE_RESOURCE_ROOT = WORKFLOW_RESOURCE_ROOT.joinpath("roles")
_CANONICAL_SAFE_ARTIFACT_MEMBER_PATTERN = (
    r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*\\)[^/]+(?:/[^/]+)*$"
)
_CODEX_SAFE_ARTIFACT_MEMBER_PATTERN = (
    r"^([^./\\][^/\\]*|\.[^./\\][^/\\]*|\.\.[^/\\][^/\\]*)"
    r"(/([^./\\][^/\\]*|\.[^./\\][^/\\]*|\.\.[^/\\][^/\\]*))*$"
)
_CANONICAL_SAFE_TEXT_PATTERN = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]*$"
_CODEX_NONEMPTY_SAFE_TEXT_PATTERN = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"
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
            "authoring-result@5.0",
            "authoring-result@6.0",
            "authoring-result@7.0",
        }
    ),
    "image": frozenset(
        {
            "image-result@1.0",
            "image-result@2.0",
            "image-result@3.0",
            "image-result@4.0",
            "image-result@5.0",
            "image-result@6.0",
        }
    ),
    "review": frozenset(
        {
            "review-result@1.0",
            "review-result@2.0",
            "review-result@3.0",
            "review-result@4.0",
            "review-result@5.0",
            "review-result@6.0",
            "review-result@7.0",
        }
    ),
    "item_management": frozenset(
        {
            "registration-result@1.0",
            "registration-result@2.0",
            "registration-result@3.0",
            "registration-result@4.0",
            "registration-result@5.0",
            "registration-result@6.0",
            "registration-result@7.0",
        }
    ),
    "support": frozenset(
        {
            "knowledge-analysis-proposal-result@1.0",
            "knowledge-analysis-proposal-result@2.0",
            "knowledge-analysis-proposal-result@3.0",
            "knowledge-analysis-proposal-result@4.0",
            "knowledge-analysis-proposal-result@5.0",
            "knowledge-analysis-proposal-result@6.0",
            "knowledge-analysis-proposal-result@7.0",
            "knowledge-analysis-proposal-result@8.0",
            "legacy-item-extraction-result@1.0",
            "legacy-item-editorial-compatibility-result@1.0",
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
    "authoring-result@5.0": "authoring-result-v5.schema.json",
    "image-result@5.0": "image-result-v5.schema.json",
    "review-result@5.0": "review-result-v5.schema.json",
    "registration-result@5.0": "registration-result-v5.schema.json",
    "authoring-result@6.0": "authoring-result-v6.schema.json",
    "image-result@6.0": "image-result-v6.schema.json",
    "review-result@6.0": "review-result-v6.schema.json",
    "registration-result@6.0": "registration-result-v6.schema.json",
    "authoring-result@7.0": "authoring-result-v7.schema.json",
    "review-result@7.0": "review-result-v7.schema.json",
    "registration-result@7.0": "registration-result-v7.schema.json",
    "knowledge-analysis-proposal-result@1.0": ("knowledge-analysis-proposal-result-v1.schema.json"),
    "knowledge-analysis-proposal-result@2.0": ("knowledge-analysis-proposal-result-v2.schema.json"),
    "knowledge-analysis-proposal-result@3.0": ("knowledge-analysis-proposal-result-v3.schema.json"),
    "knowledge-analysis-proposal-result@4.0": ("knowledge-analysis-proposal-result-v4.schema.json"),
    "knowledge-analysis-proposal-result@5.0": ("knowledge-analysis-proposal-result-v5.schema.json"),
    "knowledge-analysis-proposal-result@6.0": ("knowledge-analysis-proposal-result-v6.schema.json"),
    "knowledge-analysis-proposal-result@7.0": ("knowledge-analysis-proposal-result-v7.schema.json"),
    "knowledge-analysis-proposal-result@8.0": ("knowledge-analysis-proposal-result-v8.schema.json"),
    "legacy-item-extraction-result@1.0": "legacy-item-extraction-result-v1.schema.json",
    "legacy-item-editorial-compatibility-result@1.0": (
        "legacy-item-editorial-compatibility-result-v1.schema.json"
    ),
}
INPUT_SCHEMA_FILES = {
    "authoring": "authoring-input.schema.json",
    "image": "image-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
INPUT_SCHEMA_FILES_V1_1 = INPUT_SCHEMA_FILES
INPUT_SCHEMA_FILES_V1_4 = {"support": "knowledge-analysis-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_5 = {"support": "knowledge-analysis-input-v2.schema.json"}
INPUT_SCHEMA_FILES_V1_6 = {"support": "knowledge-analysis-input-v3.schema.json"}
INPUT_SCHEMA_FILES_V1_7 = {"support": "knowledge-analysis-input-v4.schema.json"}
INPUT_SCHEMA_FILES_V1_8 = {"support": "knowledge-analysis-input-v5.schema.json"}
INPUT_SCHEMA_FILES_V1_9 = {"support": "knowledge-analysis-input-v6.schema.json"}
INPUT_SCHEMA_FILES_V1_10 = {"support": "knowledge-analysis-input-v7.schema.json"}
INPUT_SCHEMA_FILES_V1_11 = {"support": "knowledge-analysis-input-v8.schema.json"}
INPUT_SCHEMA_FILES_V1_14 = {"support": "legacy-item-extraction-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_15 = {
    "authoring": "authoring-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
INPUT_SCHEMA_FILES_V1_16 = {"support": "legacy-item-editorial-compatibility-input-v1.schema.json"}
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
    "knowledge-analysis-proposal-result@1.0": "workflow-role/1.4.0",
    "knowledge-analysis-proposal-result@2.0": "workflow-role/1.5.0",
    "knowledge-analysis-proposal-result@3.0": "workflow-role/1.6.0",
    "knowledge-analysis-proposal-result@4.0": "workflow-role/1.7.0",
    "knowledge-analysis-proposal-result@5.0": "workflow-role/1.8.0",
    "knowledge-analysis-proposal-result@6.0": "workflow-role/1.9.0",
    "knowledge-analysis-proposal-result@7.0": "workflow-role/1.10.0",
    "knowledge-analysis-proposal-result@8.0": "workflow-role/1.11.0",
    "authoring-result@5.0": "workflow-role/1.12.0",
    "image-result@5.0": "workflow-role/1.12.0",
    "review-result@5.0": "workflow-role/1.12.0",
    "registration-result@5.0": "workflow-role/1.12.0",
    "authoring-result@6.0": "workflow-role/1.13.0",
    "image-result@6.0": "workflow-role/1.13.0",
    "review-result@6.0": "workflow-role/1.13.0",
    "registration-result@6.0": "workflow-role/1.13.0",
    "legacy-item-extraction-result@1.0": "workflow-role/1.14.0",
    "authoring-result@7.0": "workflow-role/1.15.0",
    "review-result@7.0": "workflow-role/1.15.0",
    "registration-result@7.0": "workflow-role/1.15.0",
    "legacy-item-editorial-compatibility-result@1.0": "workflow-role/1.16.0",
}
PROTOCOL_INPUT_SCHEMAS = {
    "workflow-role/1.0.1": INPUT_SCHEMA_FILES,
    "workflow-role/1.1.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.2.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.3.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.4.0": INPUT_SCHEMA_FILES_V1_4,
    "workflow-role/1.5.0": INPUT_SCHEMA_FILES_V1_5,
    "workflow-role/1.6.0": INPUT_SCHEMA_FILES_V1_6,
    "workflow-role/1.7.0": INPUT_SCHEMA_FILES_V1_7,
    "workflow-role/1.8.0": INPUT_SCHEMA_FILES_V1_8,
    "workflow-role/1.9.0": INPUT_SCHEMA_FILES_V1_9,
    "workflow-role/1.10.0": INPUT_SCHEMA_FILES_V1_10,
    "workflow-role/1.11.0": INPUT_SCHEMA_FILES_V1_11,
    "workflow-role/1.12.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.13.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.14.0": INPUT_SCHEMA_FILES_V1_14,
    "workflow-role/1.15.0": INPUT_SCHEMA_FILES_V1_15,
    "workflow-role/1.16.0": INPUT_SCHEMA_FILES_V1_16,
}
WorkflowProtocolVersion = Literal[
    "workflow-role/1.0.1",
    "workflow-role/1.1.0",
    "workflow-role/1.2.0",
    "workflow-role/1.3.0",
    "workflow-role/1.4.0",
    "workflow-role/1.5.0",
    "workflow-role/1.6.0",
    "workflow-role/1.7.0",
    "workflow-role/1.8.0",
    "workflow-role/1.9.0",
    "workflow-role/1.10.0",
    "workflow-role/1.11.0",
    "workflow-role/1.12.0",
    "workflow-role/1.13.0",
    "workflow-role/1.14.0",
    "workflow-role/1.15.0",
    "workflow-role/1.16.0",
]
ROLE_SCHEMA_FILES = tuple(
    sorted(
        {
            *RESULT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES_V1_1.values(),
            *INPUT_SCHEMA_FILES_V1_4.values(),
            *INPUT_SCHEMA_FILES_V1_5.values(),
            *INPUT_SCHEMA_FILES_V1_6.values(),
            *INPUT_SCHEMA_FILES_V1_7.values(),
            *INPUT_SCHEMA_FILES_V1_8.values(),
            *INPUT_SCHEMA_FILES_V1_9.values(),
            *INPUT_SCHEMA_FILES_V1_10.values(),
            *INPUT_SCHEMA_FILES_V1_11.values(),
            *INPUT_SCHEMA_FILES_V1_14.values(),
            *INPUT_SCHEMA_FILES_V1_15.values(),
            *INPUT_SCHEMA_FILES_V1_16.values(),
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


def load_knowledge_item_brief_v2_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v2.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_v3_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v3.schema.json"
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
        "workflow-role/1.12.0",
        "workflow-role/1.13.0",
        "workflow-role/1.15.0",
    }:
        schema = copy.deepcopy(schema)
        _mapping(_mapping(schema, "properties"), "protocol_version")["const"] = protocol_version
        request = _mapping(_mapping(schema, "$defs"), "request")
        request_name = _mapping(_mapping(request, "properties"), "request_name")
        request_name.pop("const", None)
        request_name["const"] = (
            "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            if protocol_version
            in {
                "workflow-role/1.2.0",
                "workflow-role/1.3.0",
                "workflow-role/1.12.0",
                "workflow-role/1.13.0",
                "workflow-role/1.15.0",
            }
            else "KNOWLEDGE_ITEM_REQUEST"
        )
    return _inline_catalog_schema(
        schema,
        require_reference_closure=protocol_version
        in {
            "workflow-role/1.9.0",
            "workflow-role/1.10.0",
            "workflow-role/1.11.0",
            "workflow-role/1.14.0",
            "workflow-role/1.16.0",
        },
    )


def load_role_result_schema(schema_id: str) -> dict[str, Any]:
    try:
        file_name = RESULT_SCHEMA_FILES[schema_id]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc
    logical_name = f"roles/{file_name}"
    schema = load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)
    return _inline_catalog_schema(
        schema,
        require_reference_closure=schema_id
        in {
            "knowledge-analysis-proposal-result@6.0",
            "knowledge-analysis-proposal-result@7.0",
            "knowledge-analysis-proposal-result@8.0",
            "legacy-item-extraction-result@1.0",
            "legacy-item-editorial-compatibility-result@1.0",
        },
    )


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
    canonical_value = value
    if schema_id == "authoring-result@7.0" and role == "authoring":
        canonical_value = _canonicalize_content_team_authoring_result(value)
    elif schema_id == "legacy-item-extraction-result@1.0" and role == "support":
        canonical_value = _canonicalize_legacy_item_extraction_result(value)
    elif schema_id == "legacy-item-editorial-compatibility-result@1.0" and role == "support":
        canonical_value = _canonicalize_legacy_editorial_compatibility_result(value)
    validate_schema_message(load_role_result_schema(schema_id), canonical_value, schema_id)
    try:
        if schema_id == "authoring-result@4.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV4.model_validate(value)
        if schema_id == "image-result@4.0" and role == "image":
            return GeneratedImageRoleResultV4.model_validate(value)
        if schema_id == "review-result@4.0" and role == "review":
            return GeneratedReviewRoleResultV4.model_validate(value)
        if schema_id == "registration-result@4.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV4.model_validate(value)
        if schema_id == "authoring-result@5.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV5.model_validate(value)
        if schema_id == "image-result@5.0" and role == "image":
            return GeneratedImageRoleResultV5.model_validate(value)
        if schema_id == "review-result@5.0" and role == "review":
            return GeneratedReviewRoleResultV5.model_validate(value)
        if schema_id == "registration-result@5.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV5.model_validate(value)
        if schema_id == "authoring-result@6.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV6.model_validate(value)
        if schema_id == "image-result@6.0" and role == "image":
            return GeneratedImageRoleResultV6.model_validate(value)
        if schema_id == "review-result@6.0" and role == "review":
            return GeneratedReviewRoleResultV6.model_validate(value)
        if schema_id == "registration-result@6.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV6.model_validate(value)
        if schema_id == "authoring-result@7.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV7.model_validate(canonical_value)
        if schema_id == "review-result@7.0" and role == "review":
            return ContentTeamReviewRoleResultV7.model_validate(value)
        if schema_id == "registration-result@7.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV7.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@1.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResult.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@2.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV2.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@3.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV3.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@4.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV4.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@5.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV5.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@6.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV6.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@7.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV7.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@8.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV8.model_validate(value)
        if schema_id == "legacy-item-extraction-result@1.0" and role == "support":
            return LegacyItemExtractionRoleResult.model_validate(canonical_value)
        if schema_id == "legacy-item-editorial-compatibility-result@1.0" and role == "support":
            return LegacyItemEditorialCompatibilityRoleResult.model_validate(canonical_value)
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
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        first = errors[0] if errors else None
        if first is None:
            detail = ""
        else:
            location = ".".join(str(part) for part in first["loc"]) or "$"
            detail = f" at {location}: {first['msg']}"
        raise WorkflowSchemaError(f"{schema_id} failed typed validation{detail}") from exc


def _canonicalize_content_team_authoring_result(value: object) -> object:
    """Rehydrate the renderer route derived from the model-authored visual structure."""

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    draft = output.get("draft")
    if not isinstance(draft, dict) or "visual_layout" in draft:
        return value

    validate_schema_message(
        load_codex_result_schema("authoring-result@7.0"),
        value,
        "authoring-result@7.0 projected",
    )
    inquiry = draft.get("inquiry")
    visuals = draft.get("visuals")
    if not isinstance(visuals, list):
        raise WorkflowSchemaError("content-team projected visuals are invalid")
    if inquiry is not None:
        if visuals:
            raise WorkflowSchemaError("content-team inquiry cannot include general visual slots")
        derived_layout: str | None = "INQUIRY_BOX"
    else:
        signature_items: list[tuple[str, str]] = []
        for visual in visuals:
            if not isinstance(visual, dict):
                raise WorkflowSchemaError("content-team projected visual entry is invalid")
            kind = visual.get("kind")
            label = visual.get("label")
            if not isinstance(kind, str) or not isinstance(label, str):
                raise WorkflowSchemaError("content-team projected visual identity is invalid")
            signature_items.append((kind, label))
        signature = tuple(signature_items)
        layouts: dict[tuple[tuple[str, str], ...], str] = {
            (): "NONE",
            (("IMAGE", ""),): "IMAGE_ONLY",
            (("TABLE", ""),): "TABLE_ONLY",
            (("IMAGE", ""), ("TABLE", "")): "IMAGE_TABLE",
            (("TABLE", ""), ("IMAGE", "")): "TABLE_IMAGE",
            (("IMAGE", "(가)"), ("IMAGE", "(나)")): "IMAGE_IMAGE",
            (("TABLE", "(가)"), ("TABLE", "(나)")): "TABLE_TABLE",
        }
        derived_layout = layouts.get(signature)
        if derived_layout is None:
            raise WorkflowSchemaError("content-team projected visual order is not canonical")

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_draft = _mapping(canonical_output, "draft")
    item_number = canonical_draft.get("item_number")
    stem = canonical_draft.get("stem")
    if isinstance(item_number, int) and isinstance(stem, str):
        canonical_draft["stem"] = normalize_content_team_stem(item_number, stem)
    canonical_draft["visual_layout"] = derived_layout
    canonical_draft["equation_sources"] = []
    preliminary = ContentTeamAuthoringRoleResultV7.model_validate(canonical)
    canonical_draft["equation_sources"] = list(
        derive_content_team_equation_sources(preliminary.output.draft)
    )
    return canonical


def _canonicalize_legacy_editorial_compatibility_result(value: object) -> object:
    """Derive the immutable proposal hash at the trusted validation boundary."""

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    proposal = output.get("proposal")
    if not isinstance(proposal, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_proposal = _mapping(canonical_output, "proposal")
    canonical_proposal["proposal_sha256"] = content_sha256(
        {key: item for key, item in canonical_proposal.items() if key != "proposal_sha256"}
    )
    return canonical


def _canonicalize_legacy_item_extraction_result(value: object) -> object:
    """Derive the extraction self-hash at the trusted validation boundary.

    Workers author the semantic extraction document. The orchestrator owns its canonical
    serialization identity, so an untrusted model-provided digest is never authoritative.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    extraction_result = output.get("extraction_result")
    if not isinstance(extraction_result, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_result = _mapping(canonical_output, "extraction_result")
    canonical_result["result_sha256"] = content_sha256(
        {key: item for key, item in canonical_result.items() if key != "result_sha256"}
    )
    return canonical


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
    if schema_id in {
        "knowledge-analysis-proposal-result@1.0",
        "knowledge-analysis-proposal-result@2.0",
        "knowledge-analysis-proposal-result@3.0",
        "knowledge-analysis-proposal-result@4.0",
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
    }:
        if not isinstance(worker_input.request, KnowledgeAnalysisWorkerRequest):
            raise WorkflowSchemaError("knowledge analysis result requires its typed worker request")
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError("knowledge analysis output reference is not projectable")
        output_definition = _mapping(_mapping(schema, "$defs"), "output")
        proposal_ref = _mapping(_mapping(output_definition, "properties"), "proposal")
        proposal_definition_name = {
            "knowledge-analysis-proposal-result@1.0": "KnowledgeAnalysisWorkerProposal",
            "knowledge-analysis-proposal-result@2.0": "KnowledgeAnalysisWorkerProposal",
            "knowledge-analysis-proposal-result@3.0": "KnowledgeAnalysisWorkerProposalV2",
            "knowledge-analysis-proposal-result@4.0": "KnowledgeAnalysisWorkerProposalV3",
            "knowledge-analysis-proposal-result@5.0": "KnowledgeAnalysisWorkerProposalV4",
            "knowledge-analysis-proposal-result@6.0": "KnowledgeAnalysisWorkerProposalV4",
            "knowledge-analysis-proposal-result@7.0": "KnowledgeAnalysisWorkerProposalV5",
            "knowledge-analysis-proposal-result@8.0": "KnowledgeAnalysisWorkerProposalV6",
        }[schema_id]
        if proposal_ref.get("$ref") != f"#/$defs/{proposal_definition_name}":
            raise WorkflowSchemaError("knowledge analysis proposal reference is not projectable")
        proposal_definition = _mapping(_mapping(schema, "$defs"), proposal_definition_name)
        proposal_properties = _mapping(proposal_definition, "properties")
        _mapping(proposal_properties, "analysis_request_id")["const"] = (
            worker_input.request.analysis_request.analysis_request_id
        )
        anchor_properties = _knowledge_analysis_anchor_properties(schema, proposal_properties)
        analysis_request = worker_input.request.analysis_request
        source = analysis_request.source
        for field_name, value in (
            ("artifact_revision_id", source.artifact_member.artifact_revision_id),
            ("member_path", source.artifact_member.member_path),
        ):
            _bind_result_string_const(schema, _mapping(anchor_properties, field_name), value)
        if isinstance(
            analysis_request,
            (
                KnowledgeAnalysisRequestV3,
                KnowledgeAnalysisRequestV4,
                KnowledgeAnalysisRequestV5,
                KnowledgeAnalysisRequestV6,
                KnowledgeAnalysisRequestV7,
                KnowledgeAnalysisRequestV8,
            ),
        ):
            document_source = analysis_request.source
            pages = "|".join(
                str(page)
                for page in range(
                    document_source.first_physical_page,
                    document_source.last_physical_page + 1,
                )
            )
            _mapping(anchor_properties, "locator")["pattern"] = (
                rf"^physical_page=(?:{pages})(?:;.{{1,220}})?$"
            )
        if isinstance(
            analysis_request,
            (KnowledgeAnalysisRequestV6, KnowledgeAnalysisRequestV7, KnowledgeAnalysisRequestV8),
        ):
            _bind_page_image_observations(
                schema,
                proposal_properties,
                analysis_request,
            )
            _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-extraction-result@1.0":
        if not isinstance(worker_input.request, LegacyItemExtractionWorkerRequest):
            raise WorkflowSchemaError("legacy extraction result requires its typed worker request")
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError("legacy extraction output reference is not projectable")
        output_definition = _mapping(definitions, "output")
        extraction_ref = _mapping(_mapping(output_definition, "properties"), "extraction_result")
        if extraction_ref.get("$ref") != "#/$defs/LegacyItemExtractionResult":
            raise WorkflowSchemaError("legacy extraction result reference is not projectable")
        result_definition = _mapping(definitions, "LegacyItemExtractionResult")
        result_properties = _mapping(result_definition, "properties")
        request = worker_input.request.extraction_request
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "extraction_request_id"),
            request.extraction_request_id,
        )
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "request_sha256"),
            request.request_sha256,
        )
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "result_sha256"),
            "sha256:" + "0" * 64,
        )
        observed_pages = _mapping(result_properties, "observed_page_input_ids")
        observed_pages["minItems"] = len(request.page_inputs)
        observed_pages["maxItems"] = len(request.page_inputs)
        observed_pages["items"] = {
            "type": "string",
            "enum": [page.page_input_id for page in request.page_inputs],
        }
        observed_pages["description"] = (
            "Return every supplied page_input_id exactly once and in the same order as the "
            "request. Do not repeat, omit, or reorder page IDs."
        )
        items = _mapping(result_properties, "items")
        items["minItems"] = len(request.expected_item_numbers)
        items["maxItems"] = len(request.expected_item_numbers)
        items["description"] = (
            "Return exactly one proposal for each requested item number, with no duplicates, "
            "in the same ascending order as expected_item_numbers."
        )
        item_schema = _mapping(items, "items")
        item_properties = _mapping(item_schema, "properties")
        _mapping(item_properties, "item_number")["enum"] = list(request.expected_item_numbers)
        _project_legacy_extraction_relations(
            schema,
            item_properties=item_properties,
            request=worker_input.request,
        )
        content_anchor_map = _mapping(item_properties, "content_anchor_map")
        # Codex's supported Structured Outputs subset cannot express the canonical
        # cross-item existential rule with `contains` or positional array schemas.
        # Strengthen the supported part of the projection and state the remaining
        # ordering contract explicitly; canonical Pydantic validation below the
        # worker boundary remains the authoritative fail-closed check.
        content_anchor_map["minItems"] = 2
        content_anchor_map["description"] = (
            "Return mappings in deterministic source order. The first mapping MUST use "
            'content_path exactly "title". At least one later mapping MUST use a '
            'content_path beginning with "body[". Reuse only source_anchor_ids declared '
            "in this item, and add mappings for every other grounded content element."
        )
        _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-editorial-compatibility-result@1.0":
        if not isinstance(
            worker_input.request,
            LegacyItemEditorialCompatibilityWorkerRequest,
        ):
            raise WorkflowSchemaError(
                "legacy editorial compatibility result requires its typed worker request"
            )
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError(
                "legacy editorial compatibility output reference is not projectable"
            )
        output_definition = _mapping(definitions, "output")
        proposal_ref = _mapping(_mapping(output_definition, "properties"), "proposal")
        if proposal_ref.get("$ref") != "#/$defs/LegacyItemEditorialCompatibilityProposal":
            raise WorkflowSchemaError(
                "legacy editorial compatibility proposal reference is not projectable"
            )
        proposal_definition = _mapping(
            definitions,
            "LegacyItemEditorialCompatibilityProposal",
        )
        proposal_properties = _mapping(proposal_definition, "properties")
        proposal_required = proposal_definition.get("required")
        if not isinstance(proposal_required, list) or "proposal_sha256" not in proposal_required:
            raise WorkflowSchemaError(
                "legacy editorial compatibility proposal hash is not projectable"
            )
        proposal_required.remove("proposal_sha256")
        proposal_properties.pop("proposal_sha256")
        compatibility_request = worker_input.request.compatibility_request
        _bind_result_string_const(
            schema,
            _mapping(proposal_properties, "compatibility_request_id"),
            compatibility_request.compatibility_request_id,
        )
        _bind_result_string_const(
            schema,
            _mapping(proposal_properties, "request_sha256"),
            compatibility_request.request_sha256,
        )
        compatibility_source_properties = _local_definition_properties(
            schema,
            _mapping(proposal_properties, "source"),
        )
        for key, value in (
            ("item_id", compatibility_request.source.item_id),
            ("item_revision_id", compatibility_request.source.item_revision_id),
            ("item_manifest_sha256", compatibility_request.source.item_manifest_sha256),
        ):
            _bind_result_string_const(
                schema,
                _mapping(compatibility_source_properties, key),
                value,
            )
        issue_definition = _mapping(
            definitions,
            "LegacyItemEditorialCompatibilityProposal_issue",
        )
        issue_properties = _mapping(issue_definition, "properties")
        content_paths = _mapping(issue_properties, "item_content_paths")
        content_path_items = _mapping(content_paths, "items")
        content_path_items["pattern"] = r"^[^/\u0000-\u001f][^\u0000-\u001f]*$"
        content_paths["description"] = (
            "Use canonical dot paths into Item content, for example title, body.0.text, "
            "interaction.choices, or solution.correct_choice_ids. JSON Pointer paths that "
            "start with '/' are invalid."
        )
        _prune_unreferenced_definitions(schema)
    validate_codex_structured_output_schema(schema)
    return schema


def _local_definition_properties(
    schema: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    reference = value.get("$ref")
    prefix = "#/$defs/"
    if set(value) != {"$ref"} or not isinstance(reference, str) or not reference.startswith(prefix):
        raise WorkflowSchemaError("local object reference is not independently projectable")
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    return _mapping(definition, "properties")


def _knowledge_analysis_anchor_properties(
    schema: dict[str, Any], proposal_properties: dict[str, Any]
) -> dict[str, Any]:
    anchors = _mapping(proposal_properties, "anchors")
    items = _mapping(anchors, "items")
    reference = items.get("$ref")
    prefix = "#/$defs/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise WorkflowSchemaError("knowledge analysis anchor reference is not projectable")
    anchor_definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    return _mapping(anchor_definition, "properties")


def _bind_result_string_const(
    schema: dict[str, Any], property_schema: dict[str, Any], value: str
) -> None:
    """Bind one exact string without creating a response-format-invalid ref sibling."""

    visited_references: set[str] = set()
    reference = property_schema.get("$ref")
    while reference is not None:
        prefix = "#/$defs/"
        if set(property_schema) != {"$ref"} or not isinstance(reference, str):
            raise WorkflowSchemaError("result string reference is not independently projectable")
        if not reference.startswith(prefix):
            raise WorkflowSchemaError("result string reference is not local")
        if reference in visited_references:
            raise WorkflowSchemaError("result string reference cycle is not projectable")
        visited_references.add(reference)
        definition = copy.deepcopy(
            _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
        )
        property_schema.clear()
        property_schema.update(definition)
        reference = property_schema.get("$ref")
    if property_schema.get("type") != "string" or "$ref" in property_schema:
        raise WorkflowSchemaError("result const binding requires an inline string schema")
    property_schema["const"] = value


def _inline_local_schema(schema: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Copy and fully inline one independently referenced local schema node."""

    projected = copy.deepcopy(value)
    visited_references: set[str] = set()
    reference = projected.get("$ref")
    while reference is not None:
        prefix = "#/$defs/"
        if set(projected) != {"$ref"} or not isinstance(reference, str):
            raise WorkflowSchemaError("local schema reference is not independently projectable")
        if not reference.startswith(prefix):
            raise WorkflowSchemaError("local schema reference is not local")
        if reference in visited_references:
            raise WorkflowSchemaError("local schema reference cycle is not projectable")
        visited_references.add(reference)
        projected = copy.deepcopy(
            _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
        )
        reference = projected.get("$ref")
    return projected


def _exact_legacy_source_pointer_schema(
    schema: dict[str, Any],
    template: dict[str, Any],
    pointer: object,
) -> dict[str, Any]:
    projected = _inline_local_schema(schema, template)
    properties = _mapping(projected, "properties")
    model_dump = getattr(pointer, "model_dump", None)
    if not callable(model_dump):
        raise WorkflowSchemaError("legacy source pointer is not serializable")
    value = model_dump(mode="json")
    if not isinstance(value, dict) or set(value) != set(properties):
        raise WorkflowSchemaError("legacy source pointer shape is not projectable")
    for key, item in value.items():
        if not isinstance(item, str):
            raise WorkflowSchemaError("legacy source pointer field is not an exact string")
        _bind_result_string_const(schema, _mapping(properties, key), item)
    return projected


def _legacy_source_anchor_variant(
    schema: dict[str, Any],
    template: dict[str, Any],
    *,
    pointer: object,
    source_role: str,
    physical_page: int | None,
    page_image: bool,
) -> dict[str, Any]:
    projected = _inline_local_schema(schema, template)
    properties = _mapping(projected, "properties")
    properties["source"] = _exact_legacy_source_pointer_schema(
        schema,
        _mapping(properties, "source"),
        pointer,
    )
    _mapping(properties, "source_role")["const"] = source_role
    if page_image:
        if physical_page is None:
            raise WorkflowSchemaError("legacy page anchor is missing its physical page")
        properties["physical_page"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 100000,
            "const": physical_page,
        }
    return projected


def _project_legacy_extraction_relations(
    schema: dict[str, Any],
    *,
    item_properties: dict[str, Any],
    request: LegacyItemExtractionWorkerRequest,
) -> None:
    """Project canonical cross-field rules as exact identities plus model instructions."""

    extraction_request = request.extraction_request
    source_anchors = _mapping(item_properties, "source_anchors")
    source_anchor_template = _mapping(source_anchors, "items")
    anchor_variants = [
        _legacy_source_anchor_variant(
            schema,
            source_anchor_template,
            pointer=page.image,
            source_role=page.source_role,
            physical_page=page.physical_page,
            page_image=True,
        )
        for page in extraction_request.page_inputs
    ]
    anchor_variants.extend(
        _legacy_source_anchor_variant(
            schema,
            source_anchor_template,
            pointer=materialization.source,
            source_role=materialization.source_role,
            physical_page=None,
            page_image=False,
        )
        for materialization in extraction_request.source_materializations
    )
    if not anchor_variants:
        raise WorkflowSchemaError("legacy extraction request has no projectable anchor source")
    source_anchors["items"] = {"anyOf": anchor_variants}
    source_anchors["description"] = (
        "Every source anchor MUST use one exact pointer/role pair offered by this schema. For "
        "problem and answer pages, source MUST be the supplied page image pointer (PNG), never "
        "the original PDF source pointer, and physical_page MUST match that page input."
    )

    content_properties = _local_definition_properties(
        schema,
        _mapping(item_properties, "item_content"),
    )
    _mapping(content_properties, "body")["description"] = (
        "Preserve the observed body blocks in source order. If any statement_set block is "
        "present, solution.statement_explanations MUST contain exactly one explanation for every "
        "statement_id and no other IDs. With no statement_set, statement_explanations MUST be "
        "empty."
    )
    _mapping(content_properties, "interaction")["description"] = (
        "For single_choice, return exactly one correct_choice_id that resolves to a declared "
        "choice and keep accepted_answers empty. For constructed_response, keep "
        "correct_choice_ids empty and return at least one accepted answer."
    )
    solution_properties = _local_definition_properties(
        schema,
        _mapping(content_properties, "solution"),
    )
    _mapping(solution_properties, "correct_choice_ids")["description"] = (
        "Exactly one declared choice ID for single_choice; empty for constructed_response."
    )
    _mapping(solution_properties, "accepted_answers")["description"] = (
        "Empty for single_choice; one or more source-grounded answers for constructed_response."
    )
    _mapping(solution_properties, "statement_explanations")["description"] = (
        "Use exactly the statement IDs declared across item_content.body statement_set blocks, "
        "one explanation per ID and no extras. Return an empty array only when no statement_set "
        "exists."
    )
    _mapping(item_properties, "linguistic_patterns")["description"] = (
        "Each observation must be internally coherent: uses_statement_set=true requires "
        "choice_grammar=STATEMENT_COMBINATION; prompt_form=SELECT_COMBINATION also requires "
        "uses_statement_set=true."
    )


def _bind_page_image_observations(
    schema: dict[str, Any],
    proposal_properties: dict[str, Any],
    analysis_request: (
        KnowledgeAnalysisRequestV6 | KnowledgeAnalysisRequestV7 | KnowledgeAnalysisRequestV8
    ),
) -> None:
    """Bind model-visible page attestations to exact immutable request pointers."""

    observations = _mapping(proposal_properties, "page_image_observations")
    item_schema = _mapping(observations, "items")
    reference = item_schema.get("$ref")
    prefix = "#/$defs/"
    if (
        set(item_schema) != {"$ref"}
        or not isinstance(reference, str)
        or not reference.startswith(prefix)
    ):
        raise WorkflowSchemaError("page-image observation schema is not independently projectable")
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    expected_images = tuple(
        member
        for member in analysis_request.source.materialization_members
        if member.member_kind == "PAGE_IMAGE"
    )
    if len(expected_images) != analysis_request.source.page_image_count:
        raise WorkflowSchemaError("page-image request pointer count is inconsistent")
    alternatives: list[dict[str, Any]] = []
    for member in expected_images:
        if member.physical_page is None:
            raise WorkflowSchemaError("page-image request pointer has no physical page")
        branch = copy.deepcopy(definition)
        properties = _mapping(branch, "properties")
        physical_page = _mapping(properties, "physical_page")
        if physical_page.get("type") != "integer":
            raise WorkflowSchemaError("page-image physical page is not projectable")
        physical_page["const"] = member.physical_page
        _bind_result_string_const(schema, _mapping(properties, "image_sha256"), member.sha256)
        alternatives.append(branch)
    observations["minItems"] = len(alternatives)
    observations["maxItems"] = len(alternatives)
    observations["items"] = {"anyOf": alternatives}


def load_codex_result_schema(schema_id: str) -> dict[str, Any]:
    """Project the canonical result contract into Codex's strict JSON Schema subset."""

    schema = copy.deepcopy(load_role_result_schema(schema_id))
    schema.pop("$schema", None)
    schema.pop("$id", None)
    if schema_id == "authoring-result@2.0":
        _project_knowledge_authoring_content(schema)
    if schema_id == "authoring-result@7.0":
        _project_content_team_authoring_contract(schema)
    if schema_id in {
        "knowledge-analysis-proposal-result@1.0",
        "knowledge-analysis-proposal-result@2.0",
        "knowledge-analysis-proposal-result@3.0",
        "knowledge-analysis-proposal-result@4.0",
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
    }:
        _project_knowledge_analysis_codex_contract(schema, schema_id=schema_id)
    if schema_id in {
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
    }:
        _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-extraction-result@1.0":
        _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-editorial-compatibility-result@1.0":
        _project_legacy_editorial_compatibility_codex_contract(schema)
        _prune_unreferenced_definitions(schema)
    _normalize_codex_schema(schema)
    validate_codex_structured_output_schema(schema)
    return schema


def _project_legacy_editorial_compatibility_codex_contract(
    schema: dict[str, Any],
) -> None:
    """Flatten canonical refinements that Structured Outputs cannot express.

    The canonical proposal schema and Pydantic model remain the authoritative boundary after
    generation. This projection changes only representation: object refinements are merged into
    their local base definition, the ordered two-authority tuple becomes a bounded union, and the
    status/issues conditional is left to the canonical post-generation validator.
    """

    definitions = _mapping(schema, "$defs")
    prefix = "#/$defs/"

    def flatten_refinement(target: dict[str, Any], *, expected_base: str) -> None:
        composition = target.get("allOf")
        if not isinstance(composition, list) or len(composition) != 2:
            raise WorkflowSchemaError("legacy editorial object refinement is invalid")
        base_reference, refinement = composition
        if (
            base_reference != {"$ref": f"{prefix}{expected_base}"}
            or not isinstance(refinement, dict)
            or set(refinement) != {"properties"}
        ):
            raise WorkflowSchemaError("legacy editorial object refinement is not projectable")
        base = copy.deepcopy(_mapping(definitions, expected_base))
        base_properties = _mapping(base, "properties")
        refinement_properties = _mapping(refinement, "properties")
        for name, value in refinement_properties.items():
            if name not in base_properties or not isinstance(value, dict):
                raise WorkflowSchemaError("legacy editorial field refinement is invalid")
            base_properties[name] = copy.deepcopy(value)
        target.clear()
        target.update(base)

    learned_item = _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_learnedItem")
    flatten_refinement(
        _mapping(_mapping(learned_item, "properties"), "item_content"),
        expected_base="LegacyItemEditorialCompatibilityProposal_artifactMember",
    )
    authority_base = _mapping(
        definitions,
        "LegacyItemEditorialCompatibilityProposal_authorityBase",
    )
    flatten_refinement(
        _mapping(_mapping(authority_base, "properties"), "artifact_member"),
        expected_base="LegacyItemEditorialCompatibilityProposal_artifactMember",
    )
    flatten_refinement(
        _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_contentTeamPrompt"),
        expected_base="LegacyItemEditorialCompatibilityProposal_authorityBase",
    )
    flatten_refinement(
        _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_hwpxProfile"),
        expected_base="LegacyItemEditorialCompatibilityProposal_authorityBase",
    )

    proposal = _mapping(definitions, "LegacyItemEditorialCompatibilityProposal")
    conditional_guards = proposal.pop("allOf", None)
    if not isinstance(conditional_guards, list) or len(conditional_guards) != 2:
        raise WorkflowSchemaError("legacy editorial proposal conditional contract is invalid")
    authorities = _mapping(_mapping(proposal, "properties"), "authorities")
    prefix_items = authorities.pop("prefixItems", None)
    if (
        not isinstance(prefix_items, list)
        or len(prefix_items) != 2
        or authorities.pop("items", None) is not False
        or authorities.get("minItems") != 2
        or authorities.get("maxItems") != 2
    ):
        raise WorkflowSchemaError("legacy editorial authority tuple is not projectable")
    authorities["items"] = {"anyOf": prefix_items}


def _project_content_team_authoring_contract(schema: dict[str, Any]) -> None:
    """Make the model author semantic visuals while EOM derives their renderer route."""

    definitions = _mapping(schema, "$defs")
    draft = _mapping(definitions, "AssessmentItemContentV2")
    properties = _mapping(draft, "properties")
    visual_layout = properties.pop("visual_layout", None)
    if not isinstance(visual_layout, dict):
        raise WorkflowSchemaError("content-team visual layout is not projectable")
    required = draft.get("required")
    if not isinstance(required, list) or required.count("visual_layout") != 1:
        raise WorkflowSchemaError("content-team visual layout requirement is not projectable")
    draft["required"] = [name for name in required if name != "visual_layout"]

    _mapping(properties, "visuals")["description"] = (
        "Ordered semantic visual entries from the reviewed content-team program. A table mentioned "
        "or required by the item must be a TABLE entry containing its actual headers and rows; an "
        "IMAGE entry is only an image slot and must never substitute for table data. Use zero, "
        "one, or two entries exactly as the item requires. For two equal kinds, labels must be "
        "(가), then (나); every other visual label is empty. EOM derives the renderer layout from "
        "this ordered structure."
    )
    _mapping(properties, "inquiry")["description"] = (
        "Use the reviewed 탐구/실험 structure only when the item requires it. When present, keep "
        "visuals empty because the program renders the inquiry box as its own layout."
    )


def _project_knowledge_analysis_codex_contract(schema: dict[str, Any], *, schema_id: str) -> None:
    """Retain essential text presence while projecting unsupported canonical guards."""

    if schema_id in {
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
    }:
        _project_typed_endpoint_identities(schema)
    _strip_knowledge_analysis_codex_guards(schema)
    properties = _mapping(schema, "properties")
    definitions = _mapping(schema, "$defs")
    if _mapping(properties, "output") != {"$ref": "#/$defs/output"}:
        raise WorkflowSchemaError("knowledge analysis output reference is not projectable")
    output = _mapping(definitions, "output")
    proposal_reference = _mapping(_mapping(output, "properties"), "proposal")
    proposal_definition_name = {
        "knowledge-analysis-proposal-result@1.0": "KnowledgeAnalysisWorkerProposal",
        "knowledge-analysis-proposal-result@2.0": "KnowledgeAnalysisWorkerProposal",
        "knowledge-analysis-proposal-result@3.0": "KnowledgeAnalysisWorkerProposalV2",
        "knowledge-analysis-proposal-result@4.0": "KnowledgeAnalysisWorkerProposalV3",
        "knowledge-analysis-proposal-result@5.0": "KnowledgeAnalysisWorkerProposalV4",
        "knowledge-analysis-proposal-result@6.0": "KnowledgeAnalysisWorkerProposalV4",
        "knowledge-analysis-proposal-result@7.0": "KnowledgeAnalysisWorkerProposalV5",
        "knowledge-analysis-proposal-result@8.0": "KnowledgeAnalysisWorkerProposalV6",
    }[schema_id]
    if proposal_reference != {"$ref": f"#/$defs/{proposal_definition_name}"}:
        raise WorkflowSchemaError("knowledge analysis proposal reference is not projectable")
    proposal = _mapping(definitions, proposal_definition_name)
    normalized_markdown = _mapping(_mapping(proposal, "properties"), "normalized_markdown")
    if (
        normalized_markdown.get("type") != "string"
        or normalized_markdown.get("minLength") != 1
        or "pattern" in normalized_markdown
    ):
        raise WorkflowSchemaError(
            "knowledge analysis normalized Markdown contract is not projectable"
        )
    # Codex strict output does not accept minLength. This equivalent lower-bound pattern prevents
    # an empty proposal from passing worker-side validation only to fail the canonical boundary.
    normalized_markdown["pattern"] = r"[\s\S]+"


def _project_typed_endpoint_identities(schema: dict[str, Any]) -> None:
    """Expand canonical all-of refinements into Codex-compatible strict any-of branches."""

    definitions = _mapping(schema, "$defs")
    proposal_name = (
        "KnowledgeAnalysisWorkerProposalV6"
        if "KnowledgeAnalysisWorkerProposalV6" in definitions
        else "KnowledgeAnalysisWorkerProposalV5"
    )
    proposal = _mapping(definitions, proposal_name)
    proposal_properties = _mapping(proposal, "properties")
    for property_name in ("nodes", "edges"):
        collection = _mapping(proposal_properties, property_name)
        items = _mapping(collection, "items")
        reference = items.get("$ref")
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise WorkflowSchemaError("typed identity collection is not projectable")
        definition_name = reference.removeprefix(prefix)
        typed_definition = _mapping(definitions, definition_name)
        composition = typed_definition.get("allOf")
        if not isinstance(composition, list) or len(composition) != 2:
            raise WorkflowSchemaError("typed identity contract composition is invalid")
        base_reference = composition[0]
        refinements = composition[1]
        if not isinstance(base_reference, dict) or set(base_reference) != {"$ref"}:
            raise WorkflowSchemaError("typed identity base reference is invalid")
        base_name = base_reference["$ref"]
        if not isinstance(base_name, str) or not base_name.startswith(prefix):
            raise WorkflowSchemaError("typed identity base reference is not local")
        base = _mapping(definitions, base_name.removeprefix(prefix))
        alternatives = refinements.get("anyOf")
        if not isinstance(alternatives, list) or not alternatives:
            raise WorkflowSchemaError("typed identity refinements are empty")
        projected: list[dict[str, Any]] = []
        for refinement in alternatives:
            if not isinstance(refinement, dict) or refinement.get("type") != "object":
                raise WorkflowSchemaError("typed identity refinement is invalid")
            branch = copy.deepcopy(base)
            branch_properties = _mapping(branch, "properties")
            refinement_properties = _mapping(refinement, "properties")
            for name, value in refinement_properties.items():
                if not isinstance(value, dict) or name not in branch_properties:
                    raise WorkflowSchemaError("typed identity field refinement is invalid")
                branch_properties[name] = copy.deepcopy(value)
            projected.append(branch)
        typed_definition.clear()
        typed_definition["anyOf"] = projected


def _strip_knowledge_analysis_codex_guards(value: object) -> None:
    """Leave cross-field/path guards to canonical schema + typed validation after generation."""

    if isinstance(value, dict):
        value.pop("not", None)
        for child in value.values():
            _strip_knowledge_analysis_codex_guards(child)
    elif isinstance(value, list):
        for child in value:
            _strip_knowledge_analysis_codex_guards(child)


def _prune_unreferenced_definitions(schema: dict[str, Any]) -> None:
    """Retain only the local definitions reachable from the projected schema root.

    The v4 knowledge type catalog intentionally contains contracts used by other application
    boundaries.  Bundling every sibling definition into Codex's response schema would make those
    unrelated contracts part of this worker protocol and can retain composition keywords that the
    Codex strict-output subset does not support.  Reachability is a graph traversal over immutable
    local ``$ref`` edges; a missing target fails closed instead of being silently discarded.
    """

    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return

    prefix = "#/$defs/"

    def referenced_names(value: object, *, include_definitions: bool) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith(prefix):
                found.add(reference.removeprefix(prefix))
            for key, child in value.items():
                if key != "$defs" or include_definitions:
                    found.update(referenced_names(child, include_definitions=include_definitions))
        elif isinstance(value, list):
            for child in value:
                found.update(referenced_names(child, include_definitions=include_definitions))
        return found

    pending = list(referenced_names(schema, include_definitions=False))
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            raise WorkflowSchemaError(f"projected schema references missing definition: {name}")
        reachable.add(name)
        pending.extend(referenced_names(definition, include_definitions=True) - reachable)

    schema["$defs"] = {
        name: definition for name, definition in definitions.items() if name in reachable
    }


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
    unsupported_pattern_tokens = ("(?=", "(?!", "(?<=", "(?<!")

    def visit(value: object, path: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        if "$ref" in value and set(value) != {"$ref"}:
            raise WorkflowSchemaError(
                f"Codex result reference has sibling keywords at {'.'.join(path) or '$'}"
            )
        found = unsupported.intersection(value)
        if found:
            raise WorkflowSchemaError(
                f"Codex result schema uses unsupported keyword at {'.'.join(path) or '$'}: "
                f"{sorted(found)[0]}"
            )
        pattern = value.get("pattern")
        if isinstance(pattern, str) and any(
            token in pattern for token in unsupported_pattern_tokens
        ):
            raise WorkflowSchemaError(
                f"Codex result schema uses unsupported regex lookaround at {'.'.join(path) or '$'}"
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
        elif value.get("type") == "array":
            raise WorkflowSchemaError(
                f"Codex result array has no item schema at {'.'.join(path) or '$'}"
            )
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


def _inline_catalog_schema(
    schema: dict[str, Any], *, require_reference_closure: bool = False
) -> dict[str, Any]:
    reference = "eom://schemas/item-registry/assessment-item-content-v1"
    serialized = json.dumps(schema, ensure_ascii=True)
    if reference not in serialized:
        bundled = schema
    else:
        bundled = _inline_assessment_item_schema(schema, reference)
    knowledge_contracts = (
        (
            "eom://schemas/knowledge/knowledge-analysis-request/2.0",
            "knowledge-analysis-request-v2",
            "KnowledgeAnalysisRequestV2",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/3.0",
            "knowledge-analysis-request-v3",
            "KnowledgeAnalysisRequestV3",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/4.0",
            "knowledge-analysis-request-v4",
            "KnowledgeAnalysisRequestV4",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/5.0",
            "knowledge-analysis-request-v5",
            "KnowledgeAnalysisRequestV5",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/6.0",
            "knowledge-analysis-request-v6",
            "KnowledgeAnalysisRequestV6",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/7.0",
            "knowledge-analysis-request-v7",
            "KnowledgeAnalysisRequestV7",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/8.0",
            "knowledge-analysis-request-v8",
            "KnowledgeAnalysisRequestV8",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0",
            "knowledge-analysis-worker-proposal",
            "KnowledgeAnalysisWorkerProposal",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/2.0",
            "knowledge-analysis-worker-proposal-v2",
            "KnowledgeAnalysisWorkerProposalV2",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/3.0",
            "knowledge-analysis-worker-proposal-v3",
            "KnowledgeAnalysisWorkerProposalV3",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/4.0",
            "knowledge-analysis-worker-proposal-v4",
            "KnowledgeAnalysisWorkerProposalV4",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0",
            "knowledge-analysis-worker-proposal-v5",
            "KnowledgeAnalysisWorkerProposalV5",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0",
            "knowledge-analysis-worker-proposal-v6",
            "KnowledgeAnalysisWorkerProposalV6",
        ),
    )
    for contract_reference, catalog_name, definition_name in knowledge_contracts:
        if contract_reference in json.dumps(bundled, ensure_ascii=True):
            bundled = _inline_knowledge_contract(
                bundled,
                reference=contract_reference,
                catalog_name=catalog_name,
                definition_name=definition_name,
                close_type_dependencies=require_reference_closure,
            )
    legacy_contracts = (
        (
            "eom://schemas/legacy-assessment/legacy-item-extraction-request/1.0",
            "legacy-item-extraction-request",
            "LegacyItemExtractionRequest",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            "legacy-item-extraction-result",
            "LegacyItemExtractionResult",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-request/1.0",
            "legacy-item-editorial-compatibility-request",
            "LegacyItemEditorialCompatibilityRequest",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal/1.0",
            "legacy-item-editorial-compatibility-proposal",
            "LegacyItemEditorialCompatibilityProposal",
        ),
    )
    for contract_reference, catalog_name, definition_name in legacy_contracts:
        if contract_reference in json.dumps(bundled, ensure_ascii=True):
            bundled = _inline_legacy_assessment_contract(
                bundled,
                reference=contract_reference,
                catalog_name=catalog_name,
                definition_name=definition_name,
            )
    Draft202012Validator.check_schema(bundled)
    if require_reference_closure:
        _validate_local_reference_closure(bundled)
    return bundled


def _inline_legacy_assessment_contract(
    schema: dict[str, Any], *, reference: str, catalog_name: str, definition_name: str
) -> dict[str, Any]:
    """Close one extraction role schema over its immutable Catalog-owned dependencies."""

    from eom_catalog_contracts import load_schema

    sources = (
        (reference, definition_name, copy.deepcopy(load_schema(catalog_name))),
        (
            "eom://schemas/legacy-assessment/legacy-assessment-types/1.0",
            "LegacyAssessmentTypes",
            copy.deepcopy(load_schema("legacy-assessment-types")),
        ),
        (
            "eom://schemas/item-origin/item-origin-types/1.0",
            "ItemOriginTypes",
            copy.deepcopy(load_schema("item-origin-types")),
        ),
        (
            "eom://schemas/item-registry/assessment-item-content-v1",
            "AssessmentItemContent",
            copy.deepcopy(load_schema("assessment-item-content")),
        ),
    )

    def rewrite(value: object, *, local_prefix: str | None = None) -> object:
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str):
                    replacement: str | None = None
                    for source_id, prefix, _ in sources:
                        if item == source_id:
                            replacement = f"#/$defs/{prefix}"
                            break
                        fragment = source_id + "#/$defs/"
                        if item.startswith(fragment):
                            replacement = f"#/$defs/{prefix}_" + item.removeprefix(fragment)
                            break
                    if replacement is not None:
                        rewritten[key] = replacement
                    elif local_prefix is not None and item.startswith("#/$defs/"):
                        rewritten[key] = f"#/$defs/{local_prefix}_" + item.removeprefix("#/$defs/")
                    else:
                        rewritten[key] = item
                else:
                    rewritten[key] = rewrite(item, local_prefix=local_prefix)
            return rewritten
        if isinstance(value, list):
            return [rewrite(item, local_prefix=local_prefix) for item in value]
        return value

    bundled = rewrite(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled legacy assessment role schema is not an object")
    definitions = bundled.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise WorkflowSchemaError("bundled legacy assessment definitions are not an object")
    for _, prefix, source in sources:
        body = {
            key: item
            for key, item in source.items()
            if key not in {"$schema", "$id", "title", "$defs"}
        }
        rewritten_body = rewrite(body, local_prefix=prefix)
        if not isinstance(rewritten_body, dict):
            raise WorkflowSchemaError("legacy assessment contract body is not an object")
        definitions[prefix] = rewritten_body
        source_definitions = source.get("$defs", {})
        if not isinstance(source_definitions, dict):
            raise WorkflowSchemaError("legacy assessment contract definitions are invalid")
        for name, value in source_definitions.items():
            definitions[f"{prefix}_{name}"] = rewrite(value, local_prefix=prefix)
    return bundled


def _inline_assessment_item_schema(schema: dict[str, Any], reference: str) -> dict[str, Any]:
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
    return bundled


def _inline_knowledge_contract(
    schema: dict[str, Any],
    *,
    reference: str,
    catalog_name: str,
    definition_name: str,
    close_type_dependencies: bool,
) -> dict[str, Any]:
    """Bundle a Catalog-owned contract for Codex and offline JSON Schema validation."""

    from eom_catalog_contracts import load_schema

    root = copy.deepcopy(load_schema(catalog_name))
    types_v4 = copy.deepcopy(load_schema("knowledge-analysis-types-v4"))
    types_v3 = copy.deepcopy(load_schema("knowledge-analysis-types-v3"))
    types_v2 = copy.deepcopy(load_schema("knowledge-analysis-types-v2"))
    types_v1 = copy.deepcopy(load_schema("knowledge-types"))
    v4_reference = "eom://schemas/knowledge/knowledge-analysis-types/4.0#/$defs/"
    v3_reference = "eom://schemas/knowledge/knowledge-analysis-types/3.0#/$defs/"
    v2_reference = "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/"
    v1_reference = "eom://schemas/knowledge/knowledge-types-v1#/$defs/"

    def rewrite(value: object, *, local_prefix: str | None = None) -> object:
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str):
                    if item == reference:
                        rewritten[key] = f"#/$defs/{definition_name}"
                    elif item.startswith(v4_reference):
                        rewritten[key] = "#/$defs/AnalysisV4_" + item.removeprefix(v4_reference)
                    elif item.startswith(v3_reference):
                        rewritten[key] = "#/$defs/AnalysisV3_" + item.removeprefix(v3_reference)
                    elif item.startswith(v2_reference):
                        rewritten[key] = "#/$defs/AnalysisV2_" + item.removeprefix(v2_reference)
                    elif item.startswith(v1_reference):
                        rewritten[key] = "#/$defs/KnowledgeV1_" + item.removeprefix(v1_reference)
                    elif local_prefix is not None and item.startswith("#/$defs/"):
                        rewritten[key] = f"#/$defs/{local_prefix}_" + item.removeprefix("#/$defs/")
                    else:
                        rewritten[key] = item
                else:
                    rewritten[key] = rewrite(item, local_prefix=local_prefix)
            return rewritten
        if isinstance(value, list):
            return [rewrite(item, local_prefix=local_prefix) for item in value]
        return value

    def body(value: dict[str, Any], *, local_prefix: str | None = None) -> dict[str, Any]:
        cleaned = {
            key: item
            for key, item in value.items()
            if key not in {"$schema", "$id", "title", "$defs"}
        }
        rewritten = rewrite(cleaned, local_prefix=local_prefix)
        if not isinstance(rewritten, dict):
            raise WorkflowSchemaError("knowledge contract body is not an object")
        return rewritten

    bundled = rewrite(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled role schema is not an object")
    definitions = bundled.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise WorkflowSchemaError("bundled role schema definitions are not an object")
    definitions[definition_name] = body(root, local_prefix=definition_name)
    root_definitions = root.get("$defs", {})
    if not isinstance(root_definitions, dict):
        raise WorkflowSchemaError("knowledge contract definitions are not an object")
    for name, value in root_definitions.items():
        definitions[f"{definition_name}_{name}"] = rewrite(value, local_prefix=definition_name)
    serialized_root = json.dumps(root, ensure_ascii=True)
    if close_type_dependencies:
        type_families = (
            (v4_reference, "AnalysisV4", types_v4),
            (v3_reference, "AnalysisV3", types_v3),
            (v2_reference, "AnalysisV2", types_v2),
            (v1_reference, "KnowledgeV1", types_v1),
        )
        selected_prefixes: set[str] = set()
        pending: list[dict[str, Any]] = [root]
        while pending:
            serialized_source = json.dumps(pending.pop(), ensure_ascii=True)
            for family_reference, prefix, source in type_families:
                if prefix not in selected_prefixes and family_reference in serialized_source:
                    selected_prefixes.add(prefix)
                    pending.append(source)
        type_sources = [
            (prefix, source) for _, prefix, source in type_families if prefix in selected_prefixes
        ]
    else:
        # Preserve the byte-for-byte historical v1.4--v1.8 bundle projection.
        type_sources = [("AnalysisV2", types_v2), ("KnowledgeV1", types_v1)]
        if v4_reference in serialized_root:
            type_sources.insert(0, ("AnalysisV4", types_v4))
        if v3_reference in serialized_root:
            type_sources.insert(0, ("AnalysisV3", types_v3))
    for prefix, source in type_sources:
        source_definitions = source.get("$defs")
        if not isinstance(source_definitions, dict):
            raise WorkflowSchemaError("knowledge type definitions are not an object")
        for name, value in source_definitions.items():
            definitions[f"{prefix}_{name}"] = rewrite(value, local_prefix=prefix)
    return bundled


def _validate_local_reference_closure(schema: dict[str, Any]) -> None:
    """Require every reference in a self-contained role schema to resolve locally."""

    def resolve(reference: str) -> None:
        if reference == "#":
            return
        if not reference.startswith("#/"):
            raise WorkflowSchemaError(f"workflow schema reference is external: {reference}")
        current: object = schema
        for raw_token in reference[2:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                raise WorkflowSchemaError(f"workflow schema reference is unresolved: {reference}")

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                resolve(reference)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


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
    if value.get("pattern") == _CANONICAL_SAFE_ARTIFACT_MEMBER_PATTERN:
        # The canonical contract retains its full traversal guard. Codex's structured-output
        # regex engine does not accept lookaround, so its generation-only projection uses an
        # equivalent regular expression. Canonical JSON Schema and Pydantic validation still run
        # after generation at the application boundary.
        value["pattern"] = _CODEX_SAFE_ARTIFACT_MEMBER_PATTERN
    minimum_length = value.get("minLength")
    if minimum_length is not None:
        if (
            not isinstance(minimum_length, int)
            or isinstance(minimum_length, bool)
            or minimum_length < 0
            or value.get("type") != "string"
        ):
            raise WorkflowSchemaError("Codex result string minimum is not projectable")
        if minimum_length > 0:
            pattern = value.get("pattern")
            if pattern is None:
                value["pattern"] = rf"[\s\S]{{{minimum_length},}}"
            elif pattern == _CANONICAL_SAFE_TEXT_PATTERN and minimum_length == 1:
                value["pattern"] = _CODEX_NONEMPTY_SAFE_TEXT_PATTERN
            elif not isinstance(pattern, str):
                raise WorkflowSchemaError("Codex result string pattern is not projectable")
            else:
                try:
                    accepts_empty = re.search(pattern, "") is not None
                except re.error as exc:
                    raise WorkflowSchemaError(
                        "Codex result string pattern cannot be checked for emptiness"
                    ) from exc
                if accepts_empty:
                    raise WorkflowSchemaError(
                        "Codex result string pattern does not preserve its non-empty contract"
                    )
    maximum_length = value.get("maxLength")
    if maximum_length is not None:
        value_type = value.get("type")
        string_type = value_type == "string" or (
            isinstance(value_type, list)
            and set(value_type) == {"string", "null"}
            and len(value_type) == 2
        )
        if (
            not isinstance(maximum_length, int)
            or isinstance(maximum_length, bool)
            or maximum_length < 0
            or not string_type
        ):
            raise WorkflowSchemaError("Codex result string maximum is not projectable")
        _append_projection_instruction(
            value,
            f"The value MUST contain at most {maximum_length} characters.",
        )
    if value.get("uniqueItems") is True:
        value_type = value.get("type")
        array_type = value_type == "array" or (
            isinstance(value_type, list)
            and set(value_type) == {"array", "null"}
            and len(value_type) == 2
        )
        if not array_type:
            raise WorkflowSchemaError("Codex result uniqueness constraint is not projectable")
        _append_projection_instruction(value, "Every array entry MUST be unique.")
    value.pop("minLength", None)
    value.pop("maxLength", None)
    value.pop("uniqueItems", None)
    if "oneOf" in value:
        value["anyOf"] = value.pop("oneOf")
    prefix_items = value.get("prefixItems")
    if isinstance(prefix_items, list):
        if (
            not prefix_items
            or value.get("minItems") != len(prefix_items)
            or value.get("maxItems") != len(prefix_items)
            or any(item != prefix_items[0] for item in prefix_items[1:])
        ):
            raise WorkflowSchemaError(
                "Codex result projection cannot preserve a heterogeneous fixed tuple"
            )
        value["items"] = prefix_items[0]
        value.pop("prefixItems")
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
        array_item_schemas = [
            child["items"]
            for child in alternatives
            if isinstance(child, dict)
            and child.get("type") == "array"
            and isinstance(child.get("items"), dict)
        ]
        if array_item_schemas and all(
            candidate == array_item_schemas[0] for candidate in array_item_schemas[1:]
        ):
            for child in alternatives:
                if (
                    isinstance(child, dict)
                    and child.get("type") == "array"
                    and child.get("maxItems") == 0
                    and "items" not in child
                ):
                    child["items"] = array_item_schemas[0]
    definitions = value.get("$defs")
    if isinstance(definitions, dict):
        for child in definitions.values():
            _normalize_codex_schema(child)


def _append_projection_instruction(value: dict[str, Any], instruction: str) -> None:
    description = value.get("description")
    if description is None:
        value["description"] = instruction
        return
    if not isinstance(description, str):
        raise WorkflowSchemaError("Codex result description is not a string")
    value["description"] = f"{description.rstrip()} {instruction}"


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
