from __future__ import annotations

from pathlib import Path

from scripts.infra import doctor as infra_doctor

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_docker_denied_and_database_healthy_is_least_privilege_warning() -> None:
    docker = infra_doctor.classify_docker_visibility(
        success=False,
        diagnostic="permission denied while connecting to Docker socket",
        privileged=False,
        daemon_active=True,
    )

    report = infra_doctor.summarize_docker_and_database(docker, database_ok=True)

    assert docker.status is infra_doctor.CheckStatus.WARN
    assert docker.code == "EXPECTED_LEAST_PRIVILEGE_WARNING"
    assert report.passed
    assert report.has_warnings
    assert report.result == "pass_with_warnings"


def test_docker_denied_does_not_hide_database_failure() -> None:
    docker = infra_doctor.classify_docker_visibility(
        success=False,
        diagnostic="permission denied",
        privileged=False,
        daemon_active=True,
    )

    report = infra_doctor.summarize_docker_and_database(docker, database_ok=False)

    assert not report.passed
    assert report.result == "failed"


def test_visible_docker_and_healthy_database_pass_without_warning() -> None:
    docker = infra_doctor.classify_docker_visibility(
        success=True,
        diagnostic="",
        privileged=False,
        daemon_active=True,
    )

    report = infra_doctor.summarize_docker_and_database(docker, database_ok=True)

    assert report.passed
    assert not report.has_warnings
    assert report.result == "passed"


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
