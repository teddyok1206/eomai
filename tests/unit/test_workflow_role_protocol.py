from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_workflow.models import ArtifactPointer, ArtifactSpec, RoleWorkerInput, WorkflowRequest
from eom_workflow.schemas import (
    RESULT_SCHEMA_FILES,
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result,
    validate_schema_message,
)
from jsonschema import Draft202012Validator

JOB_ID = "job_0123456789abcdef0123456789abcdef"
WORKFLOW_ID = "workflow_0123456789abcdef0123456789abcdef"
STEP_RUN_ID = "steprun_0123456789abcdef0123456789abcdef"
ARTIFACT_ID = "artifact_0123456789abcdef0123456789abcdef"
REVISION_ID = "rev_0123456789abcdef0123456789abcdef"


def _input(role: str) -> RoleWorkerInput:
    upstream: tuple[ArtifactPointer, ...] = ()
    if role != "authoring":
        upstream = (
            ArtifactPointer(
                step_key="authoring",
                attempt=1,
                job_id=JOB_ID,
                logical_artifact_id=ARTIFACT_ID,
                revision_id=REVISION_ID,
                content_hash="sha256:" + "a" * 64,
                result_schema="authoring-result@1.0",
            ),
        )
    return RoleWorkerInput(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role=role,  # type: ignore[arg-type]
        request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required"),
        upstream_artifacts=upstream,
        artifact=ArtifactSpec(
            logical_artifact_id=ARTIFACT_ID,
            revision_id=REVISION_ID,
        ),
    )


def _result(role: str) -> dict[str, object]:
    outputs: dict[str, object] = {
        "authoring": {
            "draft": {"title": "PLACEHOLDER_CONTENT", "body": "PLACEHOLDER_CONTENT"},
            "metadata": {"domain": "placeholder"},
        },
        "image": {"image_spec": {"kind": "placeholder", "description": "PLACEHOLDER_IMAGE_SPEC"}},
        "review": {
            "review": {
                "decision": "ready_for_human",
                "findings": [],
                "summary": "PLACEHOLDER_REVIEW",
            }
        },
        "item_management": {
            "registration": {
                "result": "registered_placeholder",
                "summary": "PLACEHOLDER_REGISTRATION",
            }
        },
    }
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.0.1",
        "job_id": JOB_ID,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": STEP_RUN_ID,
        "role": role,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": ARTIFACT_ID,
            "revision_id": REVISION_ID,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": outputs[role],
        "completed_at": datetime(2026, 8, 15, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }


def test_all_workflow_schemas_are_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_definition_schema())
    for role in ("authoring", "image", "review", "item_management"):
        Draft202012Validator.check_schema(load_role_input_schema(role))
    for schema_id in RESULT_SCHEMA_FILES:
        Draft202012Validator.check_schema(load_role_result_schema(schema_id))


def test_all_codex_result_projections_use_the_supported_strict_subset() -> None:
    for schema_id in RESULT_SCHEMA_FILES:
        projected = load_codex_result_schema(schema_id)
        Draft202012Validator.check_schema(projected)
        validate_codex_structured_output_schema(projected)
        assert "$schema" not in projected
        assert "$id" not in projected


def test_codex_result_projection_rejects_a_property_without_an_explicit_type() -> None:
    projected = load_codex_result_schema("authoring-result@1.0")
    artifact = projected["$defs"]["artifact"]
    artifact["properties"]["file_name"] = {"const": "result.json"}

    with pytest.raises(
        WorkflowSchemaError,
        match=r"Codex result property has no explicit type at .*file_name",
    ):
        validate_codex_structured_output_schema(projected)


@pytest.mark.parametrize(
    ("role", "schema_id"),
    [
        ("authoring", "authoring-result@1.0"),
        ("image", "image-result@1.0"),
        ("review", "review-result@1.0"),
        ("item_management", "registration-result@1.0"),
    ],
)
def test_role_input_and_result_pass_schema_and_typed_validation(role: str, schema_id: str) -> None:
    worker_input = _input(role)
    assert validate_role_input(worker_input.model_dump(mode="json"), role) == worker_input
    parsed = validate_role_result(_result(role), role, schema_id)
    assert parsed.role == role


def test_constrained_result_schema_fixes_all_execution_identifiers() -> None:
    worker_input = _input("authoring")
    schema = constrained_result_schema("authoring-result@1.0", worker_input)
    validate_schema_message(schema, _result("authoring"), "constrained-result")
    properties = schema["properties"]
    assert properties["job_id"]["const"] == JOB_ID
    assert properties["workflow_id"]["const"] == WORKFLOW_ID
    assert properties["step_run_id"]["const"] == STEP_RUN_ID


def test_role_schema_bundle_hash_is_canonical() -> None:
    first = role_schema_bundle_hash()
    assert first == role_schema_bundle_hash()
    assert first.startswith("sha256:")


def test_completed_worker_error_result_preserves_invalid_result_semantics() -> None:
    result = _result("authoring")
    result["status"] = "error"

    with pytest.raises(WorkflowSchemaError, match=r"authoring-result@1\.0 at status"):
        validate_role_result(result, "authoring", "authoring-result@1.0")


def test_catalog_request_is_projected_to_the_worker_contract() -> None:
    request = WorkflowRequest.model_validate(
        {
            "request_name": "PLACEHOLDER_REQUEST",
            "image_mode": "skip",
            "content_pack": {
                "pack_key": "generic-placeholder",
                "environment": "development",
            },
            "profiles": {
                "authoring": "authoring-default",
                "review": "review-default",
                "image": "image-placeholder",
                "registration": "registration-default",
            },
            "source_intake": {"batch_ids": ["intake_" + "a" * 32]},
            "registry_intent": {"mode": "CREATE_ITEM"},
        }
    )
    assert request.worker_request().model_dump(mode="json") == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
    }
    worker_input = _input("authoring").model_copy(update={"request": request})
    parsed = RoleWorkerInput.model_validate(worker_input.model_dump(mode="json"))
    assert parsed.request.model_dump(mode="json") == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
    }
