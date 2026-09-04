from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter, WorkerRun
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow.models import ArtifactPointer, WorkflowRequest
from sqlalchemy import Engine
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

OUTPUTS: dict[str, dict[str, object]] = {
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


class FakeStructuredAdapter(CodexWorkerAdapter):
    def __init__(self, *, lose_runner_after_result: bool = False) -> None:
        self.calls: list[str] = []
        self.lose_runner_after_result = lose_runner_after_result
        self.recovery_calls = 0
        self.completed_run: WorkerRun | None = None

    def run_structured(
        self,
        *,
        job_id: str,
        input_document: dict[str, object],
        output_schema: dict[str, object],
        prompt_text: str,
        slot: WorkerSlot,
        staging: Path,
    ) -> WorkerRun:
        del output_schema, prompt_text
        role = input_document["role"]
        assert isinstance(role, str)
        self.calls.append(role)
        workspace = staging / "fake-workspace"
        workspace.mkdir()
        result_path = workspace / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "protocol_version": "workflow-role/1.0.1",
                    "job_id": job_id,
                    "workflow_id": input_document["workflow_id"],
                    "step_run_id": input_document["step_run_id"],
                    "role": role,
                    "status": "ok",
                    "artifact": input_document["artifact"],
                    "output": OUTPUTS[role],
                    "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            ),
            encoding="utf-8",
        )
        stdout_path = staging / "worker.stdout.log"
        stderr_path = staging / "worker.stderr.log"
        stdout_path.write_text("bounded diagnostic", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        run = WorkerRun(0, result_path, stdout_path, stderr_path, "fake-structured-unit")
        self.completed_run = run
        if self.lose_runner_after_result:
            self.lose_runner_after_result = False
            raise SimulatedRunnerLoss
        return run

    def recover_completed_structured(
        self,
        *,
        job_id: str,
        slot: WorkerSlot,
        staging: Path,
    ) -> WorkerRun | None:
        del job_id, slot, staging
        self.recovery_calls += 1
        return self.completed_run


class SimulatedRunnerLoss(BaseException):
    """Model process loss, which bypasses the in-process failure handler."""


def _settings(tmp_path: Path) -> Settings:
    staging = tmp_path / "staging"
    staging.mkdir()
    nas = tmp_path / "nas"
    nas.mkdir()
    return Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=staging,
        workspace_root=tmp_path / "workspaces",
        worker_home_root=tmp_path / "homes",
        nas_artifact_root=nas,
        codex_binary=Path("/usr/local/bin/codex"),
        worker_timeout_seconds=10,
    )


def _orchestrator(
    engine: Engine, tmp_path: Path, adapter: FakeStructuredAdapter
) -> tuple[Orchestrator, Session, tuple[Connection, RootTransaction]]:
    connection = engine.connect()
    outer = connection.begin()
    orchestrator = Orchestrator(engine, _settings(tmp_path), adapter)
    orchestrator.sessions = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    return orchestrator, Session(bind=connection), (connection, outer)


@pytest.mark.parametrize(
    ("role", "schema_id", "expected_slot"),
    [
        ("authoring", "authoring-result@1.0", "01"),
        ("image", "image-result@1.0", "03"),
        ("review", "review-result@1.0", "02"),
        ("item_management", "registration-result@1.0", "04"),
    ],
)
def test_workflow_role_uses_existing_platform_job_and_artifact_path(
    integration_engine: Engine,
    tmp_path: Path,
    role: str,
    schema_id: str,
    expected_slot: str,
) -> None:
    adapter = FakeStructuredAdapter()
    orchestrator, session, resources = _orchestrator(integration_engine, tmp_path, adapter)
    connection, outer = resources
    try:
        key = f"workflow-bridge-{role}"
        pre_execution_jobs: list[str] = []
        upstream: tuple[ArtifactPointer, ...] = ()
        if role != "authoring":
            upstream = (
                ArtifactPointer(
                    step_key="authoring",
                    attempt=1,
                    job_id="job_0123456789abcdef0123456789abcdef",
                    logical_artifact_id="artifact_0123456789abcdef0123456789abcdef",
                    revision_id="rev_0123456789abcdef0123456789abcdef",
                    content_hash="sha256:" + "a" * 64,
                    result_schema="authoring-result@1.0",
                ),
            )

        def submit() -> JobRecord:
            def bind_before_execution(job_id: str) -> None:
                queued = session.get(JobRecord, job_id)
                assert queued is not None
                session.refresh(queued)
                assert queued.status == "QUEUED"
                pre_execution_jobs.append(job_id)

            return orchestrator.submit_workflow_role(
                workflow_id="workflow_0123456789abcdef0123456789abcdef",
                step_run_id="steprun_0123456789abcdef0123456789abcdef",
                step_key=role,
                attempt=1,
                role=role,
                request=WorkflowRequest(
                    request_name="PLACEHOLDER_REQUEST",
                    image_mode="required",
                ),
                upstream_artifacts=upstream,
                result_schema=schema_id,
                idempotency_key=key,
                prompt_path=Path(
                    "content/prompt-templates/placeholders/"
                    + ("registration" if role == "item_management" else role)
                    + ".txt"
                ),
                before_execute=bind_before_execution,
            )

        job = submit()
        duplicate = submit()
        assert job.status == "SUCCEEDED"
        assert duplicate.job_id == job.job_id
        assert job.worker_slot_id == expected_slot
        assert pre_execution_jobs == [job.job_id]
        assert adapter.calls == [role]
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        assert revision is not None
        assert revision.result["role"] == role
        assert Path(revision.nas_path, "result.json").is_file()
    finally:
        session.close()
        outer.rollback()
        connection.close()


def test_workflow_role_recovers_completed_worker_after_runner_loss(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    adapter = FakeStructuredAdapter(lose_runner_after_result=True)
    orchestrator, session, resources = _orchestrator(integration_engine, tmp_path, adapter)
    connection, outer = resources
    workflow_id = "workflow_0123456789abcdef0123456789abcdef"
    step_run_id = "steprun_0123456789abcdef0123456789abcdef"

    def submit() -> JobRecord:
        return orchestrator.submit_workflow_role(
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            step_key="authoring",
            attempt=1,
            role="authoring",
            request=WorkflowRequest(
                request_name="PLACEHOLDER_REQUEST",
                image_mode="required",
            ),
            upstream_artifacts=(),
            result_schema="authoring-result@1.0",
            idempotency_key="workflow-bridge-recover-completed",
            prompt_path=Path("content/prompt-templates/placeholders/authoring.txt"),
        )

    try:
        with pytest.raises(SimulatedRunnerLoss):
            submit()

        running = (
            session.query(JobRecord)
            .filter_by(idempotency_key="workflow-bridge-recover-completed")
            .one()
        )
        session.refresh(running)
        assert running.status == "RUNNING"

        recovered = submit()
        duplicate = submit()

        assert recovered.status == "SUCCEEDED"
        assert duplicate.job_id == recovered.job_id
        assert adapter.calls == ["authoring"]
        assert adapter.recovery_calls == 1
        revision = session.get(ArtifactRevisionRecord, recovered.revision_id)
        assert revision is not None
        assert Path(revision.nas_path, "result.json").is_file()
    finally:
        session.close()
        outer.rollback()
        connection.close()
