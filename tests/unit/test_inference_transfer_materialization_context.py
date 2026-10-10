"""Pure synthetic context checks; no control store, worker, model or DB access."""

from __future__ import annotations

from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_workflow.inference_transfer_materialization import (
    InferenceTransferMaterializationContext,
    validate_inference_transfer_materialization_plan,
    validate_inference_transfer_workflow_plan,
)
from eom_workflow.models import RoleWorkerInput

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


def materialization_context() -> InferenceTransferMaterializationContext:
    request = workflow_request()
    return InferenceTransferMaterializationContext(
        workflow_id="workflow_" + "1" * 32,
        workflow_request=request,
        worker_input=RoleWorkerInput(
            protocol_version="workflow-role/1.29.0",
            job_id="job_" + "1" * 32,
            workflow_id="workflow_" + "1" * 32,
            step_run_id="steprun_" + "1" * 32,
            attempt=1,
            role="support",
            request=request.worker_request(),
            upstream_artifacts=(),
            artifact={
                "logical_artifact_id": "artifact_" + "8" * 32,
                "revision_id": "rev_" + "8" * 32,
            },
        ),
        core_prompt_sha256=sha("5"),
        prompt_sha256=sha("6"),
    )


def materialization_plan(context: InferenceTransferMaterializationContext) -> dict[str, Any]:
    plan = transfer_plan(context.workflow_request.comparison).model_dump(mode="json")
    plan["access_policy_revision_id"] = context.workflow_request.access_policy_revision_id
    plan["access_policy_sha256"] = context.workflow_request.access_policy_sha256
    plan["requester_permissions_sha256"] = context.workflow_request.requester_permissions_sha256
    plan["core_prompt_sha256"] = context.core_prompt_sha256
    plan["prompt_sha256"] = context.prompt_sha256
    plan["plan_sha256"] = content_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    return plan


def test_actual_validated_application_context_binds_all_plan_pins() -> None:
    context = materialization_context()
    plan = validate_inference_transfer_materialization_plan(
        materialization_plan(context), context=context
    )
    assert plan.access_policy_revision_id == context.workflow_request.access_policy_revision_id
    assert (
        plan.requester_permissions_sha256 == context.workflow_request.requester_permissions_sha256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_policy_revision_id", "accessrev_" + "9" * 32),
        ("access_policy_sha256", sha("9")),
        ("requester_permissions_sha256", sha("9")),
        ("core_prompt_sha256", sha("9")),
        ("prompt_sha256", sha("9")),
        ("workflow_id", "workflow_" + "9" * 32),
        ("comparison_request_sha256", sha("9")),
    ],
)
def test_rehashed_plan_cannot_substitute_independent_context(field: str, value: str) -> None:
    context = materialization_context()
    plan = materialization_plan(context)
    plan[field] = value
    plan["plan_sha256"] = content_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan(plan, context=context)


@pytest.mark.parametrize("field", ["step_key", "core_prompt_sha256", "prompt_sha256"])
def test_copied_invalid_context_literal_and_hash_values_are_reparsed(field: str) -> None:
    context = materialization_context()
    copied = context.model_copy(update={field: "invalid-unvalidated-value"})
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan(
            materialization_plan(context), context=copied
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("workflow_id", "workflow_" + "9" * 32), ("role", "review"), ("attempt", 0)],
)
def test_copied_nested_role_input_cannot_bypass_context_closure(field: str, value: object) -> None:
    context = materialization_context()
    copied = context.model_copy(
        update={"worker_input": context.worker_input.model_copy(update={field: value})}
    )
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan(
            materialization_plan(context), context=copied
        )


def test_copied_application_request_policy_does_not_become_plan_authority() -> None:
    context = materialization_context()
    changed = context.workflow_request.model_copy(update={"access_policy_sha256": sha("9")})
    copied = context.model_copy(update={"workflow_request": changed})
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan(
            materialization_plan(context), context=copied
        )


def test_prejob_workflow_validator_needs_no_ephemeral_job_or_artifact_identity() -> None:
    context = materialization_context()
    plan = validate_inference_transfer_workflow_plan(
        materialization_plan(context),
        workflow_request=context.workflow_request,
        workflow_id=context.workflow_id,
        step_key=context.step_key,
        core_prompt_sha256=context.core_prompt_sha256,
        prompt_sha256=context.prompt_sha256,
    )
    assert plan.access_policy_sha256 == context.workflow_request.access_policy_sha256
