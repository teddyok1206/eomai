"""Fixed namespace source templates, not evidence of installed unit/selector activation."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = (
    "infra/systemd/eom-embedding-native-cpu-probe@.service",
    "infra/systemd/eom-embedding-native-cpu-index@.service",
    "infra/systemd/eom-embedding-native-cpu-query@.service",
    "infra/systemd/eom-embedding-native-index-prepare@.service",
    "infra/systemd/eom-embedding-native-query-prepare@.service",
    "services/workflow_runner/eom_workflow_runner/resources/eom-embedding-index-owner.service.in",
    "services/workflow_runner/eom_workflow_runner/resources/eom-reference-query-owner.service.in",
)


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_fixed_native_and_verifier_unit_binds_one_required_snapshot_before_exec(
    template: str,
) -> None:
    lines = (ROOT / template).read_text().splitlines()
    bindings = [line for line in lines if line.startswith("BindReadOnlyPaths=")]
    assert bindings == [
        "BindReadOnlyPaths=/opt/eom/embedding-host-configurations/selected-cache:/etc/ld.so.cache"
    ]
    assert "ProtectSystem=strict" in lines and "NoNewPrivileges=yes" in lines
    assert not any(
        "embedding-host-configurations" in line
        for line in lines
        if line.startswith("ReadWritePaths=")
    )
    assert all("@HOST" not in line and "${HOST" not in line for line in lines)
