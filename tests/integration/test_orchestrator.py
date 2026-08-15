from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter, WorkerRun
from eom_orchestrator.worker_registry import WorkerSlot
from eom_protocol import ErrorCode, WorkerInput
from sqlalchemy import Engine, select
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration


class FakeWorkerAdapter(CodexWorkerAdapter):
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.calls = 0

    def run(self, worker_input: WorkerInput, slot: WorkerSlot, staging: Path) -> WorkerRun:
        self.calls += 1
        stdout_path = staging / "worker.stdout.log"
        stderr_path = staging / "worker.stderr.log"
        stdout_path.write_text("diagnostic output", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if self.mode == "timeout":
            raise PlatformError(ErrorCode.WORKER_TIMEOUT, "worker execution timed out")

        workspace = staging / "fake-workspace"
        workspace.mkdir()
        result_path = workspace / "result.json"
        if self.mode == "malformed":
            result_path.write_text("{}", encoding="utf-8")
        else:
            result_path.write_text(
                json.dumps(
                    {
                        "protocol_version": "1.0.1",
                        "job_id": worker_input.job_id,
                        "status": "ok",
                        "message": "EOM_PLATFORM_SMOKE_TEST_OK",
                        "artifact": worker_input.artifact.model_dump(mode="json"),
                        "content": {"message": "EOM_PLATFORM_SMOKE_TEST_OK"},
                        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    }
                ),
                encoding="utf-8",
            )
        return WorkerRun(
            exit_code=0,
            result_path=result_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            unit_name="fake-unit",
        )


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


def _orchestrator_in_outer_transaction(
    engine: Engine, tmp_path: Path, adapter: FakeWorkerAdapter
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


def test_orchestrator_success_and_idempotent_submit(
    integration_engine: Engine, tmp_path: Path
) -> None:
    adapter = FakeWorkerAdapter()
    orchestrator, session, resources = _orchestrator_in_outer_transaction(
        integration_engine, tmp_path, adapter
    )
    connection, outer = resources
    try:
        job = orchestrator.submit("EOM_PLATFORM_SMOKE_TEST", "orchestrator-success")
        duplicate = orchestrator.submit("EOM_PLATFORM_SMOKE_TEST", "orchestrator-success")
        assert job.status == "SUCCEEDED"
        assert duplicate.job_id == job.job_id
        assert adapter.calls == 1
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        assert revision is not None
        assert Path(revision.nas_path, "result.json").is_file()
        events = list(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert [event.to_state for event in events] == [
            "CREATED",
            "VALIDATED",
            "QUEUED",
            "CLAIMED",
            "RUNNING",
            "VALIDATING_RESULT",
            "COMMITTING",
            "SUCCEEDED",
        ]
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("malformed", "WORKER_RESULT_INVALID"),
        ("timeout", "WORKER_TIMEOUT"),
    ],
)
def test_orchestrator_records_explicit_worker_failures(
    integration_engine: Engine,
    tmp_path: Path,
    mode: str,
    expected_code: str,
) -> None:
    adapter = FakeWorkerAdapter(mode)
    orchestrator, session, resources = _orchestrator_in_outer_transaction(
        integration_engine, tmp_path, adapter
    )
    connection, outer = resources
    try:
        job = orchestrator.submit("EOM_PLATFORM_SMOKE_TEST", f"orchestrator-{mode}")
        assert job.status == "FAILED"
        assert job.error_code == expected_code
        assert job.worker_stdout_path is not None
        event = session.scalar(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job.job_id)
            .order_by(JobEventRecord.sequence.desc())
            .limit(1)
        )
        assert event is not None
        assert event.event == "JOB_FAILED"
        assert event.data == {"error_code": expected_code}
    finally:
        session.close()
        outer.rollback()
        connection.close()
