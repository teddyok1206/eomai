"""Transactional creation/replay of one explicitly guarded runtime identity."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import Cursor, sql

from eom_orchestrator.general_chat_privileges import reconcile_chat_grants
from eom_orchestrator.general_chat_state import ChatError


@dataclass(frozen=True, slots=True)
class ChatRolePreparation:
    role: str
    database: str
    marker: str


def require_chat_role_replay(
    cursor: Cursor[tuple[object, ...]], spec: ChatRolePreparation, *, secret_exists: bool
) -> bool:
    cursor.execute(
        "SELECT d.description FROM pg_roles r LEFT JOIN pg_shdescription d "
        "ON d.objoid=r.oid AND d.classoid='pg_authid'::regclass WHERE r.rolname=%s",
        (spec.role,),
    )
    existing = cursor.fetchone()
    if existing is not None and (existing != (spec.marker,) or not secret_exists):
        raise ChatError("GENERAL_CHAT_ROLE_IDENTITY_CONFLICT")
    return existing is not None


def prepare_chat_role(
    cursor: Cursor[tuple[object, ...]], spec: ChatRolePreparation, *, password: str, exists: bool
) -> None:
    role = sql.Identifier(spec.role)
    if not exists:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(role, sql.Literal(password))
        )
        cursor.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(role, sql.Literal(spec.marker)))
    else:
        # Replay retains the existing credential; it is never rotated implicitly.
        cursor.execute(
            "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s",
            (spec.role,),
        )
        if cursor.fetchone() is not None:
            raise ChatError("GENERAL_CHAT_ROLE_IDENTITY_CONFLICT")
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(role)
        )
    cursor.execute(sql.SQL("ALTER ROLE {} SET search_path TO app, pg_catalog").format(role))
    cursor.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
            sql.Identifier(spec.database),
            role,
        )
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(spec.database),
            role,
        )
    )
    reconcile_chat_grants(cursor, role=spec.role)
