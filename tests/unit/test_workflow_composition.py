from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.settings import Settings, WorkerConfigSource
from eom_workflow_runner import cli
from eom_workflow_runner.actor_authorization import (
    CompositeWorkflowActorAuthorizer,
    WorkflowActorAuthorizer,
)
from eom_workflow_runner.catalog_port import WorkflowCatalogPort
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.engine import PlatformRoleJobExecutor, WorkflowRunner
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowExecutionReadiness,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.settings import WorkflowSettings
from sqlalchemy import create_engine


def _platform_settings(tmp_path: Path) -> Settings:
    return Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=tmp_path / "staging",
        workspace_root=tmp_path / "workspaces",
        worker_home_root=tmp_path / "homes",
        nas_artifact_root=tmp_path / "artifacts",
        codex_binary=Path("/usr/local/bin/codex"),
    )


def _workflow_settings(tmp_path: Path) -> WorkflowSettings:
    actors = tmp_path / "human-actors.yaml"
    runner = tmp_path / "workflow-runner.yaml"
    actors.write_bytes(Path("config/human-actors.example.yaml").resolve().read_bytes())
    runner.write_bytes(Path("config/workflow-runner.example.yaml").resolve().read_bytes())
    return WorkflowSettings(
        definition_path=Path("config/workflows/generic-item-development.v1.2.yaml").resolve(),
        actor_config_path=actors,
        runner_config_path=runner,
        prompt_root=Path("content/prompt-templates/placeholders").resolve(),
    )


def test_production_composition_supplies_catalog_adapter(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    runtime = build_workflow_runtime(
        engine=engine,
        workflow_settings=_workflow_settings(tmp_path),
        platform_settings=_platform_settings(tmp_path),
        catalog_settings=CatalogSettings(
            staging_root=tmp_path / "catalog",
            nas_artifact_root=tmp_path / "artifacts",
            intake_root=tmp_path / "intake",
            placeholder_pack_source=Path("content/packs/generic-placeholder/0.1.0").resolve(),
        ),
    )

    assert isinstance(runtime.runner.catalog, WorkflowCatalogService)
    assert runtime.catalog is runtime.runner.catalog
    assert isinstance(runtime.runner.executor, PlatformRoleJobExecutor)
    assert runtime.runner.readiness is runtime.readiness
    assert isinstance(runtime.runner.actor_authorizer, CompositeWorkflowActorAuthorizer)
    assert runtime.runner.available_roles == frozenset(
        {"authoring", "review", "image", "item_management", "support"}
    )
    assert runtime.runner.executor.orchestrator.settings == _platform_settings(tmp_path)
    assert runtime.runner.capacity_reconciler is runtime.runner.executor.orchestrator.capacity
    engine.dispose()


def test_serve_reconciles_capacity_before_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine("sqlite://")
    observed: list[str] = []

    class Reconciler:
        def reconcile_expired(self, *, observed_at: datetime) -> tuple[object, ...]:
            del observed_at
            observed.append("capacity")
            return ()

    runner = WorkflowRunner(
        engine,
        _workflow_settings(tmp_path),
        catalog=cast(WorkflowCatalogPort, object()),
        actor_authorizer=cast(WorkflowActorAuthorizer, object()),
        readiness=cast(WorkflowExecutionReadiness, object()),
        available_roles=frozenset({"authoring"}),
        capacity_reconciler=Reconciler(),
    )

    def no_work() -> None:
        observed.append("workflow")

    monkeypatch.setattr(runner, "run_once", no_work)

    def stop(_seconds: float) -> None:
        observed.append("sleep")
        raise RuntimeError("stop-loop")

    monkeypatch.setattr("eom_workflow_runner.engine.time.sleep", stop)
    with pytest.raises(RuntimeError, match="stop-loop"):
        runner.serve()

    assert observed == ["capacity", "workflow", "sleep"]
    engine.dispose()


def test_runner_rejects_missing_worker_roles() -> None:
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="worker roles are required"):
        WorkflowRunner(
            engine,
            catalog=cast(WorkflowCatalogPort, object()),
            actor_authorizer=cast(WorkflowActorAuthorizer, object()),
            readiness=cast(WorkflowExecutionReadiness, object()),
            available_roles=frozenset(),
        )
    engine.dispose()


def test_runner_rejects_missing_mandatory_catalog_adapter() -> None:
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="catalog adapter is required"):
        WorkflowRunner(
            engine,
            catalog=cast(WorkflowCatalogPort, None),
            actor_authorizer=cast(WorkflowActorAuthorizer, object()),
            readiness=cast(WorkflowExecutionReadiness, object()),
            available_roles=frozenset({"authoring"}),
        )
    engine.dispose()


def test_runner_rejects_missing_actor_authorizer() -> None:
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="actor authorizer is required"):
        WorkflowRunner(
            engine,
            catalog=cast(WorkflowCatalogPort, object()),
            actor_authorizer=cast(WorkflowActorAuthorizer, None),
            readiness=cast(WorkflowExecutionReadiness, object()),
            available_roles=frozenset({"authoring"}),
        )
    engine.dispose()


def test_cli_uses_composition_root(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeEngine:
        def dispose(self) -> None:
            calls.append("dispose")

    class FakeRunner:
        def run_once(self, workflow_id: str | None) -> None:
            calls.append(f"run-once:{workflow_id}")
            return None

    runtime = SimpleNamespace(engine=FakeEngine(), runner=FakeRunner())
    monkeypatch.setattr(cli, "build_workflow_runtime", lambda: runtime)

    assert cli.main(["run-once", "--workflow-id", "workflow_test"]) == 2
    assert calls == ["run-once:workflow_test", "dispose"]


def test_cli_reports_runtime_not_ready_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            return None

    class FakeRunner:
        def run_once(self, workflow_id: str | None) -> None:
            del workflow_id
            report = RuntimeReadinessReport(
                (
                    RuntimeReadinessCheck(
                        "catalog_staging",
                        ReadinessStatus.FAIL,
                        "CATALOG_STAGING_UNWRITABLE",
                        "permission denied",
                    ),
                )
            )
            raise WorkflowRuntimeNotReady(report)

    runtime = SimpleNamespace(engine=FakeEngine(), runner=FakeRunner())
    monkeypatch.setattr(cli, "build_workflow_runtime", lambda: runtime)

    assert cli.main(["run-once"]) == 3
    output = capsys.readouterr().out
    assert "WORKFLOW_RUNTIME_NOT_READY" in output
    assert "CATALOG_STAGING_UNWRITABLE" in output


def test_doctor_reports_missing_worker_configuration_before_composition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        worker_config=tmp_path / "missing-worker-slots.yaml",
        worker_config_source=WorkerConfigSource.EXPLICIT,
    )
    monkeypatch.setattr(cli.Settings, "from_environment", lambda: settings)

    def unexpected(**_kwargs: object) -> object:
        raise AssertionError("composition must not run with invalid worker configuration")

    monkeypatch.setattr(cli, "build_workflow_runtime", unexpected)

    assert cli.main(["doctor"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "passed": False,
        "checks": [
            {
                "name": "orchestrator_runtime_configuration",
                "status": "FAIL",
                "code": "WORKER_CONFIGURATION_INVALID",
                "detail": "PlatformError",
                "passed": False,
            }
        ],
    }
