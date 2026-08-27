from __future__ import annotations

from pathlib import Path

from eom_orchestrator.settings import Settings
from eom_workflow_runner.doctor import run_workflow_doctor
from eom_workflow_runner.readiness import RuntimeReadinessReport
from eom_workflow_runner.settings import WorkflowSettings


class _ReadyRuntime:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(())


def _settings(tmp_path: Path, *, lease_seconds: int) -> WorkflowSettings:
    runner = tmp_path / f"runner-{lease_seconds}.yaml"
    runner.write_text(
        "version: 1\n"
        "poll_interval_seconds: 2\n"
        f"command_lease_seconds: {lease_seconds}\n"
        "max_commands_per_run: 100\n",
        encoding="utf-8",
    )
    actors = tmp_path / "actors.yaml"
    actors.write_text(
        "version: 1\nactors:\n"
        "  - actor_id: requester_01\n    role: requester\n    enabled: true\n"
        "  - actor_id: reviewer_01\n    role: reviewer\n    enabled: true\n"
        "  - actor_id: admin_01\n    role: admin\n    enabled: true\n",
        encoding="utf-8",
    )
    return WorkflowSettings(runner_config_path=runner, actor_config_path=actors)


def test_doctor_requires_lease_beyond_longest_fixed_worker_wall_clock(
    tmp_path: Path,
) -> None:
    checks = run_workflow_doctor(
        _settings(tmp_path, lease_seconds=7500),
        Settings(worker_timeout_seconds=1800),
        _ReadyRuntime(),
    )

    lease = next(check for check in checks if check.name == "workflow_command_lease")
    assert lease.passed
    assert lease.detail == "lease=7500s,max_worker_wall_clock=7230s"


def test_doctor_rejects_lease_equal_to_analysis_worker_wall_clock(tmp_path: Path) -> None:
    checks = run_workflow_doctor(
        _settings(tmp_path, lease_seconds=7230),
        Settings(worker_timeout_seconds=1800),
        _ReadyRuntime(),
    )

    lease = next(check for check in checks if check.name == "workflow_command_lease")
    assert not lease.passed
    assert lease.code == "WORKFLOW_COMMAND_LEASE_INVALID"
