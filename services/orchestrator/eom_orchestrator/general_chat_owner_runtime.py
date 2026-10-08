"""Explicit installed owner configuration and read-only DB-role admission."""

from __future__ import annotations

import os
import pwd
import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from eom_orchestrator.general_chat_privileges import chat_privileges_ready, chat_role_boundary_ready
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

OWNER_USER = "eom-general-chat"
OWNER_DATABASE_ROLE = "eom_general_chat_runtime"


def require_chat_owner_identity() -> None:
    try:
        owner = pwd.getpwnam(OWNER_USER)
        if os.geteuid() != owner.pw_uid:
            raise ValueError()
    except (KeyError, ValueError):
        raise ChatError("GENERAL_CHAT_OWNER_NOT_READY") from None


@dataclass(frozen=True, slots=True)
class ChatOwnerConfiguration:
    database_url: URL
    source_commit: str
    model: str

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> ChatOwnerConfiguration:
        try:
            # No fallback to the Orchestrator/admin/global database credentials.
            url = make_url(values["EOM_GENERAL_CHAT_DATABASE_URL"])
            commit = values["EOM_RUNTIME_SOURCE_COMMIT"]
            model = values["EOM_GENERAL_CHAT_MODEL"]
            if (
                url.drivername != "postgresql+psycopg"
                or url.username != OWNER_DATABASE_ROLE
                or url.host != "127.0.0.1"
                or url.port != 5432
                or not url.database
                or not url.password
                or url.query
                or re.fullmatch(r"[0-9a-f]{40}", commit) is None
                or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", model) is None
            ):
                raise ValueError()
            return cls(url, commit, model)
        except (KeyError, ValueError):
            raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID") from None


def chat_owner_engine(config: ChatOwnerConfiguration, *, pool_size: int) -> Engine:
    return create_engine(
        config.database_url,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=20,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=20000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=60000 -c search_path=app,public",
        },
    )


def require_chat_owner_database(engine: Engine) -> None:
    with engine.connect() as connection:
        identity = connection.execute(
            text(
                "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolreplication, "
                "rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        revision = connection.execute(
            text("SELECT version_num FROM app.alembic_version")
        ).scalar_one()
        if (
            identity[0] != OWNER_DATABASE_ROLE
            or any(identity[1:])
            or revision != CURRENT_MIGRATION_REVISION
            or not chat_role_boundary_ready(connection, role=OWNER_DATABASE_ROLE)
            or not chat_privileges_ready(connection, role=OWNER_DATABASE_ROLE)
        ):
            raise ChatError("GENERAL_CHAT_OWNER_DATABASE_NOT_READY")
