from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOYER = ROOT / "scripts" / "infra" / "deploy_service_identities.sh"
MOUNT_HARDENER = ROOT / "scripts" / "infra" / "harden_artifact_mount.sh"
MOUNT_CONTRACT = ROOT / "scripts" / "infra" / "artifact_mount_contract.py"


def _mount_contract_module():
    spec = importlib.util.spec_from_file_location("artifact_mount_contract", MOUNT_CONTRACT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manager_units_use_dedicated_identities() -> None:
    expectations = {
        "eom-workflow-runner.service": (
            "User=eom-workflow-runner",
            "SupplementaryGroups=eom-cdx-01",
        ),
        "eom-catalog-application-runner.service": (
            "User=eom-catalog-manager",
            "SupplementaryGroups=eom",
        ),
        "eom-hwpx-application-runner.service": (
            "User=eom-hwpx-manager",
            "SupplementaryGroups=eom eom-hwpx",
        ),
    }
    for filename, required in expectations.items():
        source = (ROOT / "infra" / "systemd" / filename).read_text(encoding="utf-8")
        assert all(value in source for value in required)
        assert "User=eom\n" not in source


def test_identity_deployer_verifies_mount_and_polkit_boundaries() -> None:
    source = DEPLOYER.read_text(encoding="utf-8")

    assert "verify_artifact_mount" in source
    assert "file_mode=0660" in source
    assert "dir_mode=0770" in source
    assert 'chmod 02770 "${ARTIFACT_ROOT}"' not in source
    assert 'chgrp "${ARTIFACT_GROUP}"' not in source
    assert "sudo docker lxd adm" in source
    assert "a fixed child unit is active" in source
    assert "for _attempt in $(seq 1 50)" in source
    assert "POLKIT_CROSS_START=DENIED" in source
    assert "--allow-user-interaction" not in source
    assert "pip install" not in source
    assert "conda install" not in source


def test_artifact_mount_hardener_is_commit_pinned_atomic_and_recoverable() -> None:
    source = MOUNT_HARDENER.read_text(encoding="utf-8")

    assert 'git -C "${REPOSITORY}" rev-parse HEAD' in source
    assert 'git -C "${REPOSITORY}" status --porcelain' in source
    assert "findmnt --verify" in source
    assert 'install -o root -g root -m 0600 "${FSTAB}" "${BACKUP}"' in source
    assert 'mv -fT "${UPDATED}" "${FSTAB}"' in source
    assert 'systemctl restart "${MOUNT_UNIT}"' in source
    assert 'systemctl is-active --quiet "${AUTOMOUNT_UNIT}"' in source
    assert "trap recover EXIT" in source
    assert "file_mode=0660" in source
    assert "dir_mode=0770" in source
    assert "verify_writer_identity" in source
    assert all(
        identity in source
        for identity in ("eom-workflow-runner", "eom-catalog-manager", "eom-hwpx-manager")
    )
    assert "fixed worker can write the Artifact root" in source
    assert all(flag in source for flag in ("nosuid", "nodev", "noexec"))
    contract_source = MOUNT_CONTRACT.read_text(encoding="utf-8")
    assert "password=" in contract_source
    assert "pass=" in contract_source
    assert "ARTIFACT_WORLD_ACCESS=DENIED" in source
    assert "sudo" not in source


def test_artifact_mount_contract_rewrites_only_the_pinned_entry(tmp_path: Path) -> None:
    module = _mount_contract_module()
    source = tmp_path / "fstab"
    output = tmp_path / "updated"
    source.write_text(
        "# preserved\n"
        "UUID=synthetic / ext4 defaults 0 1\n"
        "//192.0.2.10/share /mnt/nas cifs "
        "credentials=/synthetic/credential,vers=3.0,uid=9,gid=8,file_mode=0644,"
        "dir_mode=0755,_netdev,nofail,x-systemd.automount 0 0\n",
        encoding="utf-8",
    )

    module.rewrite_fstab(
        source,
        output,
        expected_source="//192.0.2.10/share",
        mount_point="/mnt/nas",
        uid=1000,
        gid=1000,
    )

    updated = output.read_text(encoding="utf-8")
    assert "# preserved\nUUID=synthetic / ext4 defaults 0 1\n" in updated
    assert "credentials=/synthetic/credential" in updated
    assert all(option in updated for option in ("uid=1000", "gid=1000"))
    assert all(option in updated for option in ("file_mode=0660", "dir_mode=0770"))
    assert all(option in updated for option in ("nosuid", "nodev", "noexec"))
    assert "uid=9" not in updated and "file_mode=0644" not in updated


@pytest.mark.parametrize(
    "unsafe_option",
    ("password=synthetic", "pass=synthetic"),
)
def test_artifact_mount_contract_rejects_inline_credentials(
    tmp_path: Path, unsafe_option: str
) -> None:
    module = _mount_contract_module()
    source = tmp_path / "fstab"
    source.write_text(
        f"//192.0.2.10/share /mnt/nas cifs {unsafe_option},defaults 0 0\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ArtifactMountContractError):
        module.rewrite_fstab(
            source,
            tmp_path / "updated",
            expected_source="//192.0.2.10/share",
            mount_point="/mnt/nas",
            uid=1000,
            gid=1000,
        )
