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
    assert '"$wheel_sha256" ]] || fail NATIVE_OWNER_WHEEL_HASH_MISMATCH' in source
    assert "--no-deps --no-index --no-compile --no-cache-dir" in source
    assert "CPU_RUNTIME=UNCHANGED" in source
    for forbidden in (
        "/opt/eom/conda/envs/",
        "/etc/eom/",
        "systemctl",
        "--upgrade",
        "--force-reinstall",
        "rm -",
        "sudo ",
    ):
        assert forbidden not in source
