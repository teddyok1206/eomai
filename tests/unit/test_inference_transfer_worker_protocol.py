"""Opt-in source protocol binding tests; never invoke a worker, DB or runtime."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import Orchestrator, _validated_workflow_role_replay
from eom_orchestrator.state_machine import JobState
from eom_workflow.inference_transfer import (
    MAX_TRANSFER_WORKER_CONTEXT_BYTES,
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_RESULT_SCHEMA,
    InferenceTransferPairWorkerRequest,
    validate_inference_transfer_execution_plan,
    validate_inference_transfer_worker_result,
)
from eom_workflow.models import ArtifactSpec, InferenceTransferPairRoleResult, RoleWorkerInput
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_role_input_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import profile, request, result, sha

ROOT = Path(__file__).resolve().parents[2]
JOB = "job_" + "1" * 32
WORKFLOW = "workflow_" + "2" * 32
STEP = "steprun_" + "3" * 32


def _request() -> InferenceTransferPairWorkerRequest:
    return InferenceTransferPairWorkerRequest(
        comparison=request(), left_profile=profile("a"), right_profile=profile("b")
    )


def _input() -> RoleWorkerInput:
    return RoleWorkerInput(
        protocol_version=TRANSFER_PAIR_PROTOCOL,
        job_id=JOB,
        workflow_id=WORKFLOW,
        step_run_id=STEP,
        attempt=1,
        role="support",
        request=_request(),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32, revision_id="rev_" + "5" * 32
        ),
    )


def _result() -> InferenceTransferPairRoleResult:
    source = _input()
    return InferenceTransferPairRoleResult(
        job_id=source.job_id,
        workflow_id=source.workflow_id,
        step_run_id=source.step_run_id,
        artifact=source.artifact,
        completed_at=datetime(2026, 10, 10, 12, tzinfo=UTC),
        output=result(),
    )


def _plan() -> dict[str, Any]:
    manifest = {
        "artifact_id": "artifact_" + "6" * 32,
        "artifact_revision_id": "rev_" + "6" * 32,
        "sha256": sha("6"),
        "logical_name": "instruction-manifest.json",
        "media_type": "application/json",
        "schema_ref": "eom://schemas/control-plane/instruction-bundle-manifest/1.0",
    }
    value: dict[str, Any] = {
        "schema_version": "resolved-execution-plan/1.0",
        "plan_id": "execplan_" + "7" * 32,
        "workflow_id": WORKFLOW,
        "preset_id": "execpreset_" + "9" * 32,
        "preset_revision_id": "execpresetrev_" + "9" * 32,
        "preset_sha256": sha("9"),
        "workflow_definition_key": "item-inference-transfer-comparison",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": sha("a"),
        "content_pack_release_id": "packrel_" + "b" * 32,
        "content_pack_sha256": sha("b"),
        "capacity_policy_revision_id": "capacityrev_" + "c" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
        "evidence_bundle_revision_id": None,
        "steps": [
            {
                "step_key": "compare_pair",
                "role": "support",
                "model": "test-pinned-model",
                "reasoning_effort": "high",
                "instruction_bundle": {
                    "bundle_id": "instrbundle_" + "6" * 32,
                    "bundle_revision_id": "instrrev_" + "6" * 32,
                    "manifest_artifact": manifest,
                    "manifest_sha256": sha("6"),
                },
                "reference_bundle": None,
                "worker_pool_key": "support",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "DENIED",
            }
        ],
        "resolver_version": "1.0.0",
        "resolved_at": "2026-10-10T12:00:00Z",
    }
    value["plan_sha256"] = content_sha256(value)
    return value


def test_schema_first_canonical_role_files_and_package_mirrors_are_identical() -> None:
    for kind in ("input", "result"):
        name = f"item-inference-transfer-pair-{kind}-v1.schema.json"
        original = ROOT / "schemas/workflow/roles" / name
        mirrored = ROOT / "packages/workflow/eom_workflow/resources/roles" / name
        assert original.read_bytes() == mirrored.read_bytes()
        Draft202012Validator.check_schema(json.loads(original.read_text()))


def test_new_protocol_accepts_exact_small_values_without_artifact_materialization() -> None:
    document = _input().model_dump(mode="json")
    parsed = validate_role_input(document, "support", TRANSFER_PAIR_PROTOCOL)
    assert parsed == _input()
    assert isinstance(parsed.request, InferenceTransferPairWorkerRequest)
    assert parsed.upstream_artifacts == ()
    assert len(json.dumps(document["request"]).encode()) < MAX_TRANSFER_WORKER_CONTEXT_BYTES


@pytest.mark.parametrize("version", ["workflow-role/1.22.0", "workflow-role/1.28.0"])
def test_previous_protocol_cannot_reinterpret_new_pair_purpose(version: str) -> None:
    document = _input().model_dump(mode="json")
    document["protocol_version"] = version
    with pytest.raises(ValidationError, match="isolated protocol successor"):
        RoleWorkerInput.model_validate(document)
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(document, "support", version)


def test_pair_protocol_cannot_accept_previous_support_purpose() -> None:
    document = _input().model_dump(mode="json")
    document["request"] = {"request_name": "PLACEHOLDER_REQUEST", "image_mode": "none"}
    with pytest.raises(ValidationError):
        RoleWorkerInput.model_validate(document)
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(document, "support", TRANSFER_PAIR_PROTOCOL)


def test_pair_protocol_rejects_non_support_role() -> None:
    document = _input().model_dump(mode="json")
    document["role"] = "review"
    with pytest.raises(ValidationError, match="support"):
        RoleWorkerInput.model_validate(document)


def test_pair_context_rejects_wrong_profile_and_copied_hash_tampering() -> None:
    source = _request()
    with pytest.raises(ValidationError):
        InferenceTransferPairWorkerRequest(
            comparison=source.comparison,
            left_profile=profile("c"),
            right_profile=source.right_profile,
        )
    tampered = source.left_profile.model_copy(update={"profile_sha256": sha("f")})
    with pytest.raises(ValidationError):
        InferenceTransferPairWorkerRequest(
            comparison=source.comparison,
            left_profile=tampered,
            right_profile=source.right_profile,
        )


def test_pair_context_does_not_silently_truncate_a_large_profile() -> None:
    base = profile("a")
    claim = base.claims[0].model_dump(mode="json")
    body = base.model_dump(mode="json", exclude={"profile_sha256"})
    body["claims"] = [
        claim | {"claim_id": f"transferclaim_{index:03}", "text": "조건" * 1000}
        for index in range(32)
    ]
    body["profile_sha256"] = content_sha256(body)
    large = type(base).model_validate(body)
    with pytest.raises(ValidationError, match="64 KiB"):
        InferenceTransferPairWorkerRequest(
            comparison=request(large, profile("b")), left_profile=large, right_profile=profile("b")
        )


def test_output_envelope_and_context_validate_before_generic_commit() -> None:
    document = _result().model_dump(mode="json")
    parsed = validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA)
    assert isinstance(parsed, InferenceTransferPairRoleResult)
    validate_inference_transfer_worker_result(_request(), parsed.output)
    assert parsed.output.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"


def test_result_foreign_profiles_and_uncited_claims_are_rejected() -> None:
    foreign = result(request(profile("c"), profile("b")))
    with pytest.raises(ValueError):
        validate_inference_transfer_worker_result(_request(), foreign)
    body = result().model_dump(mode="json", exclude={"result_sha256"})
    body["mappings"][0]["left_claim_ids"] = ["transferclaim_absent"]
    body["result_sha256"] = content_sha256(body)
    typed = type(foreign).model_validate(body)
    with pytest.raises(ValueError):
        validate_inference_transfer_worker_result(_request(), typed)


def test_schema_projection_closes_refs_and_restricts_exact_pins_and_claim_ids() -> None:
    schema = constrained_result_schema(TRANSFER_PAIR_RESULT_SCHEMA, _input())
    good = _result().model_dump(mode="json")
    Draft202012Validator(schema).validate(good)
    foreign = copy.deepcopy(good)
    foreign["output"]["left_profile"]["profile_sha256"] = sha("f")
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(foreign)
    uncited = copy.deepcopy(good)
    uncited["output"]["mappings"][0]["left_claim_ids"] = ["transferclaim_absent"]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(uncited)
    text = json.dumps(schema)
    assert "eom://schemas/knowledge" not in text.replace(
        "eom://schemas/knowledge/item-inference-transfer/1.0", ""
    )


def test_loaded_schema_isolation_and_bundle_hash_are_deterministic() -> None:
    first = load_role_input_schema("support", TRANSFER_PAIR_PROTOCOL)
    first["properties"]["role"]["const"] = "authoring"
    assert load_role_input_schema("support", TRANSFER_PAIR_PROTOCOL)["properties"]["role"] == {
        "const": "support"
    }
    assert role_schema_bundle_hash(TRANSFER_PAIR_PROTOCOL) == role_schema_bundle_hash(
        TRANSFER_PAIR_PROTOCOL
    )
    assert load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA) != load_role_result_schema(
        TRANSFER_PAIR_RESULT_SCHEMA
    )


def test_missing_or_unrelated_plan_cannot_fall_back_to_legacy_slot_selection() -> None:
    with pytest.raises(ValueError):
        validate_inference_transfer_execution_plan(
            None, request=_request(), workflow_id=WORKFLOW, step_key="compare_pair"
        )
    foreign = _plan()
    foreign["workflow_definition_key"] = "customer-support"
    foreign["plan_sha256"] = content_sha256(
        {key: value for key, value in foreign.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError, match="purpose"):
        validate_inference_transfer_execution_plan(
            foreign, request=_request(), workflow_id=WORKFLOW, step_key="compare_pair"
        )


def test_purpose_plan_preserves_model_instructions_capacity_and_graph_pins() -> None:
    plan = validate_inference_transfer_execution_plan(
        _plan(), request=_request(), workflow_id=WORKFLOW, step_key="compare_pair"
    )
    assert plan.steps[0].model == "test-pinned-model"
    assert plan.steps[0].sandbox == "read-only"
    assert plan.steps[0].network == "disabled"
    assert plan.capacity_policy_revision_id == "capacityrev_" + "c" * 32


@pytest.mark.parametrize(
    "field,value",
    [("plan_sha256", sha("0")), ("graph_snapshot_revision_id", "graphrev_" + "f" * 32)],
)
def test_plan_hash_and_graph_mismatch_are_explicit(field: str, value: str) -> None:
    plan = _plan()
    plan[field] = value
    if field != "plan_sha256":
        plan["plan_sha256"] = content_sha256(
            {key: item for key, item in plan.items() if key != "plan_sha256"}
        )
    with pytest.raises(ValueError):
        validate_inference_transfer_execution_plan(
            plan, request=_request(), workflow_id=WORKFLOW, step_key="compare_pair"
        )


def test_exact_idempotent_replay_preserves_existing_identity_and_rejects_drift() -> None:
    source = _input()
    document = source.model_dump(mode="json")
    job = JobRecord(
        job_id=JOB,
        protocol_version=TRANSFER_PAIR_PROTOCOL,
        idempotency_key="synthetic-transfer-replay",
        task_type="workflow_support",
        request=document,
        request_hash=content_sha256(
            {
                "protocol_version": TRANSFER_PAIR_PROTOCOL,
                "task_type": "workflow_support",
                "request": document,
            }
        ),
        status="QUEUED",
        logical_artifact_id=source.artifact.logical_artifact_id,
        revision_id=source.artifact.revision_id,
    )
    arguments = {
        "workflow_id": WORKFLOW,
        "step_run_id": STEP,
        "attempt": 1,
        "role": "support",
        "request": source.request,
        "upstream_artifacts": (),
        "result_schema": TRANSFER_PAIR_RESULT_SCHEMA,
    }
    parsed, replay = _validated_workflow_role_replay(job, **arguments)  # type: ignore[arg-type]
    assert parsed.artifact == source.artifact and replay == document
    arguments["request"] = InferenceTransferPairWorkerRequest(
        comparison=request(profile("c"), profile("b")),
        left_profile=profile("c"),
        right_profile=profile("b"),
    )
    with pytest.raises(ValueError, match="conflicts"):
        _validated_workflow_role_replay(job, **arguments)  # type: ignore[arg-type]


def test_input_model_copy_bypass_is_revalidated_at_the_role_boundary() -> None:
    copied = _request().model_copy(update={"left_profile": profile("c")})
    with pytest.raises(ValidationError):
        RoleWorkerInput.model_validate(_input().model_copy(update={"request": copied}).model_dump())


def test_missing_reauthorization_rejects_before_any_job_or_slot_access() -> None:
    # Deliberately uninitialized: any accidental DB/slot access would fail this source-only test.
    orchestrator = Orchestrator.__new__(Orchestrator)
    with pytest.raises(ControlPlaneError, match="owner reauthorization"):
        orchestrator.submit_workflow_role(
            workflow_id=WORKFLOW,
            step_run_id=STEP,
            step_key="compare_pair",
            attempt=1,
            role="support",
            request=_request(),
            upstream_artifacts=(),
            result_schema=TRANSFER_PAIR_RESULT_SCHEMA,
            idempotency_key="synthetic-no-authority",
            prompt_text="synthetic prompt",
        )


@pytest.mark.parametrize("revoked", [False, True])
def test_terminal_replay_reauthorizes_without_executing_or_reinterpreting_history(
    monkeypatch: pytest.MonkeyPatch, revoked: bool
) -> None:
    source = _input()
    document = source.model_dump(mode="json")
    job = JobRecord(
        job_id=JOB,
        protocol_version=TRANSFER_PAIR_PROTOCOL,
        idempotency_key="synthetic-terminal-transfer",
        task_type="workflow_support",
        request=document,
        request_hash=content_sha256(
            {
                "protocol_version": TRANSFER_PAIR_PROTOCOL,
                "task_type": "workflow_support",
                "request": document,
            }
        ),
        status="SUCCEEDED",
        logical_artifact_id=source.artifact.logical_artifact_id,
        revision_id=source.artifact.revision_id,
    )
    orchestrator = Orchestrator.__new__(Orchestrator)
    monkeypatch.setattr(orchestrator, "_job_by_idempotency_key", lambda key: job)
    monkeypatch.setattr(orchestrator, "_resume_pre_execution_job", lambda key: JobState.SUCCEEDED)
    monkeypatch.setattr(orchestrator, "get_job", lambda key: job)
    calls: list[str] = []

    def reauthorize(job_id: str) -> None:
        calls.append(job_id)
        if revoked:
            raise ControlPlaneError("CONTROL_TRANSFER_SOURCE_REVOKED", "source revoked")

    arguments: dict[str, Any] = {
        "workflow_id": WORKFLOW,
        "step_run_id": STEP,
        "step_key": "compare_pair",
        "attempt": 1,
        "role": "support",
        "request": _request(),
        "upstream_artifacts": (),
        "result_schema": TRANSFER_PAIR_RESULT_SCHEMA,
        "idempotency_key": job.idempotency_key,
        "prompt_text": "synthetic prompt",
        "before_execute": reauthorize,
    }
    if revoked:
        with pytest.raises(ControlPlaneError, match="source revoked"):
            orchestrator.submit_workflow_role(**arguments)
    else:
        assert orchestrator.submit_workflow_role(**arguments) is job
    assert calls == [JOB]
    assert job.status == "SUCCEEDED"
