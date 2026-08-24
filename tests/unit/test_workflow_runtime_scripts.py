import subprocess
from pathlib import Path

from eom_catalog_service.settings import CATALOG_FIXED_STAGING_ROOTS

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_bootstrap_is_exact_and_non_recursive() -> None:
    source = (ROOT / "scripts/workflow/bootstrap_runtime_paths.sh").read_text(encoding="utf-8")
    assert '[[ "${EUID}" -eq 0 ]]' in source
    assert "/srv/eom/staging/catalog" in source
    assert "/srv/eom/staging/catalog/content-packs" in source
    assert "/srv/eom/staging/catalog/registry" in source
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "/srv/eom/workspaces" in source
    assert "chmod -R" not in source
    assert "chown -R" not in source
    assert "sudo" not in source
    assert "2770" in source and "0750" in source
    assert "find " not in source


def test_runtime_verifier_includes_all_fixed_catalog_staging_boundaries() -> None:
    source = (ROOT / "scripts/workflow/verify_runtime_paths.sh").read_text(encoding="utf-8")
    assert "/srv/eom/staging/catalog/content-packs" in source
    assert "/srv/eom/staging/catalog/registry" in source
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "eom:eom:750" in source
    assert "mktemp -d" in source
    assert ".eom-runtime-probe." in source


def test_runtime_scripts_match_typed_fixed_catalog_inventory() -> None:
    expected = {
        str(definition.path_beneath(Path("/srv/eom/staging/catalog")))
        for definition in CATALOG_FIXED_STAGING_ROOTS
    }
    assert expected == {
        "/srv/eom/staging/catalog/content-packs",
        "/srv/eom/staging/catalog/registry",
        "/srv/eom/staging/catalog/workflow-prompts",
    }
    for relative in (
        "scripts/workflow/bootstrap_runtime_paths.sh",
        "scripts/workflow/verify_runtime_paths.sh",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(path in source for path in expected)
        assert "chmod -R" not in source
        assert "chown -R" not in source


def test_systemd_authorization_verifier_is_nonprivileged_and_negative_by_default() -> None:
    source = (ROOT / "scripts/workflow/verify_systemd_worker_authorization.sh").read_text(
        encoding="utf-8"
    )
    assert "sudo" not in source
    assert "codex" not in source.lower()
    assert "--uid=root --gid=root /usr/bin/true" in source
    assert "restart" in source
    assert "malformed.service" in source


def test_runtime_scripts_have_valid_shell_syntax() -> None:
    for relative in (
        "scripts/workflow/bootstrap_runtime_paths.sh",
        "scripts/workflow/deploy_runner_service.sh",
        "scripts/workflow/install_runner_configuration.sh",
        "scripts/workflow/verify_runtime_paths.sh",
        "scripts/workflow/verify_systemd_worker_authorization.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / relative)], capture_output=True, check=False, text=True
        )
        assert result.returncode == 0, result.stderr


def test_runner_configuration_installs_root_owned_capability_policy() -> None:
    source = (ROOT / "scripts/workflow/install_runner_configuration.sh").read_text(encoding="utf-8")

    assert "config/workflows/knowledge-analysis.v1.yaml" in source
    assert "/knowledge-analysis.yaml" in source
    assert "content/prompt-templates/placeholders/support.txt" in source
    assert "/support.txt" in source
    assert "config/codex-capabilities.example.yaml" in source
    assert "/codex-capabilities.yaml" in source
    assert "install -o root -g root -m 0644" in source
    assert "root:root:644" in source
    assert "sudo" not in source
