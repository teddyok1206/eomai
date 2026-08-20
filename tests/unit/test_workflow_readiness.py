from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import eom_workflow_runner.readiness as readiness_module
import pytest
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_systemd import WorkerSystemdReadiness
from eom_workflow_runner.actor_authorization import WorkflowActorAuthorizationReadiness
from eom_workflow_runner.actor_authorization_adapters import StaticWorkflowActorAuthorizer
from eom_workflow_runner.readiness import WorkflowRuntimeReadiness
from eom_workflow_runner.settings import WorkflowSettings

ROOT = Path(__file__).resolve().parents[2]


def _group_id() -> int:
    return next((group_id for group_id in os.getgroups() if group_id != os.getgid()), os.getgid())


def _runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[WorkflowRuntimeReadiness, Path, Path]:
    worker_group = _group_id()
    runner_account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    worker_account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=worker_group)
    monkeypatch.setattr(
        "eom_workflow_runner.readiness.pwd.getpwnam",
        lambda name: runner_account if name == "eom" else worker_account,
    )
    monkeypatch.setattr(
        "eom_workflow_runner.readiness.grp.getgrnam",
        lambda _name: SimpleNamespace(gr_gid=worker_group),
    )
    monkeypatch.setattr(
        "eom_workflow_runner.readiness.os.getgrouplist",
        lambda _name, primary: [primary, worker_group],
    )
    monkeypatch.setattr(
        "eom_workflow_runner.readiness.os.getgroups",
        lambda: [worker_group],
    )

    catalog = tmp_path / "catalog"
    catalog.mkdir(mode=0o750)
    catalog.chmod(0o750)
    for fixed_name in ("content-packs", "registry", "workflow-prompts"):
        fixed_staging = catalog / fixed_name
        fixed_staging.mkdir(mode=0o750)
        fixed_staging.chmod(0o750)
    workspaces = tmp_path / "workspaces"
    homes = tmp_path / "homes"
    workspaces.mkdir()
    homes.mkdir()
    for index in range(1, 6):
        user = f"eom-cdx-{index:02d}"
        workspace = workspaces / user
        workspace.mkdir(mode=0o2770)
        os.chown(workspace, -1, worker_group)
        workspace.chmod(0o2770)
        home = homes / user
        home.mkdir(mode=0o700)
        os.chown(home, -1, worker_group)
        home.chmod(0o700)

    platform = Settings(
        worker_config=ROOT / "config/worker-slots.example.yaml",
        staging_root=tmp_path / "staging",
        workspace_root=workspaces,
        worker_home_root=homes,
        nas_artifact_root=tmp_path / "artifacts",
        codex_binary=Path(sys.executable),
    )
    workflow = WorkflowSettings(
        definition_path=ROOT / "config/workflows/generic-item-development.v1.1.yaml",
        actor_config_path=ROOT / "config/human-actors.example.yaml",
        runner_config_path=ROOT / "config/workflow-runner.example.yaml",
        prompt_root=ROOT / "content/prompt-templates/placeholders",
    )
    readiness = WorkflowRuntimeReadiness(
        workflow_settings=workflow,
        platform_settings=platform,
        catalog_settings=CatalogSettings(
            staging_root=catalog,
            nas_artifact_root=tmp_path / "artifacts",
            intake_root=tmp_path / "intake",
            placeholder_pack_source=ROOT / "content/packs/generic-placeholder/0.1.0",
        ),
        catalog_configured=True,
        actor_authorizer=StaticWorkflowActorAuthorizer(workflow.load_actors()),
        fixed_worker_codex_binary=Path(sys.executable),
        systemd_contract_inspector=lambda slot: WorkerSystemdReadiness(
            True, "READY", f"slot {slot.slot_id} contract v1"
        ),
        systemd_authorization_probe=lambda slot: WorkerSystemdReadiness(
            True, "READY", f"slot {slot.slot_id} probe passed"
        ),
    )
    return readiness, catalog, workspaces


def _codes(readiness: WorkflowRuntimeReadiness) -> set[str]:
    return set(readiness.evaluate().failed_codes)


def test_execution_readiness_passes_and_cleans_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, workspaces = _runtime(tmp_path, monkeypatch)

    report = readiness.evaluate()

    assert report.ready
    assert not list(catalog.glob(".eom-readiness-*"))
    assert not list((catalog / "content-packs").glob(".eom-readiness-*"))
    assert not list((catalog / "registry").glob(".eom-readiness-*"))
    assert not list((catalog / "workflow-prompts").glob(".eom-readiness-*"))
    assert not list(workspaces.glob("*/.eom-readiness-*"))
    actor_check = next(
        check for check in report.checks if check.name == "workflow_actor_authorization"
    )
    assert actor_check.passed


def test_execution_readiness_detects_unavailable_actor_authorization_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        readiness.actor_authorizer,
        "readiness",
        lambda: WorkflowActorAuthorizationReadiness(
            False,
            "WORKFLOW_ACTOR_IDENTITY_UNAVAILABLE",
            "identity repository unavailable",
        ),
    )

    assert "WORKFLOW_ACTOR_IDENTITY_UNAVAILABLE" in _codes(readiness)


def test_execution_readiness_detects_missing_catalog_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    readiness.catalog_configured = False

    assert "CATALOG_ADAPTER_MISSING" in _codes(readiness)


def test_execution_readiness_detects_missing_catalog_contract_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "eom_workflow_runner.readiness.load_schema",
        lambda _name: (_ for _ in ()).throw(FileNotFoundError("missing resource")),
    )

    assert "CATALOG_CONTRACT_RESOURCES_INVALID" in _codes(readiness)


def test_execution_readiness_detects_missing_fixed_worker_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    readiness.systemd_contract_inspector = lambda slot: WorkerSystemdReadiness(
        slot.slot_id != "01",
        "READY" if slot.slot_id != "01" else "WORKER_SYSTEMD_TEMPLATE_INVALID",
        f"slot {slot.slot_id}",
    )

    report = readiness.evaluate()

    assert "WORKER_SYSTEMD_TEMPLATE_INVALID" in report.failed_codes
    assert not any(
        check.name == "worker_01_systemd_authorization" and check.passed for check in report.checks
    )


def test_execution_readiness_detects_worker_systemd_authorization_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    readiness.systemd_authorization_probe = lambda slot: WorkerSystemdReadiness(
        slot.slot_id != "01",
        "READY" if slot.slot_id != "01" else "WORKER_SYSTEMD_AUTHORIZATION_DENIED",
        f"slot {slot.slot_id}",
    )

    assert "WORKER_SYSTEMD_AUTHORIZATION_DENIED" in _codes(readiness)


def test_execution_readiness_detects_unwritable_catalog_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    catalog.chmod(0o550)

    assert "CATALOG_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_unwritable_prompt_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    (catalog / "workflow-prompts").chmod(0o550)

    assert "CATALOG_PROMPT_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_missing_prompt_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    (catalog / "workflow-prompts").rmdir()

    assert "CATALOG_PROMPT_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_rejects_prompt_staging_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    prompt_staging = catalog / "workflow-prompts"
    prompt_staging.rmdir()
    prompt_staging.symlink_to(tmp_path)

    assert "CATALOG_PROMPT_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_missing_registry_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    (catalog / "registry").rmdir()

    report = readiness.evaluate()

    assert not report.ready
    assert "CATALOG_REGISTRY_STAGING_INVALID" in report.failed_codes


def test_execution_readiness_rejects_registry_staging_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    registry = catalog / "registry"
    registry.rmdir()
    registry.symlink_to(catalog / "content-packs")

    assert "CATALOG_REGISTRY_STAGING_INVALID" in _codes(readiness)


@pytest.mark.parametrize("mode", [0o550, 0o755])
def test_execution_readiness_rejects_registry_staging_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    (catalog / "registry").chmod(mode)

    assert "CATALOG_REGISTRY_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_rejects_registry_staging_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    other_group = _group_id()
    if other_group == os.getgid():
        pytest.skip("a supplementary test group is required")
    os.chown(catalog / "registry", -1, other_group)

    assert "CATALOG_REGISTRY_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_registry_probe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    original_probe = readiness_module._probe_directory

    def fail_registry_probe(path: Path, *, group_id: int | None, file_mode: int) -> None:
        if path.name == "registry":
            raise OSError("probe denied")
        original_probe(path, group_id=group_id, file_mode=file_mode)

    monkeypatch.setattr(
        "eom_workflow_runner.readiness._probe_directory",
        fail_registry_probe,
    )

    assert "CATALOG_REGISTRY_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_missing_content_pack_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, catalog, _ = _runtime(tmp_path, monkeypatch)
    (catalog / "content-packs").rmdir()

    assert "CATALOG_CONTENT_PACK_STAGING_INVALID" in _codes(readiness)


def test_execution_readiness_detects_stale_supplementary_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, _ = _runtime(tmp_path, monkeypatch)
    monkeypatch.setattr("eom_workflow_runner.readiness.os.getgroups", lambda: [])

    assert "WORKER_GROUP_MEMBERSHIP_STALE" in _codes(readiness)


def test_execution_readiness_detects_workspace_without_setgid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, _, workspaces = _runtime(tmp_path, monkeypatch)
    (workspaces / "eom-cdx-01").chmod(0o770)

    assert "WORKER_WORKSPACE_INVALID" in _codes(readiness)
