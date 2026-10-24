"""Execute the shared SQL predicates in a disposable in-memory database."""

from __future__ import annotations

from eom_orchestrator.capability_snapshot_queries import (
    current_assignment_snapshot_clause,
    latest_binding_snapshot_clause,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
)
from sqlalchemy import create_engine, select


def test_old_account_and_superseded_model_snapshots_cannot_authorize_work():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE codex_auth_bindings "
            "(binding_id TEXT PRIMARY KEY, current_assignment_revision_id TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE codex_auth_assignment_revisions "
            "(assignment_revision_id TEXT PRIMARY KEY, assigned_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE codex_capability_snapshots "
            "(capability_snapshot_id TEXT PRIMARY KEY, binding_id TEXT, observed_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE codex_capability_entries (capability_snapshot_id TEXT, model TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_auth_bindings VALUES ('binding', 'new-assignment')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_auth_assignment_revisions "
            "VALUES ('new-assignment', '2026-10-24T01:00:00Z')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_snapshots "
            "VALUES ('old', 'binding', '2026-10-24T00:59:00Z')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_entries VALUES ('old', 'unverified-old-model')"
        )
        statement = (
            select(CodexCapabilitySnapshotRecord.capability_snapshot_id)
            .join(
                CodexAuthBindingRecord,
                CodexAuthBindingRecord.binding_id == CodexCapabilitySnapshotRecord.binding_id,
            )
            .join(
                CodexCapabilityEntryRecord,
                CodexCapabilityEntryRecord.capability_snapshot_id
                == CodexCapabilitySnapshotRecord.capability_snapshot_id,
            )
            .where(current_assignment_snapshot_clause(), latest_binding_snapshot_clause())
        )
        assert connection.execute(statement).all() == []
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_snapshots "
            "VALUES ('new-a', 'binding', '2026-10-24T01:01:00Z')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_entries VALUES ('new-a', 'initial-model')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_snapshots "
            "VALUES ('new-b', 'binding', '2026-10-24T01:02:00Z')"
        )
        connection.exec_driver_sql(
            "INSERT INTO codex_capability_entries VALUES ('new-b', 'verified-model')"
        )
        assert connection.scalars(statement).all() == ["new-b"]
        assert (
            connection.scalars(
                statement.where(CodexCapabilityEntryRecord.model == "initial-model")
            ).all()
            == []
        )
        assert connection.scalars(
            statement.where(CodexCapabilityEntryRecord.model == "verified-model")
        ).all() == ["new-b"]
        # Legacy NULL assignments remain readable; a dangling non-NULL assignment fails closed.
        connection.exec_driver_sql(
            "UPDATE codex_auth_bindings SET current_assignment_revision_id = NULL"
        )
        assert connection.scalars(statement).all() == ["new-b"]
        connection.exec_driver_sql(
            "UPDATE codex_auth_bindings SET current_assignment_revision_id = 'missing'"
        )
        assert connection.scalars(statement).all() == []
    engine.dispose()
