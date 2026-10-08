"""One closed PostgreSQL privilege profile for the dedicated Artifact owner."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from psycopg import Cursor, sql
from sqlalchemy import text
from sqlalchemy.engine import Connection

TABLE_PRIVILEGES: Final = MappingProxyType(
    {
        "alembic_version": frozenset({"SELECT"}),
        "artifact_revisions": frozenset({"SELECT", "INSERT"}),
        "artifacts": frozenset({"SELECT", "INSERT"}),
        "general_chat_capacity": frozenset({"SELECT", "UPDATE"}),
        "general_chat_conversations": frozenset({"SELECT", "INSERT", "UPDATE"}),
        "general_chat_turns": frozenset({"SELECT", "INSERT", "UPDATE"}),
        "job_events": frozenset({"SELECT", "INSERT"}),
        "jobs": frozenset({"SELECT", "INSERT"}),
        "protocol_versions": frozenset({"SELECT", "INSERT"}),
    }
)
COLUMN_PRIVILEGES: Final = MappingProxyType(
    {
        ("operators", "SELECT"): frozenset({"operator_id", "status", "deleted_at"}),
        ("jobs", "UPDATE"): frozenset({"status", "updated_at", "completed_at"}),
    }
)
CHECKED_PRIVILEGES: Final = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
INSERT_TABLES: Final = tuple(
    name for name, values in TABLE_PRIVILEGES.items() if "INSERT" in values
)


def reconcile_chat_grants(cursor: Cursor[tuple[object, ...]], *, role: str) -> None:
    """Called only by guarded provisioning; caller owns role identity/transaction."""
    target = sql.Identifier(role)
    for statement in (
        "REVOKE ALL PRIVILEGES ON SCHEMA app, public FROM {}",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA app FROM {}",
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app FROM {}",
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app FROM {}",
    ):
        cursor.execute(sql.SQL(statement).format(target))
    # Table REVOKE does not remove independent per-column grants.
    cursor.execute(
        "SELECT c.relname, a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' "
        "AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped AND a.attacl IS NOT NULL"
    )
    for table, column in cursor.fetchall():
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ({}) ON app.{} FROM {}").format(
                sql.Identifier(str(column)),
                sql.Identifier(str(table)),
                target,
            )
        )
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(target))
    for table, privileges in TABLE_PRIVILEGES.items():
        cursor.execute(
            sql.SQL("GRANT {} ON app.{} TO {}").format(
                sql.SQL(", ").join(sql.SQL(value) for value in sorted(privileges)),
                sql.Identifier(table),
                target,
            )
        )
    for (table, privilege), columns in COLUMN_PRIVILEGES.items():
        cursor.execute(
            sql.SQL("GRANT {} ({}) ON app.{} TO {}").format(
                sql.SQL(privilege),
                sql.SQL(", ").join(sql.Identifier(value) for value in sorted(columns)),
                sql.Identifier(table),
                target,
            )
        )
    cursor.execute(
        "SELECT ns.nspname, seq.relname FROM pg_class seq "
        "JOIN pg_namespace ns ON ns.oid=seq.relnamespace "
        "JOIN pg_depend d ON d.objid=seq.oid AND d.deptype IN ('a','i') "
        "JOIN pg_class t ON t.oid=d.refobjid WHERE seq.relkind='S' "
        "AND ns.nspname='app' AND t.relname=ANY(%s)",
        (list(INSERT_TABLES),),
    )
    for namespace, sequence in cursor.fetchall():
        cursor.execute(
            sql.SQL("GRANT USAGE ON SEQUENCE {}.{} TO {}").format(
                sql.Identifier(str(namespace)),
                sql.Identifier(str(sequence)),
                target,
            )
        )


def chat_privileges_ready(connection: Connection, *, role: str) -> bool:
    """Closed positive and negative profile, including independent column ACLs."""
    checked = ", ".join(
        f"has_table_privilege(:role, c.oid, '{value}')" for value in CHECKED_PRIVILEGES
    )
    rows = connection.execute(
        text(
            "SELECT c.relname, ARRAY[" + checked + "] AS privileges FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relkind IN ('r','p')"
        ),
        {"role": role},
    ).all()
    seen = set()
    for table, observed in rows:
        seen.add(table)
        expected = TABLE_PRIVILEGES.get(table, frozenset())
        if tuple(observed) != tuple(value in expected for value in CHECKED_PRIVILEGES):
            return False
    if not TABLE_PRIVILEGES.keys() <= seen:
        return False
    column_rows = connection.execute(
        text(
            "SELECT c.relname, a.attname, "
            "has_column_privilege(:role, c.oid, a.attnum, 'SELECT'), "
            "has_column_privilege(:role, c.oid, a.attnum, 'INSERT'), "
            "has_column_privilege(:role, c.oid, a.attnum, 'UPDATE'), "
            "has_column_privilege(:role, c.oid, a.attnum, 'REFERENCES') "
            "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' "
            "AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped "
            "AND (a.attacl IS NOT NULL OR c.relname IN ('operators','jobs'))"
        ),
        {"role": role},
    ).all()
    found = set()
    for table, column, *observed in column_rows:
        for privilege, granted in zip(
            ("SELECT", "INSERT", "UPDATE", "REFERENCES"), observed, strict=True
        ):
            expected_column = privilege in TABLE_PRIVILEGES.get(table, frozenset()) or (
                column in COLUMN_PRIVILEGES.get((table, privilege), frozenset())
            )
            if bool(granted) != expected_column:
                return False
            if column in COLUMN_PRIVILEGES.get((table, privilege), frozenset()):
                found.add((table, privilege, column))
    return found == {
        (table, privilege, column)
        for (table, privilege), columns in COLUMN_PRIVILEGES.items()
        for column in columns
    }


def chat_role_boundary_ready(connection: Connection, *, role: str) -> bool:
    """No membership/DDL/definer escalation or unrelated sequence grants."""
    value = connection.scalar(
        text(
            "SELECT NOT (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication "
            "OR r.rolbypassrls OR r.rolinherit) AND r.rolcanlogin "
            "AND NOT EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) "
            "AND NOT has_schema_privilege(r.oid, 'app', 'CREATE') "
            "AND NOT has_schema_privilege(r.oid, 'public', 'CREATE') "
            "AND NOT has_database_privilege(r.oid, current_database(), 'CREATE') "
            "AND NOT EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('app','public') "
            "AND n.nspowner=r.oid) "
            "AND NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relowner=r.oid) "
            "AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='app' AND p.prosecdef "
            "AND has_function_privilege(r.oid,p.oid,'EXECUTE')) "
            "AND NOT EXISTS (SELECT 1 FROM pg_class seq "
            "JOIN pg_namespace n ON n.oid=seq.relnamespace "
            "WHERE n.nspname='app' AND seq.relkind='S' AND ("
            "has_sequence_privilege(r.oid,seq.oid,'SELECT') OR "
            "has_sequence_privilege(r.oid,seq.oid,'UPDATE') OR "
            "has_sequence_privilege(r.oid,seq.oid,'USAGE') <> EXISTS ("
            "SELECT 1 FROM pg_depend d JOIN pg_class t ON t.oid=d.refobjid "
            "WHERE d.objid=seq.oid AND d.deptype IN ('a','i') AND t.relname=ANY(:inserts)))) "
            "FROM pg_roles r WHERE r.rolname=:role"
        ),
        {"role": role, "inserts": list(INSERT_TABLES)},
    )
    return value is True
