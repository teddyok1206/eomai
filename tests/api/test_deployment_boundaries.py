from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")


def _shell_commands(source: str) -> tuple[str, ...]:
    commands: list[str] = []
    continued = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        continued += (" " if continued else "") + line.removesuffix("\\").rstrip()
        if line.endswith("\\"):
            continue
        commands.append(continued)
        continued = ""
    return tuple(commands)


def test_service_user_bootstrap_preserves_secret_directory_boundary() -> None:
    source = _source("scripts/api/bootstrap_service_user.sh")

    assert "chmod o+x" not in source
    assert "chmod 0751" not in source
    assert "chmod 0711" not in source
    assert "root:eom:750" in source
    assert "usermod" not in source


def test_runtime_doctor_does_not_access_secret_path() -> None:
    source = _source("apps/application_api/eom_api/cli.py")

    assert "/etc/eom/secrets" not in source
    assert "secret_file_permission" not in source
    assert '"secret_environment"' in source


def test_systemd_manager_reads_secret_and_runtime_reads_service_config() -> None:
    source = _source("infra/systemd/eom-api.service")

    assert "EnvironmentFile=/etc/eom/secrets/api.env" in source
    assert "Environment=EOM_API_CONFIG=/etc/eom-api/api.yaml" in source
    assert "ReadOnlyPaths=/etc/eom-api/api.yaml" in source
    assert "ReadOnlyPaths=/etc/eom/api.yaml" not in source


def test_deploy_release_uses_only_noninteractive_sudo() -> None:
    commands = _shell_commands(_source("scripts/api/deploy_release.sh"))
    sudo_commands = [command for command in commands if re.search(r"(^|[;&|]\s*)sudo\s", command)]

    assert sudo_commands
    assert all(re.search(r"(^|[;&|]\s*)sudo\s+-n(?:\s|$)", command) for command in sudo_commands)
    assert not any("sudo -v" in command for command in commands)


def test_privileged_metadata_verifier_is_root_only_and_secret_safe() -> None:
    source = _source("scripts/api/verify_deployment_metadata.sh")

    assert '"$(id -u)" -ne 0' in source
    assert "EOM_API_DATABASE_URL" in source
    assert "EOM_API_TOKEN_HASH_KEY" in source
    assert "EOM_API_FINGERPRINT_KEY" in source
    assert "root:eom:750" in source
    assert "cat " not in source
    assert not re.search(
        r"printf[^\n]*EOM_API_(?:DATABASE_URL|TOKEN_HASH_KEY|FINGERPRINT_KEY)", source
    )


def test_privileged_metadata_verifier_rejects_secret_directory_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_id = tmp_path / "id"
    fake_id.write_text("#!/bin/sh\nprintf '0\\n'\n", encoding="ascii")
    fake_id.chmod(0o700)
    fake_stat = tmp_path / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf 'root:eom:751\\n'\n", encoding="ascii")
    fake_stat.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    completed = subprocess.run(
        ("bash", str(REPOSITORY_ROOT / "scripts/api/verify_deployment_metadata.sh")),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "metadata mismatch" in completed.stderr
    assert "EOM_API_" not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/api/bootstrap_service_user.sh",
        "scripts/api/deploy_release.sh",
        "scripts/api/verify_deployment_metadata.sh",
        "scripts/api/verify_runtime_isolation.sh",
    ],
)
def test_deployment_shell_has_valid_syntax(relative: str) -> None:
    completed = subprocess.run(
        ("bash", "-n", str(REPOSITORY_ROOT / relative)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
