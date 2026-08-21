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
    assert value["hwpx"]["deployment_state"] == "PREPARED_NOT_DEPLOYED"


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


def test_release_scripts_have_fixed_targets_and_no_recursive_permission_changes() -> None:
    scripts = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "scripts/web_gui/build_release.sh",
            "scripts/web_gui/install_release.sh",
            "scripts/web_gui/smoke_test.sh",
        )
    )
    assert "feat/web-gui-v0" in scripts
    assert "/srv/eom/conda/envs/eom-web/bin/python" in scripts
    assert "127.0.0.1:8790" in scripts
    assert "chmod -R" not in scripts
    assert "chown -R" not in scripts
    assert "sudo " not in scripts
    assert "pip install -e" not in scripts
