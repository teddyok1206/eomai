"""Native caller connection isolation is configuration, not a grant or role switch."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_orchestrator import database
from sqlalchemy.engine import make_url


def test_native_controller_reuses_existing_credential_with_exact_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "postgresql+psycopg://controller:example@127.0.0.1:5432/testdb"
    monkeypatch.setattr(database, "database_url", lambda: original)
    builder = Mock(return_value=object())
    monkeypatch.setattr(database, "build_engine", builder)
    assert database.build_native_embedding_controller_engine() is builder.return_value
    called = make_url(builder.call_args.args[0])
    assert called.difference_update_query(("options",)) == make_url(original)
    assert called.query == {"options": "-csearch_path=app,pg_catalog"}
    builder.assert_called_once()


@pytest.mark.parametrize(
    "value",
    (
        "sqlite:///testdb",
        "postgresql+psycopg2://controller:example@127.0.0.1/testdb",
        "postgresql+psycopg://controller:example@127.0.0.1/testdb?options=-csearch_path%3Dpublic",
        "postgresql+psycopg://controller:example@127.0.0.1/testdb?options=-crole%3Dother",
    ),
)
def test_native_controller_rejects_foreign_driver_or_implicit_connection_options(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr(database, "database_url", lambda: value)
    builder = Mock()
    monkeypatch.setattr(database, "build_engine", builder)
    with pytest.raises(ValueError, match=r"^NATIVE_EMBEDDING_CONTROLLER_CONNECTION_INVALID$"):
        database.build_native_embedding_controller_engine()
    builder.assert_not_called()
