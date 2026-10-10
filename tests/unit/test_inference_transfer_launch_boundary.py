"""Synthetic launch phases; no real worker, database, NAS or capacity changes."""

from __future__ import annotations

import grp
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator import orchestrator as owner
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_protocol import ErrorCode

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


@pytest.mark.parametrize("failure_phase", ["prepare", "materialize", "reauthorize", "launch"])
def test_prelaunch_failure_releases_but_uncertain_launch_retains_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_phase: str
) -> None:
    wrapper = workflow_request()
    prompt = "synthetic launch-boundary prompt"
    plan_body = transfer_plan(
        wrapper.comparison, prompt_sha256=sha256_bytes(prompt.encode())
    ).model_dump(mode="json", exclude={"plan_sha256"})
    plan_body["access_policy_revision_id"] = wrapper.access_policy_revision_id
    plan = type(transfer_plan()).model_validate(
        plan_body | {"plan_sha256": content_sha256(plan_body)}
    )
    orchestrator = Orchestrator.__new__(Orchestrator)
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(staging_root=staging_root, nas_artifact_root=tmp_path / "unused-nas"),
        raising=False,
    )
    jobs: list[JobRecord] = []
    session = SimpleNamespace(get=lambda model, key: jobs[0])
    monkeypatch.setattr(orchestrator, "sessions", lambda: nullcontext(session), raising=False)
    monkeypatch.setattr(owner, "transaction", lambda sessions: nullcontext(session))
    monkeypatch.setattr(orchestrator, "_job_by_idempotency_key", lambda key: None)
    monkeypatch.setattr(orchestrator, "_sync_registry", Mock())
    monkeypatch.setattr(owner, "ensure_protocol_version", Mock())
    monkeypatch.setattr(orchestrator, "_validated_inference_transfer_plan", lambda **kw: plan)

    def check_preflight(session: object, **values: Any) -> frozenset[str]:
        assert not jobs
        context = values["context"]
        assert context.workflow_request == wrapper
        assert context.worker_input.request == wrapper.worker_request()
        assert context.prompt_sha256 == sha256_bytes(prompt.encode())
        return frozenset()

    preflight = Mock(side_effect=check_preflight)
    monkeypatch.setattr(owner, "preflight_inference_transfer_materialization", preflight)

    def submit(session: object, **values: Any) -> tuple[JobRecord, bool]:
        job = JobRecord(
            job_id=values["job_id"],
            protocol_version=values["protocol_version"],
            task_type=values["task_type"],
            idempotency_key=values["idempotency_key"],
            request=values["request"],
            request_hash=content_sha256(values["request"]),
            status="CREATED",
            logical_artifact_id=values["logical_artifact_id"],
            revision_id=values["revision_id"],
        )
        jobs.append(job)
        return job, True

    monkeypatch.setattr(owner, "submit_structured_job", submit)
    events: list[str] = []

    def transition(job_id: str, state: object, event: str, **kwargs: object) -> None:
        jobs[0].status = str(state)
        events.append(event)

    monkeypatch.setattr(orchestrator, "_transition", transition)
    monkeypatch.setattr(
        owner,
        "transition_job",
        lambda session, job_id, state, event, **kw: transition(job_id, state, event),
    )
    monkeypatch.setattr(orchestrator, "get_job", lambda key: jobs[0])
    failures: list[tuple[ErrorCode, str]] = []

    def fail(job_id: str, code: ErrorCode, detail: str, slot: object) -> None:
        failures.append((code, detail))
        jobs[0].status = "FAILED"

    monkeypatch.setattr(orchestrator, "_fail", fail)
    capacity, worker = Mock(), Mock()
    capacity.claim.return_value = SimpleNamespace(lease_id="synthetic-lease", slot_key="slot05")
    monkeypatch.setattr(orchestrator, "capacity", capacity, raising=False)
    monkeypatch.setattr(orchestrator, "worker_adapter", worker, raising=False)
    slot = SimpleNamespace(slot_id=5, linux_user="synthetic-worker")
    monkeypatch.setattr(orchestrator, "_slot_by_key", lambda key: slot)
    monkeypatch.setattr(grp, "getgrnam", lambda user: SimpleNamespace(gr_gid=1001))
    worker.prepare_structured_workspace.return_value = SimpleNamespace(workspace=tmp_path)
    worker.run_prepared.side_effect = OSError("synthetic launch may have started")
    materialize = Mock(return_value=SimpleNamespace(event_data=lambda: {}))
    monkeypatch.setattr(owner, "materialize_execution_step", materialize)
    monkeypatch.setattr(
        owner, "authorized_execution_artifact_revisions", Mock(return_value=frozenset())
    )
    committed = Mock()
    monkeypatch.setattr(owner, "commit_artifact", committed)
    if failure_phase == "prepare":
        worker.prepare_structured_workspace.side_effect = OSError("synthetic preparation failure")
    if failure_phase == "materialize":
        materialize.side_effect = ControlPlaneError(
            "CONTROL_TRANSFER_STAGED_INPUT_INVALID", "staged mismatch"
        )
    authorizations = 0

    def reauthorize(request: object) -> None:
        nonlocal authorizations
        authorizations += 1
        if failure_phase == "reauthorize" and authorizations == 3:
            raise ValueError("synthetic permission revocation")

    result = orchestrator.submit_workflow_role(
        workflow_id=plan.workflow_id,
        step_run_id="steprun_" + "1" * 32,
        step_key="compare_pair",
        attempt=1,
        role="support",
        request=wrapper.worker_request(),
        upstream_artifacts=(),
        result_schema="item-inference-transfer-pair-result@1.0",
        idempotency_key="synthetic-launch-boundary",
        prompt_text=prompt,
        transfer_core_prompt_sha256=sha("5"),
        transfer_workflow_request=wrapper,
        reauthorize_transfer_sources=reauthorize,
    )
    assert result.status == "FAILED"
    assert len(jobs) == 1 and len(failures) == 1
    preflight.assert_called_once()
    capacity.claim.assert_called_once()
    worker.run_resolved_structured.assert_not_called()
    committed.assert_not_called()
    if failure_phase == "launch":
        worker.run_prepared.assert_called_once()
        capacity.defer_uncertain_process.assert_called_once()
        capacity.release.assert_not_called()
        assert events[-1] == "RESOLVED_WORKER_STARTED"
    else:
        worker.run_prepared.assert_not_called()
        capacity.release.assert_called_once()
        capacity.defer_uncertain_process.assert_not_called()
        assert "RESOLVED_WORKER_STARTED" not in events
