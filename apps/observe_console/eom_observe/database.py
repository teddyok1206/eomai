"""Small PostgreSQL pool configured for short read-only transactions."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def build_readonly_engine(database_url: str, query_timeout_ms: int) -> Engine:
    options = (
        "-c default_transaction_read_only=on "
        f"-c statement_timeout={query_timeout_ms} "
        "-c idle_in_transaction_session_timeout=3000"
    )
    return create_engine(
        database_url,
        pool_size=3,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"options": options, "application_name": "eom-observe"},
    )
