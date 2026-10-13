"""Guarded purpose routing only; no database, secret or root execution."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/api/testdb_run.sh"


def test_native_stage_branch_stays_after_exact_disposable_owner_preflight() -> None:
    source = SCRIPT.read_text()
    branch = source.index('if [[ "${action}" == "embedding-stage-tests" ]]')
    assert source.index("validate_application_schema_metadata(") < branch
    assert source.index("manifest.owner_role") < branch
    assert source.index("validate_state_directory(") < branch
    leaf = source[branch : source.index('if [[ "${action}" == "embedding-encoding-tests" ]]')]
    assert "tests/integration/test_local_embedding_stage_migration.py" in leaf
    assert "tests/integration/test_local_embedding_runner.py" in leaf
    assert 'EOM_CHAT_KNOWLEDGE_TEST_STATE="${state_directory}"' in leaf
    assert "EOM_RUN_API_INTEGRATION=1" in leaf
    assert "sudo" not in leaf and "psql" not in leaf and "source " not in leaf
    assert '"$1" != "embedding-stage-tests"' in source


def test_session_fence_purpose_uses_existing_owner_guard_and_exact_opt_in() -> None:
    source = SCRIPT.read_text()
    branch = source.index('if [[ "${action}" == "authenticated-session-tests" ]]')
    assert source.index("validate_application_schema_metadata(") < branch
    assert source.index("manifest.owner_role") < branch
    assert source.index("validate_state_directory(") < branch
    leaf = source[branch : source.index('if [[ "${action}" == "embedding-stage-tests" ]]')]
    assert "tests/integration/test_authenticated_session_fence.py" in leaf
    assert 'EOM_API_TEST_STATE="${state_directory}"' in leaf
    assert "EOM_RUN_INTEGRATION=1" in leaf
    assert "EOM_RUN_API_INTEGRATION=1" in leaf
    assert "EOM_RUN_AUTHENTICATED_SESSION_INTEGRATION=1" in leaf
    assert "sudo" not in leaf and "psql" not in leaf and "source " not in leaf
    assert '"$1" != "authenticated-session-tests"' in source


def test_shell_parses_without_running_any_database_action() -> None:
    result = subprocess.run(
        ["/usr/bin/bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0


def test_unknown_purpose_rejects_before_reading_a_state_or_secret() -> None:
    result = subprocess.run(
        ["/usr/bin/bash", str(SCRIPT), "unreviewed-stage-tests", "/tmp/no-database-is-created"],
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 2 and b"usage:" in result.stderr
