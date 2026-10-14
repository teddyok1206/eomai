"""The removable owner release never installs/adopts the separately admitted CPU prefix."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/embedding/install_owner_release.sh"


def test_owner_release_installer_is_syntactically_valid() -> None:
    result = subprocess.run(("/bin/bash", "-n", str(SCRIPT)), capture_output=True, check=False)
    assert result.returncode == 0


def test_owner_installation_is_separate_offline_and_no_clobber() -> None:
    source = SCRIPT.read_text()
    assert "release_root=/opt/eom/embedding-owner-releases" in source
    assert 'mkdir -m 0755 "$target"' in source
    assert '[[ ! -e "$target" && ! -L "$target" ]]' in source
    assert "verify_release_wheel_records.py" in source
    assert "--platform-only" in source
    assert "--owner-pair" in source
    assert '"$contracts_sha256" ]] || fail NATIVE_OWNER_API_CONTRACTS_HASH_MISMATCH' in source
    assert "NATIVE_OWNER_WHEEL_SOURCE_MISMATCH" in source
    assert "NATIVE_OWNER_API_CONTRACTS_INSTALLED=PASS" in source
    assert '"$wheel_sha256" ]] || fail NATIVE_OWNER_WHEEL_HASH_MISMATCH' in source
    assert "--no-deps --no-index --no-compile --no-cache-dir" in source
    assert "CPU_RUNTIME=UNCHANGED" in source
    for forbidden in (
        "/opt/eom/conda/envs/eom-embedding-index-cpu",
        "/opt/eom/conda/envs/eom-embedding-index-cuda",
        "/srv/eom/conda/envs/eom-api",
        "/home/eom/EOM/",
        "/etc/eom/",
        "systemctl",
        "--upgrade",
        "--force-reinstall",
        "rm -",
        "sudo ",
    ):
        assert forbidden not in source


def test_installer_requires_fixed_root_code_and_protected_operator_interpreter() -> None:
    source = SCRIPT.read_text()
    assert "installer=/usr/local/libexec/eom-embedding-owner/install_owner_release.sh" in source
    assert (
        "verifier=/usr/local/libexec/eom-embedding-owner/verify_release_wheel_records.py" in source
    )
    assert "owner_python=/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12" in source
    assert '[[ "${BASH_SOURCE[0]}" == "$installer" ]]' in source
    assert 'protected_path "$executable"' in source
    assert '"$owner_python" -I -B "$verifier"' in source
    assert '"$owner_python" -I -B -m pip install' in source
    assert '--target "$stage/site-packages"' in source
    assert source.index('protected_path "$executable"') < source.index("stage=$(mktemp -d")
