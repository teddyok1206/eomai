from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOYER = ROOT / "scripts" / "infra" / "deploy_service_identities.sh"


def test_manager_units_use_dedicated_identities() -> None:
    expectations = {
        "eom-workflow-runner.service": (
            "User=eom-workflow-runner",
            "SupplementaryGroups=eom-artifact-committers eom-cdx-01",
        ),
        "eom-catalog-application-runner.service": (
            "User=eom-catalog-manager",
            "SupplementaryGroups=eom eom-artifact-committers",
        ),
        "eom-hwpx-application-runner.service": (
            "User=eom-hwpx-manager",
            "SupplementaryGroups=eom eom-artifact-committers eom-hwpx",
        ),
    }
    for filename, required in expectations.items():
        source = (ROOT / "infra" / "systemd" / filename).read_text(encoding="utf-8")
        assert all(value in source for value in required)
        assert "User=eom\n" not in source


def test_identity_deployer_keeps_artifact_and_polkit_boundaries_explicit() -> None:
    source = DEPLOYER.read_text(encoding="utf-8")

    assert "eom-artifact-committers" in source
    assert 'chmod 02770 "${ARTIFACT_ROOT}"' in source
    assert "sudo docker lxd adm" in source
    assert "a fixed child unit is active" in source
    assert "POLKIT_CROSS_START=DENIED" in source
    assert "pip install" not in source
    assert "conda install" not in source
