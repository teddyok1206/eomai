from __future__ import annotations

from pathlib import Path

import pytest
from eom_api.runtime_privileges import INSERT_TABLES, READ_TABLES, UPDATE_TABLES

from scripts.api import testdb_guard

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_role_bootstrap_revokes_drift_before_exact_grants() -> None:
    source = (REPOSITORY_ROOT / "scripts/api/bootstrap_runtime_role.sh").read_text(encoding="utf-8")

    required_reconciliation = (
        "REVOKE {} FROM {}",
        "REVOKE ALL PRIVILEGES ON DATABASE",
        "REVOKE ALL PRIVILEGES ON SCHEMA app, public",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA app",
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app",
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app",
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC",
    )
    assert all(statement in source for statement in required_reconciliation)
    assert "GRANT USAGE ON ALL SEQUENCES" not in source
    assert '"DELETE"' in source
    assert '"TRUNCATE"' in source
    assert "UPDATE app.alembic_version" in source
    assert "CREATE ROLE eom_api_privilege_probe" in source
    assert "TABLE_PRIVILEGES" in source
    assert "workflow_instances" in READ_TABLES
    assert "workflow_instances" in UPDATE_TABLES
    assert "workflow_commands" in INSERT_TABLES


def test_disposable_reconciliation_proves_idempotency_and_removes_drift() -> None:
    source = (REPOSITORY_ROOT / "scripts/api/testdb_prepare.sh").read_text(encoding="utf-8")

    assert "reconcile_runtime_role" in source
    assert source.count("reconcile_runtime_role") >= 4  # definition plus three invocations
    assert "GRANT DELETE ON TABLE app.workflow_instances" in source


def test_disposable_prepare_matches_production_application_schema_contract() -> None:
    production = (REPOSITORY_ROOT / "infra/compose/initdb/001-create-app-role.sh").read_text(
        encoding="utf-8"
    )
    disposable = (REPOSITORY_ROOT / "scripts/api/testdb_prepare.sh").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION" in production
    assert "CREATE SCHEMA app AUTHORIZATION" in disposable
    for contract in ("GRANT USAGE, CREATE ON SCHEMA app TO", "SET search_path TO app, public"):
        assert contract in production and contract in disposable
    assert "COMMENT ON SCHEMA app IS" in disposable
    assert "CREATE SCHEMA IF NOT EXISTS" not in disposable


def test_disposable_schema_metadata_requires_owner_marker_path_and_minimum_privileges() -> None:
    manifest = testdb_guard.TestDatabaseManifest.create("20260818112233_deadbeef")

    testdb_guard.validate_application_schema_metadata(
        manifest,
        schema_owner=manifest.owner_role,
        schema_comment=manifest.marker,
        effective_search_path=("app", "public"),
        has_usage=True,
        has_create=True,
    )
    invalid = (
        {"schema_owner": None},
        {"schema_comment": None},
        {"effective_search_path": ("public",)},
        {"has_usage": False},
        {"has_create": False},
    )
    baseline = {
        "schema_owner": manifest.owner_role,
        "schema_comment": manifest.marker,
        "effective_search_path": ("app", "public"),
        "has_usage": True,
        "has_create": True,
    }
    for override in invalid:
        with pytest.raises(testdb_guard.TestDatabaseGuardError):
            testdb_guard.validate_application_schema_metadata(
                manifest,
                **(baseline | override),
            )


def test_disposable_manifest_has_safe_deterministic_names() -> None:
    manifest = testdb_guard.TestDatabaseManifest.create("20260818112233_deadbeef")

    assert manifest.database == "eom_api_test_20260818112233deadbeef"
    assert manifest.owner_role == "eom_api_test_owner_20260818112233deadbeef"
    assert manifest.runtime_role == "eom_api_test_runtime_20260818112233deadbeef"
    assert max(map(len, (manifest.database, manifest.owner_role, manifest.runtime_role))) <= 63


def test_manifest_rejects_production_or_mismatched_names(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"database":"eom","owner_role":"eom_api_test_owner_20260818112233deadbeef",'
        '"runtime_role":"eom_api_test_runtime_20260818112233deadbeef",'
        '"test_id":"20260818112233_deadbeef"}\n',
        encoding="ascii",
    )

    with pytest.raises(testdb_guard.TestDatabaseGuardError):
        testdb_guard.TestDatabaseManifest.load(path)


@pytest.mark.parametrize(
    ("database", "owner_role", "runtime_role"),
    (
        (
            "eom",
            "eom_api_test_owner_20260818112233deadbeef",
            "eom_api_test_runtime_20260818112233deadbeef",
        ),
        (
            "postgres",
            "eom_api_test_owner_20260818112233deadbeef",
            "eom_api_test_runtime_20260818112233deadbeef",
        ),
        (
            "eom_api_test_20260818112233deadbeef",
            "eom_app",
            "eom_api_test_runtime_20260818112233deadbeef",
        ),
        (
            "eom_api_test_20260818112233deadbeef",
            "eom_api_test_owner_20260818112233deadbeef",
            "eom_api_runtime",
        ),
    ),
)
def test_manifest_rejects_production_database_and_role_names(
    tmp_path: Path,
    database: str,
    owner_role: str,
    runtime_role: str,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        (
            '{"database":"'
            + database
            + '","owner_role":"'
            + owner_role
            + '","runtime_role":"'
            + runtime_role
            + '","test_id":"20260818112233_deadbeef"}\n'
        ),
        encoding="ascii",
    )

    with pytest.raises(testdb_guard.TestDatabaseGuardError):
        testdb_guard.TestDatabaseManifest.load(path)


@pytest.mark.parametrize(
    ("owner", "database_marker", "owner_marker"),
    [
        ("wrong_owner", "EOM_API_DISPOSABLE_TEST_DB:20260818112233_deadbeef", None),
        ("eom_api_test_owner_20260818112233deadbeef", None, None),
        (
            "eom_api_test_owner_20260818112233deadbeef",
            "EOM_API_DISPOSABLE_TEST_DB:20260818112233_deadbeef",
            "wrong_marker",
        ),
    ],
)
def test_catalog_guard_rejects_wrong_owner_or_missing_marker(
    owner: str, database_marker: str | None, owner_marker: str | None
) -> None:
    manifest = testdb_guard.TestDatabaseManifest.create("20260818112233_deadbeef")

    with pytest.raises(testdb_guard.TestDatabaseGuardError):
        testdb_guard.validate_catalog_metadata(
            manifest,
            database_owner=owner,
            database_comment=database_marker,
            owner_comment=owner_marker,
            require_runtime=False,
        )


def test_state_directory_rejects_symlink(tmp_path: Path) -> None:
    target = Path("/tmp/eom-api-testdb-20260818112233_deadbeef")
    link = tmp_path / "eom-api-testdb-link"
    link.symlink_to(target)

    with pytest.raises(testdb_guard.TestDatabaseGuardError):
        testdb_guard.validate_state_directory(link)


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/api/bootstrap_runtime_role.sh",
        "scripts/api/testdb_prepare.sh",
        "scripts/api/testdb_run.sh",
        "scripts/api/testdb_cleanup.sh",
    ],
)
def test_runtime_role_shell_syntax(relative: str) -> None:
    import subprocess

    completed = subprocess.run(
        ("bash", "-n", str(REPOSITORY_ROOT / relative)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_disposable_database_runs_workflow_preclaim_integration() -> None:
    source = (REPOSITORY_ROOT / "scripts/api/testdb_run.sh").read_text(encoding="utf-8")

    assert "export EOM_RUN_INTEGRATION=1" in source
    assert "tests/integration/test_workflow_engine.py" in source
    assert "tests/api/test_workflow_start_integration.py" in source
    assert "tests/integration/test_workflow_submission_idempotency.py" in source


def test_disposable_migration_verifies_head_and_migration_0006_objects() -> None:
    source = (REPOSITORY_ROOT / "scripts/api/testdb_run.sh").read_text(encoding="utf-8")

    assert "{verify|migrate|tests}" in source
    assert "validate_application_schema_metadata" in source
    assert "SELECT version_num FROM app.alembic_version" in source
    assert "app.reject_identity_key_change()" in source
    assert "app.reject_api_audit_mutation()" in source
    assert "api_audit_events_append_only" in source


def test_cleanup_accepts_marked_database_after_failed_migration_without_runtime_role() -> None:
    manifest = testdb_guard.TestDatabaseManifest.create("20260818112233_deadbeef")
    testdb_guard.validate_catalog_metadata(
        manifest,
        database_owner=manifest.owner_role,
        database_comment=manifest.marker,
        owner_comment=manifest.marker,
        runtime_comment=None,
        require_runtime=False,
    )
    source = (REPOSITORY_ROOT / "scripts/api/testdb_cleanup.sh").read_text(encoding="utf-8")
    assert "require_runtime=runtime_exists" in source
    assert "if runtime_exists:" in source
    assert "--confirm" in source
    assert "test state directory metadata mismatch" in source
    assert '"${state_directory}/manifest.json" "${state_directory}/owner.env"' in source


def test_disposable_scripts_do_not_print_credentials_or_database_urls() -> None:
    prepare = (REPOSITORY_ROOT / "scripts/api/testdb_prepare.sh").read_text(encoding="utf-8")
    run = (REPOSITORY_ROOT / "scripts/api/testdb_run.sh").read_text(encoding="utf-8")

    for prohibited in (
        "print(owner_password)",
        "print(owner_url)",
        "printf '%s\\n' \"${EOM_DATABASE_URL}\"",
    ):
        assert prohibited not in prepare
        assert prohibited not in run


def test_disposable_workflow_tests_do_not_delete_immutable_history() -> None:
    sources = {
        relative: (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "tests/api/test_workflow_start_integration.py",
            "tests/integration/test_workflow_submission_idempotency.py",
            "tests/api/test_workflow_approval_runtime_role.py",
        )
    }

    assert all("delete(WorkflowDefinitionRecord)" not in source for source in sources.values())
    assert (
        "delete(ApiAuditEventRecord)"
        not in sources["tests/api/test_workflow_approval_runtime_role.py"]
    )
    runner = (REPOSITORY_ROOT / "scripts/api/testdb_run.sh").read_text(encoding="utf-8")
    assert runner.index("tests/integration/test_workflow_submission_idempotency.py") < runner.index(
        "tests/api/test_workflow_approval_runtime_role.py"
    )
