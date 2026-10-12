"""Source-only fixed-purpose guards/ports; no production owner or authority simulation."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_workflow.admission import workflow_admission, workflow_definition_is_admitted
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition_data
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow.local_embedding_workflow import (
    LocalEmbeddingStep,
    LocalEmbeddingWorkflowDefinition,
)
from eom_workflow.models import TerminalStep, WorkflowLimits
from eom_workflow.schemas import LocalEmbeddingAdmissionContractError
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingAdmission,
    validate_local_embedding_runner_admission,
    validate_local_embedding_submission_controls,
)
from eom_workflow_runner.local_embedding_execution_port import (
    LocalEmbeddingNativeExecutor,
    LocalEmbeddingStepPending,
)
from eom_workflow_runner.state_machine import STAGE_TRANSITIONS, WorkflowStage

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.local_embedding_admission_fixtures import member, native_fixture

ROOT = Path(__file__).resolve().parents[2]


def scope_fixture() -> tuple[ResolvedLocalEmbeddingAdmission, CompiledWorkflowDefinition]:
    fixture = native_fixture()
    definition = LocalEmbeddingWorkflowDefinition(
        limits=WorkflowLimits(max_rework_cycles=0, max_step_attempts=1),
        steps=(
            LocalEmbeddingStep(),
            TerminalStep(key="complete", type="terminal", terminal_status="COMPLETED"),
        ),
    )
    compiled = compile_definition_data(
        definition.model_dump(mode="json"), "synthetic-native", set()
    )
    policy = LocalEmbeddingExecutionPolicy.model_validate(
        seal(
            fixture.policy.model_dump(mode="json")
            | {"workflow_definition_sha256": compiled.sha256},
            "policy_sha256",
        )
    )
    request = LocalEmbeddingWorkflowRequestV11.model_validate(
        seal(
            fixture.request.model_dump(mode="json")
            | {
                "workflow_definition_sha256": compiled.sha256,
                "native_execution_policy": member(
                    "policy.json",
                    fixture.request.native_execution_policy.schema_ref,
                    policy.model_dump(mode="json"),
                    "3",
                ).model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    return ResolvedLocalEmbeddingAdmission(request, fixture.plan, policy), compiled


def test_exact_native_definition_admission_is_not_codex_or_runtime_authority() -> None:
    admission = workflow_admission("local-embedding-index", "1.0.0")
    assert admission is not None and admission.role_protocol_version == "local-embedding/1.0"
    assert not workflow_definition_is_admitted("local-embedding-index", "1.0.1")
    scope, definition = scope_fixture()
    assert (
        validate_local_embedding_runner_admission(
            scope, definition, actor_type="human", actor_id="operator_" + "1" * 32
        )
        == scope
    )
    with pytest.raises(TypeError):
        cast(type[object], LocalEmbeddingOwnerAdmission)()
    with pytest.raises(TypeError):
        cast(type[object], LocalEmbeddingNativeExecutor)()


@pytest.mark.parametrize(
    "actor_type,actor_id",
    [
        ("system", "operator_" + "1" * 32),
        ("human", "guiadmin"),
        ("human", "operator_" + "2" * 32),
        ("WORKER", "operator_" + "1" * 32),
    ],
)
def test_audit_mismatch_is_rejected_without_role_impersonation(
    actor_type: str, actor_id: str
) -> None:
    scope, definition = scope_fixture()
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_OPERATOR_UNAVAILABLE"):
        validate_local_embedding_runner_admission(
            scope, definition, actor_type=actor_type, actor_id=actor_id
        )


def test_future_service_audit_has_no_owner_default_or_grant() -> None:
    scope, _ = scope_fixture()
    body = scope.request.model_dump(mode="json")
    body["actor_context"] = {
        "kind": "LOCAL_INDEXING_SERVICE",
        "service_id": "localindexservice_" + "1" * 32,
        "service_revision_id": "localindexservicerev_" + "1" * 32,
        "service_identity_sha256": sha("1"),
        "service_policy_revision_id": "accessrev_" + "1" * 32,
        "service_policy_sha256": sha("1"),
        "authorization_audit_sha256": sha("1"),
    }
    request = LocalEmbeddingWorkflowRequestV11.model_validate(seal(body, "request_sha256"))
    with pytest.raises(
        LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_SERVICE_UNAVAILABLE"
    ):
        ResolvedLocalEmbeddingAdmission(request, scope.plan, scope.policy)


@pytest.mark.parametrize("change", ["hash", "snapshot", "typed_definition"])
def test_forged_compiled_definition_is_recompiled_and_exact(change: str) -> None:
    scope, definition = scope_fixture()
    if change == "hash":
        bad = replace(definition, sha256=sha("0"))
    elif change == "snapshot":
        bad = replace(definition, canonical_bytes=b"{}")
    else:
        bad = replace(
            definition,
            definition=definition.definition.model_copy(update={"definition_version": "1.0.1"}),
        )
    with pytest.raises(ValueError):
        validate_local_embedding_runner_admission(
            scope, bad, actor_type="human", actor_id="operator_" + "1" * 32
        )


def test_unvalidated_scope_and_copied_bool_recipe_are_revalidated() -> None:
    scope, definition = scope_fixture()
    bad_request = scope.request.model_copy(
        update={
            "resource_profile": scope.request.resource_profile.model_copy(update={"threads": True})
        }
    )
    with pytest.raises((ValueError, LocalEmbeddingAdmissionContractError)):
        ResolvedLocalEmbeddingAdmission(bad_request, scope.plan, scope.policy)
    bad = object.__new__(ResolvedLocalEmbeddingAdmission)
    for field, value in (("request", bad_request), ("plan", scope.plan), ("policy", scope.policy)):
        object.__setattr__(bad, field, value)
    with pytest.raises(ValueError):
        validate_local_embedding_runner_admission(
            bad, definition, actor_type="human", actor_id="operator_" + "1" * 32
        )


def test_zero_demand_controls_are_coverage_only_not_native_start_admission() -> None:
    scope, definition = scope_fixture()
    plan = type(scope.plan).model_validate(
        seal(
            scope.plan.model_dump(mode="json")
            | {
                "demands": [],
                "missing_solution_report_revision_ids": [
                    source.item_revision_id for source in scope.plan.sources
                ],
                "encoding_set_sha256": embedding_input_set_sha256(()),
            },
            "plan_sha256",
        )
    )
    request = LocalEmbeddingWorkflowRequestV11.model_validate(
        seal(
            scope.request.model_dump(mode="json")
            | {
                "source_plan": member(
                    "source-plan.json",
                    scope.request.source_plan.schema_ref,
                    plan.model_dump(mode="json"),
                    "2",
                ).model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    empty = ResolvedLocalEmbeddingAdmission(request, plan, scope.policy)
    assert (
        validate_local_embedding_submission_controls(
            empty, definition, actor_type="human", actor_id="operator_" + "1" * 32
        )
        == empty
    )
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_COVERAGE_ONLY"):
        validate_local_embedding_runner_admission(
            empty, definition, actor_type="human", actor_id="operator_" + "1" * 32
        )


def test_native_stage_has_only_terminal_targets_and_no_authoring_transition() -> None:
    assert STAGE_TRANSITIONS[WorkflowStage.LOCAL_EMBEDDING] == frozenset(
        {WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    )
    assert WorkflowStage.LOCAL_EMBEDDING not in STAGE_TRANSITIONS[WorkflowStage.AUTHORING]


def pending_row(status: str = "OWNED") -> Any:
    fixture = native_fixture("a")
    from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult

    return EmbeddingEncodingReadResult.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-job/1.0",
                "record_type": "READ_RESULT",
                "owned_job": fixture.association.owned_jobs[0].model_dump(mode="json"),
                "owner_intent": fixture.association.intent.model_dump(mode="json"),
                "status": status,
                "completion": None,
            },
            "read_sha256",
        )
    )


@pytest.mark.parametrize("status", ["OWNED", "BORROWED", "UNCERTAIN"])
def test_pending_outcome_reuses_typed_existing_reads_not_boolean_success(status: str) -> None:
    row = pending_row(status)
    assert LocalEmbeddingStepPending((row,)).readings == (row,)


def test_completed_compute_reads_can_still_wait_for_real_index_registration() -> None:
    fixture = native_fixture("a")
    from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult

    row = EmbeddingEncodingReadResult.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-job/1.0",
                "record_type": "READ_RESULT",
                "owned_job": fixture.association.owned_jobs[0].model_dump(mode="json"),
                "owner_intent": fixture.association.intent.model_dump(mode="json"),
                "status": "COMPLETED",
                "completion": fixture.completions[0].model_dump(mode="json"),
            },
            "read_sha256",
        )
    )
    assert LocalEmbeddingStepPending((row,)).readings == (row,)


@pytest.mark.parametrize(
    "kind", ["empty", "duplicate", "list", "too_many", "failed", "cancelled", "copied"]
)
def test_pending_outcome_is_bounded_unique_and_cannot_hide_terminal_failure(kind: str) -> None:
    row = pending_row()
    readings: Any = (row,)
    if kind == "empty":
        readings = ()
    elif kind == "duplicate":
        readings = (row, row)
    elif kind == "list":
        readings = [row]
    elif kind == "too_many":
        readings = (row,) * 1025
    elif kind in {"failed", "cancelled"}:
        readings = (pending_row(kind.upper()),)
    else:
        readings = (row.model_copy(update={"status": "SUCCEEDED"}),)
    with pytest.raises(ValueError):
        LocalEmbeddingStepPending(readings)


def test_no_concrete_owner_launcher_implementation_or_sql_executes_in_ports() -> None:
    for filename in ("local_embedding_admission.py", "local_embedding_execution_port.py"):
        source = (ROOT / "services/workflow_runner/eom_workflow_runner" / filename).read_text()
        tree = ast.parse(source)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "commit", "begin", "Popen", "run"}
            for node in ast.walk(tree)
        )
        assert "PlatformRoleJobExecutor" not in source
