"""Database engine and transaction helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.settings import database_url


def build_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def build_native_embedding_controller_engine() -> Engine:
    """Use the existing controller credential with the exact session-fence namespace.

    The ordinary runner retains its established app/public connection behavior.
    Native owner operations must not resolve unqualified identifiers via public;
    configure their own connection before any caller-root transaction starts.
    This changes neither database role/defaults nor privileges or IAM rows.
    """
    url = make_url(database_url())
    if url.get_backend_name() != "postgresql" or url.get_driver_name() != "psycopg":
        raise ValueError("NATIVE_EMBEDDING_CONTROLLER_CONNECTION_INVALID")
    if url.query.get("options") not in (None, "-csearch_path=app,pg_catalog"):
        raise ValueError("NATIVE_EMBEDDING_CONTROLLER_CONNECTION_INVALID")
    configured = url.update_query_dict({"options": "-csearch_path=app,pg_catalog"})
    return build_engine(configured.render_as_string(hide_password=False))


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory.begin() as session:
        yield session
