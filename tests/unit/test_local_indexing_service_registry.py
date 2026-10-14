"""Frozen DDL and non-DB ownership/input boundaries; no installed service grant."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_identity_service import register_local_indexing_service
from eom_identity_service.local_indexing_service_models import (
    LocalIndexingServiceEventRecord,
    LocalIndexingServiceRecord,
    LocalIndexingServiceRevisionRecord,
)
from eom_operator_identity import LocalIndexingServiceError, LocalIndexingServiceErrorCode
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import Table, create_engine
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import Session
from sqlalchemy.schema import AddConstraint, CreateTable

from tests.unit.test_local_indexing_service_contracts import identity

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20261014_0055_local_indexing_identity.py"
TABLES = tuple(
    cast(Table, model.__table__)
    for model in (
        LocalIndexingServiceRecord,
        LocalIndexingServiceRevisionRecord,
        LocalIndexingServiceEventRecord,
    )
)


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guarded_local_indexing_identity", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOperations:
    def __init__(self, *, refuse: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.refuse = refuse

    def execute(self, sql: str) -> None:
        self.calls.append(("execute", sql))
        if self.refuse:
            raise ValueError("synthetic history refusal")

    def drop_constraint(self, name: str, _table: str, **_: Any) -> None:
        self.calls.append(("constraint", name))

    def drop_table(self, name: str) -> None:
        self.calls.append(("table", name))


def test_frozen_ddl_matches_columns_constraints_and_explicit_head_fks() -> None:
    normalized = {"".join(statement.split()) for statement in migration()._DDL}
    for table in TABLES:
        assert "".join(str(CreateTable(table).compile(dialect=dialect())).split()) in normalized
        assert all(str(column.type) not in {"JSONB", "BYTEA", "BLOB", "TEXT"} for column in table.c)
        assert len(table.name.encode()) <= 63
        for constraint in table.constraints:
            if constraint.name:
                assert len(constraint.name.encode()) <= 63
    for fk in TABLES[0].foreign_key_constraints:
        assert fk.deferrable and fk.initially == "DEFERRED" and fk.use_alter
        assert "".join(str(AddConstraint(fk).compile(dialect=dialect())).split()) in normalized
    source = MIGRATION.read_text()
    assert not any(
        (node.module or "").startswith("eom_")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    )
    assert "GRANT" not in source and "UPDATE workflow" not in source
    assert "expected_resource_version IS NOT NULL" in source


def test_registry_migration_is_registered_under_the_current_schema_head() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [CURRENT_MIGRATION_REVISION]
    assert scripts.get_revision("20261014_0055") is not None
    assert migration().down_revision == "20261013_0054"
    assert (
        "import eom_identity_service.local_indexing_service_models"
        in (ROOT / "migrations/env.py").read_text()
    )


def test_downgrade_refuses_history_before_any_ddl(monkeypatch: pytest.MonkeyPatch) -> None:
    module = migration()
    recording = RecordingOperations(refuse=True)
    monkeypatch.setattr(module, "op", recording)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert len(recording.calls) == 1
    for table in TABLES:
        assert f"FROM {table.name}" in recording.calls[0][1]
    recording = RecordingOperations()
    monkeypatch.setattr(module, "op", recording)
    module.downgrade()
    assert [kind for kind, _ in recording.calls] == [
        "execute",
        "constraint",
        "constraint",
        "table",
        "table",
        "table",
        "execute",
        "execute",
    ]


def test_no_implicit_root_or_non_postgres_fallback() -> None:
    with Session() as session, pytest.raises(LocalIndexingServiceError) as error:
        register_local_indexing_service(session, identity(), operation_key="synthetic:invalid-root")
    assert error.value.code == LocalIndexingServiceErrorCode.CONTEXT_INVALID
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session, session.begin():
            with pytest.raises(LocalIndexingServiceError) as error:
                register_local_indexing_service(
                    session, identity(), operation_key="synthetic:wrong-db"
                )
            assert error.value.code == LocalIndexingServiceErrorCode.CONTEXT_INVALID
    finally:
        engine.dispose()


def test_disposable_purpose_follows_owner_guard_without_privileged_or_runtime_fallback() -> None:
    source = (ROOT / "scripts/api/testdb_run.sh").read_text()
    start = source.index('if [[ "${action}" == "local-indexing-service-tests" ]]')
    assert source.index("validate_state_directory(") < start
    assert source.index("validate_application_schema_metadata(") < start
    leaf = source[start : source.index('if [[ "${action}" == "embedding-stage-tests" ]]')]
    assert "EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION=1" in leaf
    assert 'EOM_API_TEST_STATE="${state_directory}"' in leaf
    assert "tests/integration/test_local_indexing_service_registry.py" in leaf
    assert not any(value in leaf for value in ("sudo", "source ", "psql", "owner.env"))


@pytest.mark.parametrize("owner", [None, object(), {"role_name": "eom_app", "role_oid": 1}])
def test_fixed_fence_installation_rejects_untyped_owner_before_db(owner) -> None:
    from eom_identity_service import LocalIndexingFenceError, install_local_indexing_service_fence

    with (
        Session() as session,
        pytest.raises(LocalIndexingFenceError, match="CONFIGURATION_INVALID"),
    ):
        install_local_indexing_service_fence(session, owner)


def test_fixed_fence_installation_reuses_explicit_postgres_owner_root() -> None:
    from eom_identity_service import (
        LocalIndexingFenceOwnerPin,
        install_local_indexing_service_fence,
    )

    owner = LocalIndexingFenceOwnerPin("synthetic_owner", 12001)
    with Session() as session, pytest.raises(LocalIndexingServiceError) as caught:
        install_local_indexing_service_fence(session, owner)
    assert caught.value.code == LocalIndexingServiceErrorCode.CONTEXT_INVALID
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with (
            Session(engine) as session,
            session.begin(),
            pytest.raises(LocalIndexingServiceError) as caught,
        ):
            install_local_indexing_service_fence(session, owner)
        assert caught.value.code == LocalIndexingServiceErrorCode.CONTEXT_INVALID
    finally:
        engine.dispose()
