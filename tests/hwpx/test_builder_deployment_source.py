"""Deployment source admission and pinned materialization, without runtime installation."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hwpx/deploy_builder.sh"


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _executable(path: Path, source: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + source, encoding="utf-8")
    path.chmod(0o700)


@dataclass(frozen=True)
class DeploymentFixture:
    canonical: Path
    candidate: Path
    script: Path
    binaries: Path
    log: Path
    build_temporary_root: Path
    commit: str

    def run(
        self,
        *arguments: str,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            PATH=f"{self.binaries}:/usr/bin:/bin",
            HWPX_TEST_COMMANDS=str(self.log),
            HWPX_TEST_TEMP=str(self.build_temporary_root),
            HWPX_TEST_NPM=str(self.binaries / "npm"),
        )
        environment.update(extra_environment or {})
        return subprocess.run(
            ["bash", str(self.script), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""


@pytest.fixture
def deployment(tmp_path: Path) -> DeploymentFixture:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _git(canonical, "init", "--quiet")
    for member in (
        "packages/hwpx_contracts/release.txt",
        "services/hwpx_builder/release.txt",
        "services/hwpx_builder/kordoc_runtime/package.json",
        "services/hwpx_builder/kordoc_runtime/package-lock.json",
        "schemas/hwpx/example.schema.json",
        "scripts/hwpx/python_runtime_layout.py",
    ):
        path = canonical / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pinned-source\n", encoding="utf-8")
    (canonical / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    _git(canonical, "add", ".")
    _git(
        canonical,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Pinned deployment fixture",
    )
    candidate = tmp_path / "candidate worktree"
    _git(canonical, "worktree", "add", "--detach", str(candidate), "HEAD")
    commit = _git(candidate, "rev-parse", "HEAD")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.log"
    temporary_root = tmp_path / "builds"
    temporary_root.mkdir()
    real_git = shutil.which("git")
    real_mktemp = shutil.which("mktemp")
    assert real_git is not None and real_mktemp is not None
    _executable(
        binaries / "git",
        'if [[ "${HWPX_TEST_BAD_COMMIT:-}" = 1 '
        '&& "$*" = *"rev-parse --verify HEAD^{commit}" ]]; then\n'
        "  printf '%s\\n' not-a-commit\n  exit 0\nfi\n"
        'printf "git %s\\n" "$*" >> "$HWPX_TEST_COMMANDS"\n'
        f'exec "{real_git}" "$@"\n',
    )
    _executable(binaries / "id", 'printf "%s\\n" "${HWPX_TEST_USER:-eom}"\n')
    _executable(binaries / "stat", 'printf "%s\\n" "${HWPX_TEST_OWNER:-eom}"\n')
    _executable(
        binaries / "sudo",
        'printf "sudo %s\\n" "$*" >> "$HWPX_TEST_COMMANDS"\nexit 99\n',
    )
    _executable(
        binaries / "mktemp",
        f'template="${{@: -1}}"\nexec "{real_mktemp}" -d "$HWPX_TEST_TEMP/${{template##*/}}"\n',
    )
    _executable(binaries / "npm", "exit 80\n")
    _executable(
        binaries / "python",
        'printf "python %s\\n" "$*" >> "$HWPX_TEST_COMMANDS"\n'
        'if [[ "${1:-}" = -m && "${2:-}" = build ]]; then\n'
        '  source_root="${@: -1}"\n'
        '  [[ "$(< "$source_root/release.txt")" = pinned-source ]]\n'
        '  [[ ! -e "$source_root/ignored.py" ]]\n'
        "fi\n",
    )
    _executable(
        binaries / "node",
        'printf "node %s\\n" "$*" >> "$HWPX_TEST_COMMANDS"\n'
        'if [[ "${1:-}" = -p ]]; then printf "true\\n"; exit 0; fi\n'
        'if [[ "${1:-}" = "$HWPX_TEST_NPM" ]]; then\n'
        '  while [[ $# -gt 0 && "$1" != --prefix ]]; do shift; done\n'
        "  [[ $# -eq 2 ]]\n"
        '  runtime="$2/node_modules/kordoc"\n'
        '  mkdir -p "$runtime/THIRD_PARTY"\n'
        '  printf "fixture\\n" > "$runtime/LICENSE"\n'
        '  printf "fixture\\n" > "$runtime/NOTICE"\n'
        '  if [[ -n "${HWPX_TEST_MUTATE_SOURCE:-}" ]]; then\n'
        '    printf "changed-after-preflight\\n" > "$HWPX_TEST_MUTATE_SOURCE"\n'
        "  fi\nfi\n",
    )
    source = SCRIPT.read_text(encoding="utf-8")
    source = source.replace(
        'CANONICAL_REPOSITORY_ROOT="/home/eom/EOM"',
        f'CANONICAL_REPOSITORY_ROOT="{canonical}"',
        1,
    )
    for variable, binary in (("PYTHON", "python"), ("NODE", "node"), ("NPM", "npm")):
        source = source.replace(
            f'{variable}="/srv/eom/conda/envs/eom-hwpx/bin/{binary}"',
            f'{variable}="{binaries / binary}"',
            1,
        )
    runtime = tmp_path / "installed-runtime"
    (runtime / "node_modules/kordoc/THIRD_PARTY").mkdir(parents=True)
    (runtime / "node_modules/kordoc/LICENSE").write_text("fixture")
    (runtime / "node_modules/kordoc/NOTICE").write_text("fixture")
    source = source.replace(
        'KORDOC_TARGET="/srv/eom/conda/envs/eom-hwpx/share/eom-kordoc"',
        f'KORDOC_TARGET="{runtime}"',
        1,
    )
    script = tmp_path / "deploy_builder.sh"
    script.write_text(source, encoding="utf-8")
    return DeploymentFixture(canonical, candidate, script, binaries, log, temporary_root, commit)


def test_default_source_root_and_dry_run_remain_supported(deployment: DeploymentFixture) -> None:
    result = deployment.run("--dry-run")
    assert result.returncode == 0, result.stderr
    assert f"Would build commit {deployment.commit}" in result.stdout
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


@pytest.mark.parametrize(
    "mode",
    [
        "--verify",
        "--normalize-python-layout",
        "--normalize-node-layout",
        "--normalize-node-libraries",
    ],
)
def test_default_maintenance_modes_keep_prior_dirty_checkout_behavior(
    deployment: DeploymentFixture, mode: str
) -> None:
    (deployment.canonical / "packages/hwpx_contracts/release.txt").write_text("in-progress\n")
    result = deployment.run(mode)
    assert result.returncode == 0, result.stderr
    assert "python " in deployment.calls()
    assert "sudo " not in deployment.calls()
    assert "python -m build " not in deployment.calls()


def test_explicit_maintenance_source_still_requires_clean_worktree(
    deployment: DeploymentFixture,
) -> None:
    (deployment.candidate / "packages/hwpx_contracts/release.txt").write_text("in-progress\n")
    result = deployment.run("--verify", "--source-root", str(deployment.candidate))
    assert result.returncode != 0
    assert "Working tree must be clean" in result.stderr
    assert "python " not in deployment.calls()


def test_inherited_git_environment_cannot_replace_canonical_repository(
    deployment: DeploymentFixture,
) -> None:
    result = deployment.run(
        "--dry-run",
        "--source-root",
        str(deployment.candidate),
        extra_environment={
            "GIT_DIR": "/does-not-exist/git",
            "GIT_WORK_TREE": "/does-not-exist/worktree",
            "GIT_COMMON_DIR": "/does-not-exist/common",
            "GIT_INDEX_FILE": "/does-not-exist/index",
            "GIT_OBJECT_DIRECTORY": "/does-not-exist/objects",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/does-not-exist/alternates",
        },
    )
    assert result.returncode == 0, result.stderr
    assert f"Would build commit {deployment.commit}" in result.stdout


@pytest.mark.parametrize("source_first", [False, True])
def test_clean_worktree_can_deploy_while_primary_checkout_is_dirty(
    deployment: DeploymentFixture, source_first: bool
) -> None:
    (deployment.canonical / "packages/hwpx_contracts/release.txt").write_text("in-progress\n")
    arguments = ("--source-root", str(deployment.candidate), "--dry-run")
    if not source_first:
        arguments = ("--dry-run", "--source-root", str(deployment.candidate))
    result = deployment.run(*arguments)
    assert result.returncode == 0, result.stderr
    assert f"Would build commit {deployment.commit}" in result.stdout
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


@pytest.mark.parametrize(
    "arguments",
    [
        ("--unknown",),
        ("--source-root",),
        ("--source-root=anything",),
        ("--dry-run", "--install"),
        ("--verify", "--verify"),
        ("--source-root", "/tmp", "--source-root", "/tmp"),
    ],
)
def test_invalid_or_repeated_cli_arguments_fail_before_any_command(
    deployment: DeploymentFixture, arguments: tuple[str, ...]
) -> None:
    result = deployment.run(*arguments)
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert deployment.calls() == ""


@pytest.mark.parametrize("path", ["/", ".", "relative/path", "", "/does-not-exist"])
def test_invalid_source_paths_fail_closed_without_installation(
    deployment: DeploymentFixture, path: str
) -> None:
    result = deployment.run("--dry-run", "--source-root", path)
    assert result.returncode != 0
    assert "HWPX source root" in result.stderr
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


@pytest.mark.parametrize(
    "variant", ["symlink", "symlink-parent", "dot-segment", "trailing-slash", "control-character"]
)
def test_noncanonical_source_arguments_are_rejected(
    deployment: DeploymentFixture, variant: str, tmp_path: Path
) -> None:
    if variant == "symlink":
        link = tmp_path / "alias"
        link.symlink_to(deployment.candidate, target_is_directory=True)
        source = str(link)
    elif variant == "symlink-parent":
        link = tmp_path / "parent-alias"
        link.symlink_to(tmp_path, target_is_directory=True)
        source = str(link / deployment.candidate.name)
    elif variant == "dot-segment":
        source = f"{deployment.candidate}/../{deployment.candidate.name}"
    elif variant == "trailing-slash":
        source = str(deployment.candidate) + "/"
    else:
        source = str(deployment.candidate) + "\n"
    result = deployment.run("--dry-run", "--source-root", source)
    assert result.returncode != 0
    assert "HWPX source root" in result.stderr
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


def test_source_must_be_exact_worktree_root(deployment: DeploymentFixture) -> None:
    result = deployment.run("--dry-run", "--source-root", str(deployment.candidate / "services"))
    assert result.returncode != 0
    assert "exact Git worktree root" in result.stderr


def test_other_git_repository_is_not_a_release_source(
    deployment: DeploymentFixture, tmp_path: Path
) -> None:
    other = tmp_path / "unrelated"
    other.mkdir()
    _git(other, "init", "--quiet")
    result = deployment.run("--dry-run", "--source-root", str(other))
    assert result.returncode != 0
    assert "canonical EOM repository" in result.stderr


@pytest.mark.parametrize("dirty", ["tracked", "untracked"])
def test_dirty_selected_source_is_rejected_before_installation(
    deployment: DeploymentFixture, dirty: str
) -> None:
    target = deployment.candidate / (
        "packages/hwpx_contracts/release.txt" if dirty == "tracked" else "untracked.txt"
    )
    target.write_text("not-in-commit\n", encoding="utf-8")
    result = deployment.run("--dry-run", "--source-root", str(deployment.candidate))
    assert result.returncode != 0
    assert "Working tree must be clean" in result.stderr
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"HWPX_TEST_OWNER": "root"}, "owned by eom"),
        ({"HWPX_TEST_USER": "root"}, "run as eom"),
        ({"HWPX_TEST_BAD_COMMIT": "1"}, "40-character SHA"),
    ],
)
def test_owner_operator_and_full_commit_identity_are_required(
    deployment: DeploymentFixture, environment: dict[str, str], message: str
) -> None:
    result = deployment.run(
        "--dry-run", "--source-root", str(deployment.candidate), extra_environment=environment
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert "sudo " not in deployment.calls()
    assert "python " not in deployment.calls()


def test_default_install_requires_existing_noninteractive_authorization(
    deployment: DeploymentFixture,
) -> None:
    result = deployment.run("--source-root", str(deployment.candidate))
    assert result.returncode != 0
    assert "noninteractive operator authorization" in result.stderr
    assert "sudo -n true\n" in deployment.calls()
    assert "python " not in deployment.calls()
    assert not tuple(deployment.build_temporary_root.iterdir())


def test_build_materializes_only_pinned_commit_even_after_checkout_changes(
    deployment: DeploymentFixture,
) -> None:
    (deployment.candidate / "services/hwpx_builder/ignored.py").write_text("not-approved\n")
    result = deployment.run(
        "--build-only",
        "--source-root",
        str(deployment.candidate),
        extra_environment={
            "HWPX_TEST_MUTATE_SOURCE": str(
                deployment.candidate / "services/hwpx_builder/release.txt"
            )
        },
    )
    assert result.returncode == 0, result.stderr
    calls = deployment.calls()
    assert f"archive --format=tar {deployment.commit}" in calls
    builds = tuple(line for line in calls.splitlines() if line.startswith("python -m build "))
    assert len(builds) == 2
    assert builds[0].endswith("/packages/hwpx_contracts")
    assert builds[1].endswith("/services/hwpx_builder")
    assert "Working tree must be clean" not in result.stderr
    assert "sudo " not in calls
    assert (
        deployment.candidate / "services/hwpx_builder/release.txt"
    ).read_text() == "changed-after-preflight\n"


def test_release_verification_includes_geometry_code_and_noninteractive_installs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'installed_builder / "content_team_images.py"' in source
    assert 'installed_builder / "reference.py"' in source
    assert 'installed_contracts / "__init__.py"' in source
    assert 'installed_contracts / "picture_geometry.py"' in source
    assert '"eom_hwpx_contracts/picture_geometry.py"' in source
    assert '"$PYTHON" - "$VERIFY_SOURCE_ROOT"' in source
    assert 'VERIFY_SOURCE_ROOT="$WORK_ROOT"' in source
    assert 'PYTHON_LAYOUT_HELPER="$WORK_ROOT/scripts/hwpx/python_runtime_layout.py"' in source
    assert all(
        line.strip().startswith("sudo -n ")
        for line in source.splitlines()
        if line.strip().startswith("sudo ")
    )
