"""Creative execution wiring with synthetic persistence and a non-Codex worker.

No model, systemd unit, production DB, or NAS is accessed by this fixture.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_execution import (
    ExternalItemLearningExecutionContext,
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.state_machine import JobState
from eom_orchestrator.worker import PreparedWorkerWorkspace, WorkerRun
from eom_workflow.control_plane import (
    parse_creative_learning_execution_plan,
)
from eom_workflow.models import ExternalItemLearningWorkerRequest

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_result_contract import _result


def _record(*, successor: bool = False) -> ResolvedExecutionPlanRecord:
    plan = parse_creative_learning_execution_plan(_plan(successor=successor))
    return ResolvedExecutionPlanRecord(
        plan_id=plan.plan_id,
        workflow_id=plan.workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
        plan_sha256=plan.plan_sha256,
        resolver_version=plan.resolver_version,
        resolved_at=plan.resolved_at,
        canonical_document=plan.model_dump(mode="json"),
    )


@pytest.mark.parametrize("changed", [None, "hash", "workflow", "preset", "graph", "time"])
def test_plan_binds_full_row_identity_before_execution(changed: str | None) -> None:
    record = _record()
    request = ExternalItemLearningWorkerRequest(work_input=_plan()["work_input"])
    if changed == "hash":
        record.plan_sha256 = "sha256:" + "0" * 64
    elif changed == "workflow":
        record.workflow_id = "workflow_" + "0" * 32
    elif changed == "preset":
        record.preset_revision_id = "execpresetrev_" + "0" * 32
    elif changed == "graph":
        record.graph_snapshot_revision_id = "graphrev_" + "0" * 32
    elif changed == "time":
        record.resolved_at = None
    if changed:
        with pytest.raises(ControlPlaneError, match="exact creative execution plan"):
            validate_external_item_learning_execution_plan(
                record, workflow_id=_plan()["workflow_id"], step_key="extract", request=request
            )
    else:
        plan = validate_external_item_learning_execution_plan(
            record, workflow_id=record.workflow_id, step_key="extract", request=request
        )
        assert plan.work_input == request.work_input


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, successor: bool = False):
    record = _record(successor=successor)
    plan = parse_creative_learning_execution_plan(record.canonical_document)
    request = ExternalItemLearningWorkerRequest(work_input=plan.work_input)
    orchestrator = object.__new__(Orchestrator)
    settings = SimpleNamespace(
        staging_root=tmp_path / "staging", nas_artifact_root=tmp_path / "nas"
    )
    settings.staging_root.mkdir()
    session = Mock()
    session.scalar.return_value = record
    orchestrator.settings = settings
    orchestrator.sessions = lambda: nullcontext(session)
    orchestrator.capacity = Mock()
    orchestrator.capacity.claim.return_value = SimpleNamespace(
        lease_id="lease-test", slot_key="slot01"
    )
    slot = SimpleNamespace(slot_id="01", linux_user="synthetic-worker")
    monkeypatch.setattr(orchestrator, "_slot_by_key", lambda _key: slot)
    monkeypatch.setattr(orchestrator, "_job_by_idempotency_key", lambda _key: None)
    monkeypatch.setattr(orchestrator, "_sync_registry", Mock())
    monkeypatch.setattr(orchestrator, "_publish_visual_references", Mock(return_value={}))
    monkeypatch.setattr(owner_module.grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=123))
    monkeypatch.setattr(owner_module, "transaction", lambda _sessions: nullcontext(session))
    monkeypatch.setattr(owner_module, "ensure_protocol_version", Mock())
    monkeypatch.setattr(
        owner_module, "authorized_execution_artifact_revisions", Mock(return_value=frozenset())
    )
    evidence = SimpleNamespace(event_data=lambda: {"fixture": "local-page-inputs"})
    materialize = Mock(return_value=evidence)
    monkeypatch.setattr(owner_module, "materialize_execution_step", materialize)
    jobs = []
    transitions = []
    events = []

    def submit(_session, **values):
        job = JobRecord(
            job_id=values["job_id"],
            protocol_version=values["protocol_version"],
            idempotency_key=values["idempotency_key"],
            request=values["request"],
            request_hash=content_sha256(
                {
                    "protocol_version": values["protocol_version"],
                    "task_type": values["task_type"],
                    "request": values["request"],
                }
            ),
            task_type=values["task_type"],
            status="CREATED",
            logical_artifact_id=values["logical_artifact_id"],
            revision_id=values["revision_id"],
        )
        jobs.append(job)
        session.get.return_value = job
        session.execute.return_value.scalar_one.return_value = job
        return job, True

    monkeypatch.setattr(owner_module, "submit_structured_job", submit)

    def transition(_job_id, state, event, **_kwargs):
        jobs[0].status = state.value
        transitions.append((state.value, event))

    monkeypatch.setattr(orchestrator, "_transition", transition)
    monkeypatch.setattr(
        owner_module,
        "transition_job",
        lambda _session, job_id, state, event, **kwargs: transition(job_id, state, event, **kwargs),
    )
    monkeypatch.setattr(orchestrator, "get_job", lambda _job_id: jobs[0])

    def fail(_job_id, code, message, _slot):
        jobs[0].status = "FAILED"
        jobs[0].error_code = str(code)
        jobs[0].error_message = message

    monkeypatch.setattr(orchestrator, "_fail", fail)
    worker = Mock()
    orchestrator.worker_adapter = worker
    inputs = []

    def prepare(**values):
        inputs.append(values["input_document"])
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        events.append("prepare")
        return PreparedWorkerWorkspace(
            values["job_id"], workspace, workspace / "schema.json", workspace / "prompt.txt"
        )

    def run(**values):
        events.append("worker-test-double")
        value = inputs[0]
        if successor:
            from tests.unit.test_external_item_learning_result_v2 import result_v2

            learning_result = result_v2()
        else:
            learning_result = _result()
        source = request.work_input.source
        for field in ("input_sha256", "source_id", "source_revision_id", "external_number"):
            learning_result[field] = getattr(source, field)
        learning_result["result_sha256"] = content_sha256(
            {key: item for key, item in learning_result.items() if key != "result_sha256"}
        )
        result_path = tmp_path / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "protocol_version": value["protocol_version"],
                    "job_id": value["job_id"],
                    "workflow_id": value["workflow_id"],
                    "step_run_id": value["step_run_id"],
                    "role": "support",
                    "status": "ok",
                    "artifact": value["artifact"],
                    "completed_at": "2026-10-27T12:00:00Z",
                    "output": {"learning_result": learning_result},
                }
            ),
            encoding="utf-8",
        )
        return WorkerRun(
            0, result_path, tmp_path / "stdout.log", tmp_path / "stderr.log", "synthetic-unit"
        )

    worker.prepare_structured_workspace.side_effect = prepare
    worker.run_prepared.side_effect = run
    source_authorizer = Mock(side_effect=lambda _request: events.append("authorize-source"))
    publisher = Mock()
    publisher.settings = settings
    artifact = request.work_input.page_artifact
    publisher.read_published_revision.return_value = SimpleNamespace(
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.artifact_revision_id,
        primary_file=artifact.member_path,
        primary_sha256=artifact.sha256,
        manifest_sha256=artifact.file_set_manifest_sha256,
        nas_path=settings.nas_artifact_root / artifact.artifact_id / artifact.artifact_revision_id,
    )
    context = ExternalItemLearningExecutionContext(source_authorizer, publisher)
    staged = SimpleNamespace(
        content_hash="sha256:" + "1" * 64,
        manifest_hash="sha256:" + "2" * 64,
        content_bytes=42,
        manifest=SimpleNamespace(content_bytes=42, model_dump=lambda **_kwargs: {}),
    )
    monkeypatch.setattr(owner_module, "stage_structured_artifact", Mock(return_value=staged))
    commit = Mock(return_value=tmp_path / "committed-test-artifact")
    monkeypatch.setattr(owner_module, "commit_artifact", commit)
    monkeypatch.setattr(owner_module, "create_artifact_records", Mock())
    return SimpleNamespace(
        orchestrator=orchestrator,
        request=request,
        plan=plan,
        context=context,
        worker=worker,
        source=source_authorizer,
        publisher=publisher,
        jobs=jobs,
        materialize=materialize,
        commit=commit,
        transitions=transitions,
        events=events,
    )


def _execute(value, *, result_schema="external-item-learning-result@1.0"):
    return value.orchestrator.submit_workflow_role(
        workflow_id=value.plan.workflow_id,
        step_run_id="steprun_" + "0" * 32,
        step_key="extract",
        attempt=1,
        role="support",
        request=value.request,
        upstream_artifacts=(),
        result_schema=result_schema,
        idempotency_key="synthetic-creative-role-execution",
        prompt_text="synthetic prompt",
        external_item_learning=value.context,
    )


def test_prepared_execution_wires_pages_capacity_and_result_without_codex(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    result = _execute(value)
    assert result.status == "SUCCEEDED"
    value.worker.run_resolved_structured.assert_not_called()
    value.worker.run_prepared.assert_called_once()
    assert value.materialize.call_args.kwargs["creative_page_publisher"] is value.publisher
    assert (
        value.orchestrator.capacity.claim.call_args.args[0].workload_class == "KNOWLEDGE_ANALYSIS"
    )
    assert value.source.call_count == 4
    assert value.publisher.read_published_revision.call_count == 2
    value.commit.assert_called_once()
    value.orchestrator.capacity.release.assert_called_once()
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()


@pytest.mark.parametrize("failure_at", [2, 3, 4])
def test_source_revocation_never_commits_an_unapproved_result(monkeypatch, tmp_path, failure_at):
    value = _fixture(monkeypatch, tmp_path)
    value.source.side_effect = [None] * (failure_at - 1) + [ValueError("revoked source")]
    result = _execute(value)
    assert result.status == "FAILED"
    assert result.error_message == "CONTROL_CREATIVE_SOURCE_AUTHORIZATION_FAILED"
    value.commit.assert_not_called()
    assert value.worker.run_prepared.call_count == (1 if failure_at == 4 else 0)
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()


def test_materialization_failure_releases_capacity_without_launch(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    value.materialize.side_effect = ControlPlaneError("CONTROL_POINTER_HASH_MISMATCH", "fixture")
    assert _execute(value).status == "FAILED"
    value.worker.run_prepared.assert_not_called()
    value.orchestrator.capacity.release.assert_called_once()
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()
    value.commit.assert_not_called()


def test_page_identity_change_after_worker_rejects_commit(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    original = value.publisher.read_published_revision.return_value
    wrong = SimpleNamespace(**{**original.__dict__, "manifest_sha256": "sha256:" + "0" * 64})
    value.publisher.read_published_revision.side_effect = [original, wrong]
    result = _execute(value)
    assert result.status == "FAILED"
    assert result.error_message == "CONTROL_POINTER_MANIFEST_MISMATCH"
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_not_called()


@pytest.mark.parametrize("terminal", [JobState.SUCCEEDED, JobState.FAILED])
def test_terminal_replay_reauthorizes_without_restarting_or_rewriting(
    monkeypatch, tmp_path, terminal
):
    value = _fixture(monkeypatch, tmp_path)
    job = _execute(value)
    job.status = terminal.value  # synthetic terminal history, not a production repair
    monkeypatch.setattr(value.orchestrator, "_job_by_idempotency_key", lambda _key: job)
    monkeypatch.setattr(value.orchestrator, "_resume_pre_execution_job", lambda _job_id: terminal)
    assert _execute(value) is job
    assert job.status == terminal.value
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()
    assert value.source.call_count == 6


def test_revoked_terminal_replay_does_not_preserve_a_permission(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    job = _execute(value)
    monkeypatch.setattr(value.orchestrator, "_job_by_idempotency_key", lambda _key: job)
    value.source.side_effect = ValueError("revoked")
    with pytest.raises(ControlPlaneError, match="source authorization failed"):
        _execute(value)
    assert job.status == "SUCCEEDED"
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()
