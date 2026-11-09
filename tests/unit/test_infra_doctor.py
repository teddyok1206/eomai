from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from eom_orchestrator import database

from scripts.infra import doctor as infra_doctor

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("docker_visible", "database_ok", "expected_result"),
    [
        (False, True, "pass_with_warnings"),
        (False, False, "failed"),
        (True, True, "passed"),
    ],
    ids=["least-privilege-warning", "database-failure-not-hidden", "healthy"],
)
def test_actual_docker_and_database_checks_keep_independent_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    docker_visible: bool,
    database_ok: bool,
    expected_result: str,
) -> None:
    commands: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("docker", "compose", "version"): (0, "", ""),
        ("systemctl", "is-active", "docker"): (0, "active", ""),
        ("docker", "info"): (0, "", "") if docker_visible else (1, "", "permission denied"),
        (
            "docker",
            "compose",
            "--env-file",
            "/etc/eom/secrets/postgres.env",
            "-f",
            "/home/eom/EOM/infra/compose/compose.yml",
            "ps",
            "eom-postgres",
        ): (0, "", ""),
        (
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            "eom-postgres",
        ): (0, "healthy", ""),
        ("ss", "-lntH"): (0, "LISTEN 0 128 127.0.0.1:5432 0.0.0.0:*", ""),
    }

    def run_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = commands[tuple(arguments)]
        return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)

    executor = Mock(spec=infra_doctor.CommandExecutor)
    executor.run.side_effect = run_command
    monkeypatch.setattr("scripts.infra.doctor.shutil.which", lambda _name: "/usr/bin/docker")
    engine = MagicMock()
    if database_ok:
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.scalar_one.return_value = 1
    else:
        engine.connect.side_effect = OSError("test database unavailable")
    build_engine = Mock(return_value=engine)
    monkeypatch.setattr(database, "build_engine", build_engine)

    # Exercise the two production checks with isolated command/database adapters.
    doctor = infra_doctor.InfrastructureDoctor(privileged=False, executor=executor)
    doctor._docker()
    doctor._postgres()

    report = doctor.report
    checks = {check.name: check for check in report.checks}
    docker = checks["docker_visibility"]
    assert docker.status is (
        infra_doctor.CheckStatus.PASS if docker_visible else infra_doctor.CheckStatus.WARN
    )
    assert docker.code == (
        "DOCKER_VISIBLE" if docker_visible else "EXPECTED_LEAST_PRIVILEGE_WARNING"
    )
    assert checks["postgres_application_connectivity"].status is (
        infra_doctor.CheckStatus.PASS if database_ok else infra_doctor.CheckStatus.FAIL
    )
    assert report.passed is database_ok
    assert report.has_warnings is not docker_visible
    assert report.result == expected_result
    build_engine.assert_called_once_with()
    engine.dispose.assert_called_once_with()


def test_privileged_docker_denial_is_failure() -> None:
    check = infra_doctor.classify_docker_visibility(
        success=False,
        diagnostic="permission denied",
        privileged=True,
        daemon_active=True,
    )

    assert check.status is infra_doctor.CheckStatus.FAIL


def test_default_infrastructure_doctor_has_no_sudo_probe() -> None:
    wrapper = (REPOSITORY_ROOT / "scripts/infra/doctor.sh").read_text(encoding="utf-8")
    implementation = (REPOSITORY_ROOT / "scripts/infra/doctor.py").read_text(encoding="utf-8")

    assert "sudo -n" not in wrapper
    assert 'run(("sudo"' not in implementation
    assert 'run(("sudo",' not in implementation
