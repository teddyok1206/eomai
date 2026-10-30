from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_service.inference_transfer_catalog_adapter import (
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.orchestrator import RETRYABLE_CONTROL_ADMISSION_ERRORS
from eom_orchestrator.preset_model_validation_processor import PresetModelValidationProcessor
from eom_orchestrator.settings import Settings, WorkerConfigSource
from eom_workflow_runner import cli
from eom_workflow_runner.actor_authorization import (
    CompositeWorkflowActorAuthorizer,
    WorkflowActorAuthorizer,
)
from eom_workflow_runner.catalog_port import WorkflowCatalogPort
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.engine import PlatformRoleJobExecutor, WorkflowRunner
from eom_workflow_runner.inference_transfer_executor import PlatformInferenceTransferExecutor
from eom_workflow_runner.local_embedding_admission import LocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowExecutionReadiness,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.reference_query_admission import ReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
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


def test_temporarily_unavailable_slot_keeps_the_platform_job_queued() -> None:
    assert (
        frozenset(
            {
                "CONTROL_CAPACITY_EXHAUSTED",
                "CONTROL_KNOWLEDGE_CAPACITY_EXHAUSTED",
                "CONTROL_ELIGIBLE_SLOT_UNAVAILABLE",
            }
        )
        == RETRYABLE_CONTROL_ADMISSION_ERRORS
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
    assert isinstance(runtime.runner.inference_transfer_executor, PlatformInferenceTransferExecutor)
    assert (
        runtime.runner.inference_transfer_executor.orchestrator
        is runtime.runner.executor.orchestrator
    )
    assert (
        runtime.runner.inference_transfer_executor.actor_authorizer
        is runtime.runner.actor_authorizer
    )
    assert isinstance(
        runtime.runner.inference_transfer_executor.source, CatalogInferenceTransferSourceAdapter
    )
    assert runtime.runner.readiness is runtime.readiness
    assert isinstance(runtime.runner.actor_authorizer, CompositeWorkflowActorAuthorizer)
    assert runtime.runner.available_roles == frozenset(
        {"authoring", "review", "image", "item_management", "support"}
    )
    assert runtime.runner.executor.orchestrator.settings == _platform_settings(tmp_path)
    assert runtime.runner.capacity_reconciler is runtime.runner.executor.orchestrator.capacity
    assert runtime.runner.local_embedding_owner is None
    assert runtime.runner.local_embedding_executor is None
    assert runtime.runner.reference_query_owner is None
    assert runtime.runner.reference_query_executor is None
    assert isinstance(runtime.runner.preset_validator, PresetModelValidationProcessor)
    assert runtime.runner.preset_validator.settings == runtime.platform_settings
    engine.dispose()


@pytest.mark.parametrize("owner_only", [False, True])
def test_native_composition_requires_paired_explicit_injection(owner_only: bool) -> None:
    owner = cast(LocalEmbeddingOwnerAdmission, object()) if owner_only else None
    executor = None if owner_only else cast(LocalEmbeddingNativeExecutor, object())
    with pytest.raises(ValueError, match="supplied together"):
        build_workflow_runtime(local_embedding_owner=owner, local_embedding_executor=executor)


@pytest.mark.parametrize("owner_only", [False, True])
def test_query_composition_requires_paired_explicit_injection_before_runtime_io(
    owner_only: bool,
) -> None:
    owner = cast(ReferenceQueryOwnerAdmission, object()) if owner_only else None
    executor = None if owner_only else cast(ReferenceQueryNativeExecutor, object())
    with pytest.raises(ValueError, match="QUERY owner and executor must be supplied together"):
        build_workflow_runtime(reference_query_owner=owner, reference_query_executor=executor)


@pytest.mark.parametrize("with_validation", [False, True])
def test_serve_reconciles_capacity_before_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_validation: bool
) -> None:
    engine = create_engine("sqlite://")
    observed: list[str] = []

    class Reconciler:
        def reconcile_expired(self, *, observed_at: datetime) -> tuple[object, ...]:
            del observed_at
            observed.append("capacity")
            return ()

    class Processor:
        def maintain_once(self) -> None:
            observed.append("maintenance")

        def process_once(self) -> None:
            observed.append("control")

        def process_observation_once(self) -> None:
            raise AssertionError("role consumer used maintenance-only observation scope")

    class Validator:
        def process_once(self) -> None:
            observed.append("validation")

    runner = WorkflowRunner(
        engine,
        _workflow_settings(tmp_path),
        catalog=cast(WorkflowCatalogPort, object()),
        actor_authorizer=cast(WorkflowActorAuthorizer, object()),
        readiness=cast(WorkflowExecutionReadiness, object()),
        available_roles=frozenset({"authoring"}),
        control_processor=Processor(),
        preset_validator=Validator() if with_validation else None,
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

    assert observed == [
        "capacity",
        "maintenance",
        "control",
        *(["validation"] if with_validation else []),
        "workflow",
        "sleep",
    ]
    engine.dispose()


def test_maintenance_service_only_claims_read_observations_not_model_or_state_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine("sqlite://")
    observed: list[str] = []

    class Reconciler:
        def reconcile_expired(self, *, observed_at: datetime) -> tuple[object, ...]:
            del observed_at
            observed.append("capacity")
            return ()

    class Processor:
        def maintain_once(self) -> None:
            observed.append("maintenance")

        def process_once(self) -> None:
            raise AssertionError("maintenance service claimed a control command")

        def process_observation_once(self) -> None:
            observed.append("usage-observation")

    class Validator:
        def process_once(self) -> None:
            raise AssertionError("maintenance service claimed a preset validation")

    runner = WorkflowRunner(
        engine,
        _workflow_settings(tmp_path),
        catalog=cast(WorkflowCatalogPort, object()),
        actor_authorizer=cast(WorkflowActorAuthorizer, object()),
        readiness=cast(WorkflowExecutionReadiness, object()),
        available_roles=frozenset({"authoring"}),
        control_processor=Processor(),
        preset_validator=Validator(),
        capacity_reconciler=Reconciler(),
    )

    def forbidden_claim(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("maintenance service claimed an executable command")

    monkeypatch.setattr(runner, "run_once", forbidden_claim)

    def stop(_seconds: float) -> None:
        observed.append("sleep")
        raise RuntimeError("stop-loop")

    monkeypatch.setattr("eom_workflow_runner.engine.time.sleep", stop)
    with pytest.raises(RuntimeError, match="stop-loop"):
        runner.serve_maintenance()

    assert observed == ["usage-observation", "capacity", "maintenance", "sleep"]
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
    monkeypatch.setattr(Settings, "from_environment", lambda: settings)

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
