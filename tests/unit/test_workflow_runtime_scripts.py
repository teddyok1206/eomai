import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_bootstrap_is_exact_and_non_recursive() -> None:
    source = (ROOT / "scripts/workflow/bootstrap_runtime_paths.sh").read_text(encoding="utf-8")
    assert '[[ "${EUID}" -eq 0 ]]' in source
    assert "/srv/eom/staging/catalog" in source
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "/srv/eom/workspaces" in source
    assert "chmod -R" not in source
    assert "chown -R" not in source
    assert "sudo" not in source
    assert "2770" in source and "0750" in source


def test_runtime_verifier_includes_prompt_staging_boundary() -> None:
    source = (ROOT / "scripts/workflow/verify_runtime_paths.sh").read_text(encoding="utf-8")
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "eom:eom:750" in source


def test_runtime_scripts_have_valid_shell_syntax() -> None:
    for relative in (
        "scripts/workflow/bootstrap_runtime_paths.sh",
        "scripts/workflow/verify_runtime_paths.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / relative)], capture_output=True, check=False, text=True
        )
        assert result.returncode == 0, result.stderr
