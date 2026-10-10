"""Source/shell checks only: no privileged callback, installed runtime or credentials."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOUNDARY = ROOT / "scripts/api/release_operator_boundary.sh"


def _bash(command: str, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("/usr/bin/bash", "-euo", "pipefail", "-c", command),
        env={"PATH": "/usr/bin:/bin", "TZ": "UTC", **environment},
        check=False,
        text=True,
        capture_output=True,
        timeout=5,
    )


def test_build_can_source_operator_library_without_configuration_or_side_effect() -> None:
    result = _bash(f'source "{BOUNDARY}"; printf build_only_defined')
    assert result.returncode == 0 and result.stdout == "build_only_defined"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "arguments",
    (
        "",
        "ARBITRARY_COMMAND " + "a" * 40,
        "MIGRATION_VERIFY wrong-commit",
        "MIGRATION_VERIFY " + "a" * 40,
    ),
)
def test_missing_config_and_unbounded_command_rejected_before_sudo(arguments: str) -> None:
    result = _bash(f'source "{BOUNDARY}"; run_release_operator {arguments}')
    assert result.returncode == 1
    assert result.stderr.strip() == "RELEASE_OPERATOR_BOUNDARY_REJECTED"
    assert result.stdout == ""


def _environment(launcher: Path) -> dict[str, str]:
    digest = "sha256:" + "a" * 64
    return {
        "EOM_RELEASE_OPERATOR_LAUNCHER": str(launcher),
        "EOM_RELEASE_OPERATOR_RUNTIME_PREFIX": "/not/read/protected-prefix",
        "EOM_RELEASE_OPERATOR_RUNTIME_SHA256": digest,
        "EOM_RELEASE_OPERATOR_CONTEXT": "/not/read/operator-context.json",
        "EOM_RELEASE_OPERATOR_CONTEXT_SHA256": digest,
        "EOM_RELEASE_OPERATOR_LAUNCHER_SHA256": digest,
        "EOM_RELEASE_OPERATOR_HELPER_SHA256": digest,
    }


def test_unprivileged_owned_launcher_cannot_run_before_its_own_self_check(tmp_path: Path) -> None:
    launcher = tmp_path / "launcher.sh"
    launcher.write_text("# synthetic launcher, must never execute\n")
    result = _bash(
        f'source "{BOUNDARY}"; run_release_operator MIGRATION_VERIFY {"a" * 40}',
        **_environment(launcher),
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.strip() == "RELEASE_OPERATOR_BOUNDARY_REJECTED"


@pytest.mark.parametrize("field", ("LAUNCHER_SHA256", "RUNTIME_SHA256", "CONTEXT_SHA256"))
def test_hash_inputs_are_closed_sha_values_before_any_privileged_process(field: str) -> None:
    environment = _environment(Path("/not/read/launcher"))
    environment["EOM_RELEASE_OPERATOR_" + field] = "not a SHA"
    result = _bash(
        f'source "{BOUNDARY}"; run_release_operator MIGRATION_VERIFY {"a" * 40}',
        **environment,
    )
    assert result.returncode == 1 and result.stderr.strip() == "RELEASE_OPERATOR_BOUNDARY_REJECTED"


def test_native_metadata_predicate_checks_actual_regular_files_in_one_find_process(
    tmp_path: Path,
) -> None:
    # Only the find predicate runs, using this test UID. This does not admit/execute a runtime.
    good = tmp_path / "regular"
    good.write_bytes(b"not executable")
    good.chmod(0o644)
    source = (ROOT / "scripts/api/release_operator_runtime.sh").read_text()
    start = source.index("invalid=$(find -P")
    end = source.index('[[ -z "$invalid" ]]', start)
    predicate = source[start:end].replace("-uid 0", f"-uid {os.getuid()}")
    command = predicate + ' printf "%s" "$invalid"'
    assert _bash(command, PREFIX=str(tmp_path)).stdout == ""
    good.chmod(0o666)
    assert _bash(command, PREFIX=str(tmp_path)).stdout == "x"
    good.chmod(0o644)
    os.link(good, tmp_path / "hardlink")
    assert _bash(command, PREFIX=str(tmp_path)).stdout == "x"


def test_native_metadata_predicate_rejects_control_names(tmp_path: Path) -> None:
    source = (ROOT / "scripts/api/release_operator_runtime.sh").read_text()
    start = source.index("invalid=$(find -P")
    end = source.index('[[ -z "$invalid" ]]', start)
    command = source[start:end].replace("-uid 0", f"-uid {os.getuid()}")
    command += ' printf "%s" "$invalid"'
    (tmp_path / "terminal-newline\n").write_bytes(b"not executable")
    assert _bash(command, PREFIX=str(tmp_path)).stdout == "x"


def test_callback_surface_changes_neither_migration_meaning_nor_default_build_path() -> None:
    migration = (ROOT / "scripts/api/migrate_release.sh").read_text()
    deployment = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert "run_release_operator MIGRATION_UPGRADE_0051" in migration
    assert "run_release_operator MIGRATION_VERIFY" in migration
    assert migration.index('[[ "$EUID" -ne 0 ]]') < migration.index("git -C")
    assert migration.index('[[ "$EUID" -ne 0 ]]') < migration.index('source "${REPOSITORY_ROOT}')
    assert "POSTGRES_ENV" not in migration
    assert "PYTHONPATH=" not in migration and "run_reviewed_python" not in migration
    assert "alembic upgrade head" not in migration
    build = deployment.split('case "${ACTION}" in', 1)[1].split("install)", 1)[0]
    assert "run_release_operator" not in build and "build_release" in build
    boundary = BOUNDARY.read_text()
    assert boundary.index("/usr/bin/sha256sum") < boundary.index("/usr/bin/sudo")
    assert "RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN" in boundary
    assert "API_PYTHON" not in boundary and "PYTHONPATH" not in boundary
    assert 'run_release_operator API_ISOLATION_VERIFY "${COMMIT}"' in deployment
    assert 'sudo -n "${RUNTIME_VERIFIER_TARGET}"' not in deployment


def test_all_changed_shells_parse_without_execution() -> None:
    result = subprocess.run(
        (
            "/usr/bin/bash",
            "-n",
            str(BOUNDARY),
            str(ROOT / "scripts/api/release_operator_runtime.sh"),
            str(ROOT / "scripts/api/migrate_release.sh"),
            str(ROOT / "scripts/api/deploy_release.sh"),
            str(ROOT / "scripts/api/bootstrap_runtime_role.sh"),
        ),
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0


def test_exec_keeps_db_interpreter_pid_and_outer_group_without_privileged_execution() -> None:
    # Exercise only a tiny non-root process fixture, never the real bootstrap/DB script.
    process = subprocess.Popen(
        (
            "/usr/bin/bash",
            "-c",
            'exec "$1" -I -c "import os; print(os.getpid(), os.getpgrp())"',
            "synthetic-exec-fixture",
            "/srv/eom/conda/envs/eom-core/bin/python",
        ),
        env={"PATH": "/usr/bin:/bin"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        output, error = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    pid, group = map(int, output.split())
    assert process.returncode == 0 and not error
    assert pid == process.pid and group == os.getpgrp()
