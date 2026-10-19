"""Actual Runner/checkpoint DTO paths with synthetic owners, never runtime proof."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    parse_local_embedding_launch_intent_for_request,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_embedding_request_v2 import LocalEmbeddingWorkflowRequestV2
from eom_workflow.local_embedding_source_plan_v2 import LocalEmbeddingSourcePlanV2
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LocalEmbeddingStepOutputV2,
    LocalEmbeddingWorkflowReceiptV2,
    validate_local_embedding_step_output_v2,
    validate_local_embedding_workflow_receipt_v2,
)
from eom_workflow.native_embedding_coordinator_v2 import NativeCoordinatorCompletedV2
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_step_execution import (
    advance_local_embedding_step,
    complete_local_embedding_terminal,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_embedding_runner_execution import SyntheticExecution, execution_fixture
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_scope
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture


def mixed_execution() -> tuple[SyntheticExecution, LocalEmbeddingStepOutputV2]:
    execution = execution_fixture()
    build_scope = cast(
        Callable[[], tuple[ResolvedLocalEmbeddingAdmission, CompiledWorkflowDefinition, object]],
        mixed_scope,
    )
    scope, compiled, _grant = build_scope()
    assert isinstance(scope.request, LocalEmbeddingWorkflowRequestV2)
    assert isinstance(scope.plan, LocalEmbeddingSourcePlanV2)
    assert isinstance(scope.policy, LocalEmbeddingServiceExecutionPolicy)
    request, plan, policy = scope.request, scope.plan, scope.policy
    values = carrier_fixture()
    execution.scope, execution.compiled = scope, compiled
    execution.workflow.definition_version = "2.0.0"
    execution.workflow.definition_hash = compiled.sha256
    execution.workflow.initial_request = execution.workflow.request_payload = (
        scope.request.model_dump(mode="json")
    )
    execution.workflow.created_actor_type = "local_indexing_service"
    execution.workflow.created_actor_id = scope.request.actor_context.service_id
    execution.step.input_pointer_manifest = {
        "source_plan": scope.request.source_plan.model_dump(mode="json"),
        "source_plan_sha256": scope.request.source_plan_sha256,
    }
    execution.owner.resolve_submission.return_value = scope
    # Metadata-only completion has genuine full eligible coverage, but no new
    # numeric association. Do not retag the existing computational Job/input1.
    receipt = LocalEmbeddingWorkflowReceiptV2.model_validate(
        seal(
            values["receipt"].model_dump(mode="json")
            | {
                "workflow_definition_sha256": scope.request.workflow_definition_sha256,
                "workflow_request_sha256": scope.request.request_sha256,
                "native_launch_job_id": None,
                "launch_association_sha256": None,
            },
            "receipt_sha256",
        )
    )
    output = LocalEmbeddingStepOutputV2.model_validate(
        seal(
            values["output"].model_dump(mode="json")
            | {
                "receipt_sha256": receipt.receipt_sha256,
                "receipt": values["output"].receipt.model_dump(mode="json")
                | {
                    "artifact_id": "artifact_" + "d" * 32,
                    "artifact_revision_id": "rev_" + "d" * 32,
                    "sha256": sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json"))),
                },
            },
            "output_sha256",
        )
    )
    assert output.workflow_id == execution.workflow.workflow_id
    assert output.step_run_id == execution.step.step_run_id
    intent = parse_local_embedding_launch_intent_for_request(
        seal(
            values["association"].intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": scope.request.request_sha256,
            },
            "intent_sha256",
        ),
        scope.request,
    )
    checkpoint = NativeEmbeddingCoordinator(intent, scope.request).checkpoint(
        "COMPLETED", NativeCoordinatorCompletedV2(output=output)
    )
    assert isinstance(checkpoint.payload, NativeCoordinatorCompletedV2)

    def execute(**_kwargs: Any) -> LocalEmbeddingStepOutputV2:
        assert execution.depth == 0
        assert isinstance(checkpoint.payload, NativeCoordinatorCompletedV2)
        return checkpoint.payload.output

    def completion(**kwargs: Any) -> LocalEmbeddingStepOutputV2:
        assert execution.depth == 1
        validate_local_embedding_workflow_receipt_v2(
            receipt,
            request,
            plan,
            policy,
            workflow_id=execution.workflow.workflow_id,
            step_run_id=execution.step.step_run_id,
            receipt_owner_job_id=output.receipt_owner_job_id,
            launch_association=None,
            owned_input=None,
            index_coverage=values["coverage"],
        )
        return validate_local_embedding_step_output_v2(kwargs["output"], receipt)

    execution.executor.execute.side_effect = execute
    execution.executor.validate_completion.side_effect = completion
    return execution, output


def advance(execution: SyntheticExecution) -> bool:
    return advance_local_embedding_step(
        workflow=execution.workflow,
        compiled=execution.compiled,
        request=execution.scope.request,
        lease=execution.lease,
        owner=execution.owner,
        executor=execution.executor,
        fenced_transaction=execution.fenced,
        poll_interval_seconds=1,
        actor_type=execution.workflow.created_actor_type,
        actor_id=execution.workflow.created_actor_id,
    )


def complete(execution: SyntheticExecution) -> None:
    complete_local_embedding_terminal(
        workflow_id=execution.workflow.workflow_id,
        request=execution.scope.request,
        lease=execution.lease,
        executor=execution.executor,
        fenced_transaction=execution.fenced,
        actor_type=execution.workflow.created_actor_type,
        actor_id=execution.workflow.created_actor_id,
    )


def test_completed_checkpoint2_advances_terminal_and_exact_replays_without_dispatch() -> None:
    execution, output = mixed_execution()
    assert advance(execution) is True
    assert execution.step.state == "SUCCEEDED"
    assert execution.step.platform_job_id == output.receipt_owner_job_id
    assert execution.step.output_pointer_manifest == output.model_dump(mode="json")
    complete(execution)
    before, rows = execution.workflow.runtime_context.copy(), len(execution.rows)
    complete(execution)
    assert execution.workflow.state == execution.workflow.stage == "COMPLETED"
    assert (
        execution.workflow.runtime_context
        == before
        == {"final_pointer_manifest": {"embedding_receipt": output.model_dump(mode="json")}}
    )
    assert len(execution.rows) == rows
    assert execution.executor.execute.call_count == 1
    assert execution.executor.validate_completion.call_count == 3


@pytest.mark.parametrize("request2", (False, True))
def test_cross_family_outcome_rejects_before_owner_completion(request2: bool) -> None:
    mixed, output2 = mixed_execution()
    legacy = execution_fixture()
    execution, wrong = (mixed, legacy.output) if request2 else (legacy, output2)
    assert isinstance(execution.scope.request, LocalEmbeddingWorkflowRequestV2) is request2
    execution.executor.execute.side_effect = lambda **_kwargs: wrong
    # Even a permissive injected owner cannot erase the Runner's family rule.
    execution.executor.validate_completion.side_effect = lambda **kwargs: kwargs["output"]
    with pytest.raises(WorkflowError) as failure:
        advance(execution)
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    execution.executor.validate_completion.assert_not_called()
    assert execution.step.platform_job_id is None
    assert execution.step.output_pointer_manifest is None
    assert execution.step.state == "RUNNING"
    assert execution.workflow.current_step_key == "encode_batch"


@pytest.mark.parametrize("phase", ("successful_step_replay", "terminal"))
def test_stored_wrong_family2_receipt_never_completes_or_rewrites_history(phase: str) -> None:
    execution, _output = mixed_execution()
    assert advance(execution)
    execution.step.output_pointer_manifest = execution_fixture().output.model_dump(mode="json")
    before = execution.step.output_pointer_manifest.copy()
    execution.executor.validate_completion.reset_mock()
    if phase == "successful_step_replay":
        execution.workflow.current_step_key = "encode_batch"
    with pytest.raises(WorkflowError) as failure:
        advance(execution) if phase == "successful_step_replay" else complete(execution)
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    assert execution.step.output_pointer_manifest == before
    assert execution.step.state == "SUCCEEDED" and execution.workflow.state == "RUNNING"
    execution.executor.validate_completion.assert_not_called()
    assert execution.executor.execute.call_count == 1
