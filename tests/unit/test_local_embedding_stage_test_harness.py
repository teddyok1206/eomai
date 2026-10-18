"""Guarded purpose routing only; no database, secret or root execution."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/api/testdb_run.sh"


def test_disposable_inspection_is_read_only_and_follows_existing_private_state_guards() -> None:
    source = SCRIPT.read_text()
    branch = source.index('if [[ "${action}" == "inspect" ]]')
    assert source.index("validate_application_schema_metadata(") < branch
    leaf = source[branch : source.index('if [[ "${action}" == "migrate" ]]')]
    assert "connection.read_only = True" in leaf
    assert "SHOW transaction_read_only" in leaf
    assert "validate_catalog_metadata(" in leaf
    assert "shobj_description(db.oid,'pg_database')" in leaf
    assert "current_database()" in leaf and "current_user" in leaf
    assert "app.alembic_version" in leaf and "pg_stat_activity" in leaf
    assert "pid<>pg_backend_pid()" in leaf
    for forbidden in ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "GRANT", "COMMIT"):
        assert forbidden not in leaf
    assert "print(json.dumps" in leaf and '"other_connections"' in leaf
    assert "print(os.environ" not in leaf
    assert '"$1" != "inspect"' in source


def test_native_stage_branch_stays_after_exact_disposable_owner_preflight() -> None:
    source = SCRIPT.read_text()
    branch = source.index('if [[ "${action}" == "embedding-stage-tests" ]]')
    assert source.index("validate_application_schema_metadata(") < branch
    assert source.index("manifest.owner_role") < branch
    assert source.index("validate_state_directory(") < branch
    leaf = source[branch : source.index('if [[ "${action}" == "embedding-encoding-tests" ]]')]
    assert "tests/integration/test_local_embedding_stage_migration.py" in leaf
    assert "tests/integration/test_reference_query_step_migration.py" in leaf
    assert "tests/integration/test_private_chat_query_step_migration.py" in leaf
    assert "tests/integration/test_reference_query_native_persistence.py" in leaf
    assert "tests/integration/test_private_chat_query_native_persistence.py" in leaf
    assert "tests/integration/test_reference_query_submission.py" in leaf
    assert "tests/integration/test_reference_query_prepare_application.py" in leaf
    assert "tests/integration/test_similarity_item_start_persistence.py" in leaf
    assert "tests/integration/test_operator_fence_installation.py" in leaf
    assert "tests/integration/test_reference_start_idempotency.py" in leaf
    assert "EOM_RUN_OPERATOR_FENCE_INSTALLATION_TESTS=1" in leaf
    assert 'EOM_API_TEST_STATE="${state_directory}"' in leaf
    assert "EOM_RUN_INTEGRATION=1" in leaf
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


def test_private_declared_workflows_do_not_share_the_empty_history_migration_database() -> None:
    source = SCRIPT.read_text()
    stage_start = source.index('if [[ "${action}" == "embedding-stage-tests" ]]')
    stage = source[stage_start : source.index('if [[ "${action}" == "embedding-encoding-tests" ]]')]
    owner_start = source.index('if [[ "${action}" == "embedding-tests" ]]')
    owner = source[owner_start : source.index('if [[ "${action}" == "chat-knowledge-tests" ]]')]
    assert "test_private_chat_query_context_persistence.py" in stage
    assert "test_private_chat_query_command_lineage.py" not in stage
    assert "test_private_chat_query_submission.py" not in stage
    assert "test_private_chat_similarity_read.py" not in stage
    assert "test_private_chat_query_command_lineage.py" in owner
    assert "test_private_chat_query_submission.py" in owner
    assert "test_private_chat_similarity_read.py" in owner
    assert "test_private_chat_query_owner_admission.py" in owner
    assert "test_private_chat_query_context_persistence.py" not in owner


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
