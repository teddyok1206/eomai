from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "infra/systemd/eom-workflow-runner.service"
DEPLOY = ROOT / "scripts/workflow/deploy_runner_service.sh"


def _directives(source: str, name: str) -> set[str]:
    prefix = f"{name}="
    return {line.removeprefix(prefix) for line in source.splitlines() if line.startswith(prefix)}


def test_workflow_runner_service_fixes_identity_command_and_group_contract() -> None:
    source = UNIT.read_text(encoding="utf-8")

    assert "User=eom" in source
    assert "Group=eom" in source
    assert "SupplementaryGroups=eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05" in source
    assert "ExecStart=/srv/eom/conda/envs/eom-api/bin/eom-workflow-runner serve" in source
    assert "EOM_POSTGRES_ENV=/etc/eom/secrets/postgres.env" in source
    assert "UMask=0007" in source


def test_workflow_runner_service_is_narrow_but_can_materialize_worker_handoffs() -> None:
    source = UNIT.read_text(encoding="utf-8")

    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectKernelLogs=true",
        "ProtectControlGroups=true",
        "ProtectClock=true",
        "ProtectHostname=true",
        "LockPersonality=true",
        "RestrictRealtime=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "IPAddressDeny=any",
        "IPAddressAllow=localhost",
    ):
        assert directive in source
    assert "RestrictSUIDSGID=false" in source
    assert "RestrictSUIDSGID=true" not in source
    assert _directives(source, "ReadWritePaths") == {
        "/srv/eom/staging",
        "/srv/eom/workspaces",
        "/mnt/nas/eom/artifacts",
        "/var/lib/eom-workflow-runner",
    }
    inaccessible = _directives(source, "InaccessiblePaths")
    assert "/home/eom/EOM" in inaccessible
    assert "/home/eom/EOMIS" in inaccessible
    assert "/var/run/docker.sock" in inaccessible
    assert "/etc/eom/secrets/api.env" in inaccessible
    assert all(
        f"-/srv/eom/worker-homes/eom-cdx-{slot}/.codex" in inaccessible
        for slot in ("01", "02", "03", "04", "05")
    )


def test_workflow_runner_service_reads_only_its_required_operator_contracts() -> None:
    source = UNIT.read_text(encoding="utf-8")
    read_only = _directives(source, "ReadOnlyPaths")

    assert "/etc/eom/secrets/postgres.env" in read_only
    assert "/etc/eom/worker-slots.yaml" in read_only
    assert "/etc/eom/human-actors.yaml" in read_only
    assert "/etc/eom/workflow-runner.yaml" in read_only
    assert "/etc/eom/workflows" in read_only
    assert "/etc/eom/workflow-prompts" in read_only
    assert "EnvironmentFile=/etc/eom/secrets/api.env" not in source
    assert "EnvironmentFile=/etc/eom/secrets/catalog-manager.env" not in source


def test_workflow_runner_deployer_is_commit_pinned_and_noninteractive() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    assert '[[ "$(id -u)" == "0" ]]' in source
    assert 'git -C "${REPOSITORY_ROOT}" rev-parse HEAD' in source
    assert 'git -C "${REPOSITORY_ROOT}" status --porcelain' in source
    assert 'systemd-analyze verify "${UNIT_SOURCE}"' in source
    assert 'install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"' in source
    assert 'systemctl enable "${SERVICE}"' in source
    assert 'systemctl start "${SERVICE}"' in source
    assert "systemctl restart" not in source
    assert "sudo" not in source
    assert "pip install" not in source
    assert "conda install" not in source


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze unavailable")
def test_workflow_runner_unit_verifies_without_diagnostics() -> None:
    completed = subprocess.run(
        ["systemd-analyze", "verify", str(UNIT)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
