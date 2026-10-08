from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_orchestrator.general_chat_privileges import (
    CHECKED_PRIVILEGES,
    COLUMN_PRIVILEGES,
    TABLE_PRIVILEGES,
    chat_privileges_ready,
    chat_role_boundary_ready,
    reconcile_chat_grants,
)
from eom_orchestrator.general_chat_role_preparation import (
    ChatRolePreparation,
    prepare_chat_role,
    require_chat_role_replay,
)
from eom_orchestrator.general_chat_state import ChatError


def expected_rows():
    tables = [
        (table, [value in grants for value in CHECKED_PRIVILEGES])
        for table, grants in TABLE_PRIVILEGES.items()
    ]
    tables += [
        ("operators", [False] * 7),
        ("operator_credentials", [False] * 7),
        ("worker_slots", [False] * 7),
    ]
    columns = []
    for table, names in (
        ("operators", ("operator_id", "status", "deleted_at", "username")),
        ("jobs", ("job_id", "request", "status", "updated_at", "completed_at")),
    ):
        for column in names:
            flags = [
                value in TABLE_PRIVILEGES.get(table, frozenset())
                or column in COLUMN_PRIVILEGES.get((table, value), frozenset())
                for value in ("SELECT", "INSERT", "UPDATE", "REFERENCES")
            ]
            columns.append((table, column, *flags))
    return tables, columns


class Connection:
    def __init__(self, tables, columns):
        self.rows, self.calls = [tables, columns], []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        rows = self.rows[len(self.calls) - 1]
        return SimpleNamespace(all=lambda: rows)


def test_closed_privilege_profile_uses_two_batched_catalog_queries():
    connection = Connection(*expected_rows())
    assert chat_privileges_ready(connection, role="synthetic_role")
    assert len(connection.calls) == 2
    assert all(
        statement.startswith("SELECT ") and params == {"role": "synthetic_role"}
        for statement, params in connection.calls
    )
    with pytest.raises(TypeError):
        TABLE_PRIVILEGES["operator_credentials"] = frozenset({"SELECT"})


@pytest.mark.parametrize(
    "change",
    [
        "missing-table",
        "missing-grant",
        "extra-table",
        "credential-column",
        "extra-operator-column",
        "job-body-update",
        "missing-operator-column",
    ],
)
def test_missing_or_extra_table_and_column_privileges_fail_closed(change):
    tables, columns = expected_rows()
    if change == "missing-table":
        tables = [row for row in tables if row[0] != "general_chat_turns"]
    elif change == "missing-grant":
        tables = [(name, [False] * 7 if name == "jobs" else flags) for name, flags in tables]
    elif change == "extra-table":
        tables += [("unrelated_table", [True, False, False, False, False, False, False])]
    elif change == "credential-column":
        columns += [("operator_credentials", "password_hash", True, False, False, False)]
    elif change == "extra-operator-column":
        columns += [("operators", "display_name", True, False, False, False)]
    elif change == "job-body-update":
        columns += [("jobs", "request", True, True, True, False)]
    else:
        columns = [row for row in columns if row[:2] != ("operators", "status")]
    assert not chat_privileges_ready(Connection(tables, columns), role="synthetic_role")


def test_role_boundary_is_read_only_and_covers_escalation_and_sequences():
    calls = []
    connection = SimpleNamespace(
        scalar=lambda statement, params: calls.append((str(statement), params)) or True
    )
    assert chat_role_boundary_ready(connection, role="synthetic_role")
    query, params = calls[0]
    assert query.startswith("SELECT ") and params["role"] == "synthetic_role"
    assert all(
        name in query
        for name in (
            "pg_auth_members",
            "has_schema_privilege",
            "has_database_privilege",
            "p.prosecdef",
            "has_sequence_privilege",
            "rolinherit",
        )
    )


class Cursor:
    def __init__(self, row=None):
        self.row, self.statements = row, []

    def execute(self, statement, params=None):
        self.statements.append(
            (statement if isinstance(statement, str) else statement.as_string(), params)
        )

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


def test_reconcile_grants_does_not_grant_identity_write_or_blanket_sequence_usage():
    cursor = Cursor()
    reconcile_chat_grants(cursor, role="synthetic_role")
    statements = [statement for statement, _ in cursor.statements]
    assert not any(
        "GRANT ALL" in value or ("ALL SEQUENCES" in value and value.startswith("GRANT"))
        for value in statements
    )
    assert any(
        'GRANT SELECT ("deleted_at", "operator_id", "status") ON app."operators"' in value
        for value in statements
    )
    assert any(
        'GRANT UPDATE ("completed_at", "status", "updated_at") ON app."jobs"' in value
        for value in statements
    )
    assert not any(
        value.startswith("GRANT") and "operator_credentials" in value for value in statements
    )


@pytest.mark.parametrize(
    "existing,secret,allowed",
    [
        (None, False, True),
        (None, True, True),
        (("marker",), True, True),
        (("other",), True, False),
        (("marker",), False, False),
    ],
)
def test_role_collision_is_not_adopted_without_exact_durable_receipt(existing, secret, allowed):
    cursor = Cursor(existing)
    spec = ChatRolePreparation("synthetic_role", "synthetic_db", "marker")
    if allowed:
        assert require_chat_role_replay(cursor, spec, secret_exists=secret) is (
            existing is not None
        )
    else:
        with pytest.raises(ChatError, match="IDENTITY_CONFLICT"):
            require_chat_role_replay(cursor, spec, secret_exists=secret)
    assert len(cursor.statements) == 1 and cursor.statements[0][0].startswith("SELECT ")


def test_existing_role_replay_does_not_rotate_password():
    cursor = Cursor()
    prepare_chat_role(
        cursor,
        ChatRolePreparation("synthetic_role", "synthetic_db", "marker"),
        password="synthetic_secret",
        exists=True,
    )
    assert not any(
        "PASSWORD" in statement or "synthetic_secret" in statement
        for statement, _ in cursor.statements
    )


def test_unknown_membership_stops_before_reconciliation():
    cursor = Cursor((1,))
    with pytest.raises(ChatError, match="IDENTITY_CONFLICT"):
        prepare_chat_role(
            cursor,
            ChatRolePreparation("synthetic_role", "synthetic_db", "marker"),
            password="synthetic_secret",
            exists=True,
        )
    assert len(cursor.statements) == 1
