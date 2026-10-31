"""Build-only checkout selection never changes the production installation root."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def run_git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True, capture_output=True)


@pytest.fixture
def checkouts(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("local Git required")
    primary, linked, other = (tmp_path / name for name in ("primary", "linked", "other"))
    for root in (primary, other):
        root.mkdir()
        run_git(root, "init", "-q")
        run_git(
            root,
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "synthetic",
            "--allow-empty",
        )
    run_git(primary, "worktree", "add", "-qb", "hotfix/synthetic", str(linked))
    return primary, linked, other


@pytest.mark.parametrize(
    "action,cwd_index,accepted", (("build", 1, True), ("build", 2, False), ("install", 1, True))
)
def test_only_same_repository_builds_select_linked_checkout(checkouts, action, cwd_index, accepted):
    script = (Path(__file__).resolve().parents[2] / "scripts/api/deploy_release.sh").read_text()
    block = script.split("# A compatible hotfix", 1)[1].split(
        '\n[[ -r "${WORKFLOW_RUNNER_HOLD_LIBRARY}"', 1
    )[0]
    prefix = "set -euo pipefail\nGIT=/usr/bin/git\nREPOSITORY_ROOT=$PRIMARY\nfail() { exit 73; }\n"
    result = subprocess.run(
        (
            "bash",
            "-c",
            prefix + "# A compatible hotfix" + block + '\nprintf "%s" "$REPOSITORY_ROOT"',
        ),
        cwd=checkouts[cwd_index],
        env={**os.environ, "PRIMARY": str(checkouts[0]), "ACTION": action},
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if accepted else 73)
    if accepted:
        assert result.stdout == str(checkouts[1] if action == "build" else checkouts[0])
