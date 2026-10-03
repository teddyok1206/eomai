"""Keep the independent wheel boundary aligned with the canonical schema inventory."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from eom_catalog_contracts import catalog_schema_inventory

ROOT = Path(__file__).resolve().parents[2]


def test_embedded_release_inspector_has_no_undefined_names() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index("inspect_release() {")
    python_start = script.index("<<'PY'\n", start) + len("<<'PY'\n")
    python_end = script.index("\nPY\n", python_start)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F821",
            "--stdin-filename",
            "release-inspector.py",
            "-",
        ],
        input=script[python_start:python_end],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wheel_catalog_resource_inventory_matches_canonical_contracts() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index("catalog_resources = {")
    end = script.index("\n}\n", start) + len("\n}")
    assignment = ast.parse(script[start:end]).body[0]
    assert isinstance(assignment, ast.Assign)
    actual = ast.literal_eval(assignment.value)
    expected = {
        resource.resource_path.removeprefix("resources/"): resource.canonical_path
        for _, resource in catalog_schema_inventory()
    }
    assert actual == expected


def test_privileged_migration_preflight_is_read_only_for_git_index(tmp_path: Path) -> None:
    source = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert 'git --no-optional-locks -C "${REPOSITORY_ROOT}" status --porcelain' in source
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("original\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    index = tmp_path / ".git/index"
    before = index.stat(), index.read_bytes()
    tracked.touch()
    subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(tmp_path),
            "status",
            "--porcelain",
        ],
        check=True,
        capture_output=True,
    )
    assert (index.stat(), index.read_bytes()) == before
