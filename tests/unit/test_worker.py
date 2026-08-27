import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.execution_materializer import MaterializedExecution
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import (
    CodexWorkerAdapter,
    PreparedWorkerWorkspace,
    WorkerRun,
    load_worker_result,
    worker_output_schema,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import FixedUnitRun, FixedUnitStatus
from eom_protocol import ArtifactSpec, ErrorCode, SmokePayload, WorkerInput
from jsonschema import Draft202012Validator

JOB_ID = "job_0123456789abcdef0123456789abcdef"


def _worker_input() -> WorkerInput:
    return WorkerInput(
        job_id=JOB_ID,
        payload=SmokePayload(message="EOM_PLATFORM_SMOKE_TEST"),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_0123456789abcdef0123456789abcdef",
            revision_id="rev_0123456789abcdef0123456789abcdef",
        ),
        submitted_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def _collected_run() -> FixedUnitRun:
    return FixedUnitRun(
        unit_name=f"eom-worker-01@{JOB_ID}.service",
        exit_code=0,
        command_stdout=b"",
        command_stderr=b"",
        status=FixedUnitStatus(
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            result="success",
            exec_main_code=0,
            exec_main_status=0,
            exec_main_started_monotonic=0,
            need_daemon_reload=False,
        ),
        active_returncode=3,
    )


def test_worker_output_schema_constrains_all_input_identifiers() -> None:
    worker_input = _worker_input()
    schema = worker_output_schema(worker_input)
    properties = schema["properties"]
    assert properties["job_id"]["const"] == worker_input.job_id
    artifact = properties["artifact"]["properties"]
    assert artifact["logical_artifact_id"]["const"] == worker_input.artifact.logical_artifact_id
    assert artifact["revision_id"]["const"] == worker_input.artifact.revision_id


def test_worker_command_has_no_caller_selected_identity_or_properties() -> None:
    settings = Settings()
    adapter = CodexWorkerAdapter(settings)
    argv = adapter._argv(
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        job_id="job_0123456789abcdef0123456789abcdef",
    )
    command = " ".join(argv)
    assert "systemd-run" not in command
    assert "--uid" not in command
    assert "--gid" not in command
    assert "--property" not in command
    assert command.endswith("start eom-worker-01@job_0123456789abcdef0123456789abcdef.service")


def test_collected_worker_success_reaches_valid_result_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_input = _worker_input()
    workspace = tmp_path / JOB_ID
    staging = tmp_path / "staging"
    workspace.mkdir()
    staging.mkdir()
    result = {
        "protocol_version": "1.0.1",
        "job_id": worker_input.job_id,
        "status": "ok",
        "message": "EOM_PLATFORM_SMOKE_TEST_OK",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "content": {"message": "EOM_PLATFORM_SMOKE_TEST_OK"},
        "completed_at": "2026-08-19T00:00:00Z",
    }
    (workspace / "result.json").write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(
        "eom_orchestrator.worker.launch_worker_unit",
        lambda *_args, **_kwargs: _collected_run(),
    )

    run = CodexWorkerAdapter(Settings())._execute(
        job_id=JOB_ID,
        workspace=workspace,
        schema_path=workspace / "worker-result.schema.json",
        prompt_path=workspace / "prompt.txt",
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        staging=staging,
    )
    parsed = load_worker_result(run.result_path, workspace)
    Draft202012Validator(worker_output_schema(worker_input)).validate(parsed)

    assert run.exit_code == 0
    assert parsed == result


def test_collected_worker_success_without_result_is_result_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / JOB_ID
    staging = tmp_path / "staging"
    workspace.mkdir()
    staging.mkdir()
    monkeypatch.setattr(
        "eom_orchestrator.worker.launch_worker_unit",
        lambda *_args, **_kwargs: _collected_run(),
    )

    run = CodexWorkerAdapter(Settings())._execute(
        job_id=JOB_ID,
        workspace=workspace,
        schema_path=workspace / "worker-result.schema.json",
        prompt_path=workspace / "prompt.txt",
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        staging=staging,
    )

    with pytest.raises(PlatformError) as captured:
        load_worker_result(run.result_path, workspace)

    assert run.exit_code == 0
    assert captured.value.code is ErrorCode.WORKER_RESULT_MISSING


def test_collected_worker_success_with_malformed_result_is_result_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / JOB_ID
    staging = tmp_path / "staging"
    workspace.mkdir()
    staging.mkdir()
    (workspace / "result.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        "eom_orchestrator.worker.launch_worker_unit",
        lambda *_args, **_kwargs: _collected_run(),
    )

    run = CodexWorkerAdapter(Settings())._execute(
        job_id=JOB_ID,
        workspace=workspace,
        schema_path=workspace / "worker-result.schema.json",
        prompt_path=workspace / "prompt.txt",
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        staging=staging,
    )

    with pytest.raises(PlatformError) as captured:
        load_worker_result(run.result_path, workspace)

    assert captured.value.code is ErrorCode.WORKER_RESULT_INVALID


def test_resolved_materialization_failure_never_starts_fixed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / JOB_ID
    workspace.mkdir()
    prepared = PreparedWorkerWorkspace(
        job_id=JOB_ID,
        workspace=workspace,
        schema_path=workspace / "worker-result.schema.json",
        prompt_path=workspace / "prompt.txt",
    )
    adapter = CodexWorkerAdapter(Settings())
    monkeypatch.setattr(adapter, "prepare_structured_workspace", lambda **_kwargs: prepared)
    started = False

    def start(**_kwargs: object) -> None:
        nonlocal started
        started = True

    monkeypatch.setattr(adapter, "run_prepared", start)

    def reject(_workspace: Path) -> MaterializedExecution:
        raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "materialization rejected")

    with pytest.raises(PlatformError, match="materialization rejected"):
        adapter.run_resolved_structured(
            job_id=JOB_ID,
            input_document={},
            output_schema={"type": "object"},
            prompt_text="prompt",
            slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
            staging=tmp_path / "staging",
            materialize=reject,
            timeout_seconds=600,
        )
    assert not started


def test_resolved_plan_timeout_reaches_prepared_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / JOB_ID
    workspace.mkdir()
    prepared = PreparedWorkerWorkspace(
        job_id=JOB_ID,
        workspace=workspace,
        schema_path=workspace / "worker-result.schema.json",
        prompt_path=workspace / "prompt.txt",
    )
    materialized = MaterializedExecution(
        plan_id="execplan_" + "1" * 32,
        plan_sha256="sha256:" + "1" * 64,
        step_key="analyze",
        model="gpt-5.6-terra",
        reasoning_effort="xhigh",
        instruction_bundle_revision_id="bundlerev_" + "1" * 32,
        instruction_manifest_sha256="sha256:" + "2" * 64,
        reference_bundle_revision_id=None,
        reference_manifest_sha256=None,
        agents_sha256="sha256:" + "3" * 64,
        invocation_sha256="sha256:" + "4" * 64,
        image_input_manifest_sha256="sha256:" + "5" * 64,
        materialized_member_count=8,
        materialized_bytes=1024,
        invocation_path=workspace / "codex-invocation.json",
    )
    adapter = CodexWorkerAdapter(Settings())
    monkeypatch.setattr(adapter, "prepare_structured_workspace", lambda **_kwargs: prepared)
    observed: list[int | None] = []

    def run_prepared(**kwargs: object) -> WorkerRun:
        timeout_seconds = kwargs.get("timeout_seconds")
        assert isinstance(timeout_seconds, int)
        observed.append(timeout_seconds)
        return WorkerRun(
            exit_code=0,
            result_path=workspace / "result.json",
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            unit_name=f"eom-worker-05@{JOB_ID}.service",
        )

    monkeypatch.setattr(adapter, "run_prepared", run_prepared)
    result = adapter.run_resolved_structured(
        job_id=JOB_ID,
        input_document={},
        output_schema={"type": "object"},
        prompt_text="prompt",
        slot=WorkerSlot(slot_id="05", linux_user="eom-cdx-05", role="support", enabled=True),
        staging=tmp_path / "staging",
        materialize=lambda _workspace: materialized,
        timeout_seconds=7200,
    )

    assert result.materialization is materialized
    assert observed == [7200]
