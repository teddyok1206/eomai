"""Owner failure boundaries under synthetic transactions; no DB, worker or NAS access."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_protocol import ErrorCode
from eom_workflow.inference_transfer import InferenceTransferPairWorkerRequest
from eom_workflow.inference_transfer_control import validate_inference_transfer_plan_context
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import profile, request, sha


@pytest.mark.parametrize(
    ("source_failure", "expected_detail"),
    [
        (
            ControlPlaneError("CONTROL_TRANSFER_SOURCE_REVOKED", "source revoked"),
            "CONTROL_TRANSFER_SOURCE_REVOKED",
        ),
        (
            ValueError("untrusted internal source-resolution detail"),
            "CONTROL_TRANSFER_AUTHORIZATION_FAILED",
        ),
    ],
)
def test_revocation_after_job_creation_terminalizes_exact_job_without_worker_or_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_failure: ControlPlaneError | ValueError,
    expected_detail: str,
) -> None:
    left, right = profile("a"), profile("b")
    query = request(left, right)
    worker_request = InferenceTransferPairWorkerRequest(
        comparison=query, left_profile=left, right_profile=right
    )
    prompt_text = "synthetic prepared comparison prompt"
    plan = transfer_plan(query, prompt_sha256=sha256_bytes(prompt_text.encode("utf-8")))
    validate_inference_transfer_plan_context(
        plan,
        comparison=query,
        left_profile=left,
        right_profile=right,
        workflow_id=plan.workflow_id,
        core_prompt_sha256=sha("5"),
        prompt_sha256=sha256_bytes(prompt_text.encode("utf-8")),
    )
    workflow_body = {
        "schema_version": "inference-transfer-workflow-request/1.0",
        "request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST",
        "execution_preset_key": "item-inference-transfer-comparison",
        "comparison": query.model_dump(mode="json"),
        "left_profile": left.model_dump(mode="json"),
        "right_profile": right.model_dump(mode="json"),
        "access_policy_revision_id": "accessrev_" + "1" * 32,
        "access_policy_sha256": sha("3"),
        "requester_permissions_sha256": sha("4"),
    }
    workflow_request = InferenceTransferWorkflowRequest.model_validate(
        workflow_body | {"request_sha256": content_sha256(workflow_body)}
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(staging_root=tmp_path / "staging"),
        raising=False,
    )
    monkeypatch.setattr(orchestrator, "sessions", lambda: nullcontext(Mock()), raising=False)
    monkeypatch.setattr(owner_module, "preflight_inference_transfer_materialization", Mock())
    capacity, worker = Mock(), Mock()
    monkeypatch.setattr(orchestrator, "capacity", capacity, raising=False)
    monkeypatch.setattr(orchestrator, "worker_adapter", worker, raising=False)
    monkeypatch.setattr(orchestrator, "_job_by_idempotency_key", lambda key: None)
    monkeypatch.setattr(orchestrator, "_sync_registry", lambda session: None)
    monkeypatch.setattr(orchestrator, "_validated_inference_transfer_plan", lambda **kwargs: plan)
    monkeypatch.setattr(owner_module, "ensure_protocol_version", Mock())
    monkeypatch.setattr(owner_module, "transaction", lambda sessions: nullcontext(Mock()))
    committed = Mock()
    monkeypatch.setattr(owner_module, "commit_artifact", committed)
    jobs: list[JobRecord] = []

    def submit(session: object, **values: Any) -> tuple[JobRecord, bool]:
        job = JobRecord(
            job_id=values["job_id"],
            protocol_version=values["protocol_version"],
            task_type=values["task_type"],
            idempotency_key=values["idempotency_key"],
            request=values["request"],
            request_hash=content_sha256(
                {
                    "protocol_version": values["protocol_version"],
                    "task_type": values["task_type"],
                    "request": values["request"],
                }
            ),
            status="REQUESTED",
            logical_artifact_id=values["logical_artifact_id"],
            revision_id=values["revision_id"],
        )
        jobs.append(job)
        return job, True

    monkeypatch.setattr(owner_module, "submit_structured_job", submit)
    transitions: list[tuple[str, str]] = []

    def transition(job_id: str, state: object, event: str) -> None:
        assert len(jobs) == 1 and jobs[0].job_id == job_id
        jobs[0].status = str(state)
        transitions.append((str(state), event))

    monkeypatch.setattr(orchestrator, "_transition", transition)
    monkeypatch.setattr(orchestrator, "get_job", lambda job_id: jobs[0])
    failures: list[tuple[str, ErrorCode, str, object]] = []

    def fail(job_id: str, code: ErrorCode, detail: str, slot: object) -> None:
        assert jobs[0].job_id == job_id
        failures.append((job_id, code, detail, slot))
        jobs[0].status = "FAILED"

    monkeypatch.setattr(orchestrator, "_fail", fail)
    authorization_states: list[str] = []

    def reauthorize(value: InferenceTransferPairWorkerRequest) -> None:
        assert value == worker_request
        state = "NO_JOB" if not jobs else jobs[0].status
        authorization_states.append(state)
        if state == "QUEUED":
            raise source_failure

    result = orchestrator.submit_workflow_role(
        workflow_id=plan.workflow_id,
        step_run_id="steprun_" + "1" * 32,
        step_key="compare_pair",
        attempt=1,
        role="support",
        request=worker_request,
        upstream_artifacts=(),
        result_schema="item-inference-transfer-pair-result@1.0",
        idempotency_key="synthetic-revocation-after-owner-created-job",
        prompt_text=prompt_text,
        transfer_core_prompt_sha256=sha("5"),
        transfer_workflow_request=workflow_request,
        reauthorize_transfer_sources=reauthorize,
    )

    assert result is jobs[0]
    assert result.status == "FAILED"
    assert result.request["request"] == worker_request.model_dump(mode="json")
    assert authorization_states == ["NO_JOB", "QUEUED"]
    assert transitions == [("VALIDATED", "REQUEST_VALIDATED"), ("QUEUED", "JOB_QUEUED")]
    assert failures == [(result.job_id, ErrorCode.WORKER_UNAVAILABLE, expected_detail, None)]
    capacity.claim.assert_not_called()
    capacity.release.assert_not_called()
    worker.run_structured.assert_not_called()
    worker.run_resolved_structured.assert_not_called()
    committed.assert_not_called()
    assert not (tmp_path / "staging").exists()
