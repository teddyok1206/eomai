from __future__ import annotations

from pathlib import Path

import pytest
from eom_orchestrator.doctor import runtime_configuration_check, runtime_environment_check
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.live_preflight import run_live_worker_preflight
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import (
    DEFAULT_WORKER_CONFIG,
    Settings,
    SettingsError,
    WorkerConfigSource,
)
from eom_orchestrator.worker_registry import WorkerRegistry
from eom_orchestrator.worker_systemd import WorkerSystemdReadiness

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_WORKER_CONFIG = ROOT / "config/worker-slots.example.yaml"
PACKAGE_ROOT = ROOT / "services/orchestrator"


def _worker_config(tmp_path: Path, *, content: str | None = None) -> Path:
    path = tmp_path / "worker-slots.yaml"
    path.write_text(
        content if content is not None else CANONICAL_WORKER_CONFIG.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _settings(tmp_path: Path, config: Path) -> Settings:
    staging = tmp_path / "staging"
    workspace = tmp_path / "workspaces" / "eom-cdx-01"
    staging.mkdir(parents=True)
    workspace.mkdir(parents=True)
    codex = tmp_path / "codex"
    codex.write_text("placeholder", encoding="utf-8")
    codex.chmod(0o700)
    return Settings(
        worker_config=config,
        staging_root=staging,
        workspace_root=workspace.parent,
        worker_home_root=tmp_path / "homes",
        nas_artifact_root=tmp_path / "artifacts",
        codex_binary=codex,
        worker_config_source=WorkerConfigSource.EXPLICIT,
    )


def _ready(_slot: object) -> WorkerSystemdReadiness:
    return WorkerSystemdReadiness(True, "READY", "test boundary")


def test_default_worker_configuration_is_operator_owned_and_cwd_independent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EOM_WORKER_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_environment()

    assert settings.worker_config == DEFAULT_WORKER_CONFIG
    assert settings.worker_config == Path("/etc/eom/worker-slots.yaml")
    assert settings.worker_config_source is WorkerConfigSource.OPERATOR_DEFAULT


def test_explicit_absolute_worker_configuration_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _worker_config(tmp_path)
    monkeypatch.setenv("EOM_WORKER_CONFIG", str(config))

    settings = Settings.from_environment()
    resolved = resolve_worker_configuration(settings)

    assert settings.worker_config_source is WorkerConfigSource.ENVIRONMENT
    assert resolved.live_worker.slot_id == "01"
    assert resolved.live_worker.linux_user == "eom-cdx-01"
    assert resolved.registry.global_codex_concurrency == 3


def test_relative_worker_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EOM_WORKER_CONFIG", "config/worker-slots.example.yaml")
    with pytest.raises(SettingsError, match="absolute"):
        Settings.from_environment()


@pytest.mark.parametrize(
    "content",
    [
        "not: [valid",
        "version: 2\nlimits: {global_codex_concurrency: 1, gpu_concurrency: 1}\nslots: []\n",
        """version: 1
limits: {global_codex_concurrency: 1, gpu_concurrency: 2}
slots:
  - {slot_id: "01", linux_user: eom-cdx-01, role: authoring, enabled: true}
""",
        """version: 1
limits: {global_codex_concurrency: 1, gpu_concurrency: 1}
slots:
  - {slot_id: "01", linux_user: eom-cdx-01, role: authoring, enabled: true, executable: /bin/sh}
""",
        """version: 1
limits: {global_codex_concurrency: 1, gpu_concurrency: 1}
slots:
  - {slot_id: "06", linux_user: eom-cdx-06, role: authoring, enabled: true}
""",
    ],
)
def test_malformed_or_injected_worker_configuration_is_rejected(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(PlatformError):
        WorkerRegistry.load(_worker_config(tmp_path, content=content))


def test_worker_configuration_rejects_missing_relative_and_symlink_paths(tmp_path: Path) -> None:
    with pytest.raises(PlatformError):
        WorkerRegistry.load(tmp_path / "missing.yaml")
    with pytest.raises(PlatformError):
        WorkerRegistry.load(Path("worker-slots.yaml"))
    target = _worker_config(tmp_path)
    linked = tmp_path / "linked.yaml"
    linked.symlink_to(target)
    with pytest.raises(PlatformError):
        WorkerRegistry.load(linked)


def test_runtime_configuration_doctor_reports_valid_missing_and_malformed(tmp_path: Path) -> None:
    valid = runtime_configuration_check(_settings(tmp_path / "valid", _worker_config(tmp_path)))
    missing_settings = Settings(
        worker_config=tmp_path / "missing.yaml",
        worker_config_source=WorkerConfigSource.EXPLICIT,
    )
    malformed_path = tmp_path / "malformed.yaml"
    malformed_path.write_text("version: [", encoding="utf-8")
    malformed_settings = Settings(
        worker_config=malformed_path,
        worker_config_source=WorkerConfigSource.EXPLICIT,
    )

    assert valid.passed
    assert not runtime_configuration_check(missing_settings).passed
    assert not runtime_configuration_check(malformed_settings).passed


def test_runtime_environment_doctor_uses_the_canonical_api_environment() -> None:
    canonical = runtime_environment_check(Path("/srv/eom/conda/envs/eom-api"))
    retired = runtime_environment_check(Path("/srv/eom/conda/envs/eom-core"))

    assert canonical.name == "eom_api_environment"
    assert canonical.passed
    assert not retired.passed


def test_live_preflight_passes_without_job_or_codex_invocation(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    settings = _settings(tmp_path, config)

    report = run_live_worker_preflight(
        settings,
        package_roots=(PACKAGE_ROOT,),
        systemd_contract=_ready,
        authorization_probe=_ready,
    )

    assert report.ready
    assert {check.name for check in report.checks} == {
        "orchestrator_installed_package",
        "orchestrator_runtime_configuration",
        "live_worker_target",
        "orchestrator_staging",
        "live_worker_workspace",
        "codex_binary",
        "result_protocol_schemas",
        "live_worker_systemd_template",
        "live_worker_systemd_authorization",
    }
    assert not list(settings.staging_root.glob(".eom-live-preflight-*"))


def test_live_preflight_configuration_failure_stops_before_systemd_boundary(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def unexpected(_slot: object) -> WorkerSystemdReadiness:
        calls.append("systemd")
        return _ready(_slot)

    report = run_live_worker_preflight(
        Settings(
            worker_config=tmp_path / "missing.yaml",
            worker_config_source=WorkerConfigSource.EXPLICIT,
        ),
        package_roots=(PACKAGE_ROOT,),
        systemd_contract=unexpected,
        authorization_probe=unexpected,
    )

    assert not report.ready
    assert report.failed_codes == ("WORKER_CONFIGURATION_INVALID",)
    assert calls == []


def test_orchestrator_settings_have_no_repository_or_install_prefix_inference() -> None:
    source = (PACKAGE_ROOT / "eom_orchestrator/settings.py").read_text(encoding="utf-8")
    assert "parents[" not in source
    assert "worker-slots.example.yaml" not in source
    assert "REPOSITORY_ROOT" not in source
    assert "/home/eom/EOM" not in source
    assert "sys.prefix" not in source


def test_live_harness_preflights_before_the_usage_consuming_submission() -> None:
    source = (ROOT / "tests/e2e/test_codex_live.py").read_text(encoding="utf-8")
    preflight = source.index("preflight = run_live_worker_preflight(settings)")
    readiness_gate = source.index("assert preflight.ready")
    submission = source.index('.submit("EOM_PLATFORM_SMOKE_TEST")')
    assert preflight < readiness_gate < submission
    assert "Orchestrator(engine, settings)" in source
