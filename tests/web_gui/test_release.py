from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_dependencies_are_pinned_and_explainable() -> None:
    project = tomllib.loads((ROOT / "apps/web_gui/pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    names = {re.split(r"[=<>]", value, maxsplit=1)[0].casefold() for value in dependencies}
    assert names == {"fastapi", "httpx", "pydantic", "pyyaml", "typer", "uvicorn"}
    assert all("==" in value for value in dependencies)
    assert not names & {"jinja2", "react", "vue", "playwright"}


def test_runtime_lock_covers_direct_dependencies() -> None:
    project = tomllib.loads((ROOT / "apps/web_gui/pyproject.toml").read_text(encoding="utf-8"))
    lock = (ROOT / "infra/conda/eom-web.requirements.lock").read_text(encoding="utf-8")
    for dependency in project["project"]["dependencies"]:
        assert dependency.casefold() in lock.casefold()


def test_example_config_preserves_loopback_and_existing_ports() -> None:
    value = yaml.safe_load((ROOT / "config/web-gui.example.yaml").read_text(encoding="utf-8"))
    assert value["server"] == {
        "host": "127.0.0.1",
        "port": 8790,
        "workers": 1,
        "allowed_hosts": ["127.0.0.1", "localhost"],
    }
    assert value["server"]["port"] not in {8000, 8765, 8780}
    assert "hwpx" not in value


def test_systemd_unit_has_dedicated_identity_and_sandbox() -> None:
    unit = (ROOT / "infra/systemd/eom-web-gui.service").read_text(encoding="utf-8")
    required = (
        "User=eom-web",
        "Group=eom-web",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "CapabilityBoundingSet=",
        "IPAddressDeny=any",
        "IPAddressAllow=localhost",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/home/eom/EOMIS",
        "InaccessiblePaths=/srv/eom/worker-homes",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/var/run/docker.sock",
    )
    for directive in required:
        assert directive in unit
    assert "0.0.0.0" not in unit
    assert "TimeoutStopSec=15" in unit


def test_uvicorn_shutdown_finishes_before_systemd_stop_timeout() -> None:
    cli = (ROOT / "apps/web_gui/eom_web_gui/cli.py").read_text(encoding="utf-8")

    assert "timeout_graceful_shutdown=10" in cli


def test_runtime_config_migration_removes_only_the_stale_hwpx_copy() -> None:
    script = (ROOT / "scripts/web_gui/migrate_runtime_config.sh").read_text(encoding="utf-8")

    assert "cookie_secure" in script
    assert 'value.pop("hwpx", None)' in script
    assert "unknown HWPX configuration drift" in script
    assert "HWPX capability must not be duplicated" in script
    assert "chmod -R" not in script
    assert "chown -R" not in script


def test_release_scripts_have_fixed_targets_and_no_recursive_permission_changes() -> None:
    scripts = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "scripts/web_gui/build_release.sh",
            "scripts/web_gui/install_release.sh",
            "scripts/web_gui/smoke_test.sh",
        )
    )
    assert 'EXPECTED_BRANCHES=("main"' in scripts
    assert "feat/web-gui-v0" in scripts
    assert "/srv/eom/conda/envs/eom-web/bin/python" in scripts
    assert "127.0.0.1:8790" in scripts
    assert "chmod -R" not in scripts
    assert "chown -R" not in scripts
    assert "sudo " not in scripts
    assert "pip install -e" not in scripts


def test_installer_normalizes_metadata_for_the_service_identity() -> None:
    installer = (ROOT / "scripts/web_gui/install_release.sh").read_text(encoding="utf-8")
    assert 'DIST_INFO_ROOT="${INSTALLED_PATHS[1]}"' in installer
    assert 'find "${DIST_INFO_ROOT}" -type d -exec chmod 0755 {} +' in installer
    assert 'find "${DIST_INFO_ROOT}" -type f -exec chmod 0644 {} +' in installer
    assert "installed distribution metadata path mismatch" in installer
    assert "installed distribution metadata root is not unique" in installer
    assert 'runuser -u eom-web -- env EXPECTED_COMMIT="${EXPECTED_COMMIT}"' in installer
    assert "web_gui_service_identity_metadata=PASS" in installer
    assert "chmod -R" not in installer
    assert "chown -R" not in installer
