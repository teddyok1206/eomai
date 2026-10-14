"""Read-only SQL admission tests; no real grant, installation or PostgreSQL connection."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identity_service import local_indexing_fence_sql as fence
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

FIELDS = (
    "owner_ok",
    "definition_ok",
    "body_ok",
    "acl_ok",
    "runtime_role_ok",
    "schema_ok",
    "execute_ok",
    "identity_privileges_ok",
)
OWNER = fence.LocalIndexingFenceOwnerPin("synthetic_owner", 12345)


class Result:
    def __init__(self, rows: list[dict[str, object]], scalar: object = None) -> None:
        self.rows, self.scalar = rows, scalar

    def mappings(self) -> Result:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def one(self) -> dict[str, object]:
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar_one(self) -> object:
        return self.scalar


class Inspection:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.rows: list[dict[str, object]] = [{name: True for name in FIELDS}]
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: SQLAlchemyError | None = None

    def execute(self, statement: object, parameters: dict[str, object]) -> Result:
        self.calls.append((str(statement), parameters))
        if self.error is not None:
            raise self.error
        return Result(self.rows)


def test_exact_definition_pins_and_no_mutation_or_dynamic_sql() -> None:
    assert fence.LOCAL_INDEXING_FENCE_SIGNATURE == (
        "public.eom_fence_local_indexing_service_v1(text,text,text,text)"
    )
    assert (
        "sha256:" + hashlib.sha256(fence.LOCAL_INDEXING_FENCE_BODY.encode()).hexdigest()
    ) == fence.LOCAL_INDEXING_FENCE_BODY_SHA256
    assert fence.LOCAL_INDEXING_FENCE_BODY_SHA256 == (
        "sha256:eba4706dc13f62c8546fd4d1dc7390179057d944da475720eefae2b6cd885c85"
    )
    for value in (
        "FOR SHARE",
        "requested_service_id IS NULL",
        "octet_length",
        "current_setting('role')",
        "pinned_identity.database_role <> SESSION_USER",
        "locked_head.state <> 'ACTIVE'",
        "locked_head.current_revision_id IS DISTINCT FROM requested_revision_id",
        "pinned_identity.content_sha256 <> requested_identity_sha256",
        "pinned_identity.runtime_source_commit <> requested_source_commit",
        "FROM app.local_indexing_services",
        "FROM app.local_indexing_service_revisions",
    ):
        assert value in fence.LOCAL_INDEXING_FENCE_BODY
    for value in (
        "FOR KEY SHARE",
        "SKIP LOCKED",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "EXECUTE ",
        "COMMIT",
        "EXCEPTION WHEN",
        "api_tokens",
        "operator_id",
        "password",
        "pg_advisory",
    ):
        assert value not in fence.LOCAL_INDEXING_FENCE_BODY
    for value in (
        "RETURNS pg_catalog.jsonb",
        "SECURITY DEFINER",
        "VOLATILE",
        "PARALLEL UNSAFE",
        "CALLED ON NULL INPUT",
        "SET search_path TO pg_catalog, pg_temp",
    ):
        assert value in fence.LOCAL_INDEXING_FENCE_CREATE_SQL
    assert "OR REPLACE" not in fence.LOCAL_INDEXING_FENCE_CREATE_SQL
    assert fence.LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL.endswith("FROM PUBLIC")
    assert fence.LOCAL_INDEXING_FENCE_GRANT_SQL.endswith("TO eom_catalog_manager_runtime")


def test_exact_read_only_bounded_inspection_and_no_identity_table_privilege() -> None:
    connection = Inspection()
    fence.require_local_indexing_fence_installation(cast(Connection, connection), OWNER)
    sql, values = connection.calls[0]
    assert sql.lstrip().startswith("SELECT") and sql.rstrip().endswith("LIMIT 2")
    assert values == {
        "owner_oid": 12345,
        "owner_name": "synthetic_owner",
        "expected_body": fence.LOCAL_INDEXING_FENCE_BODY,
        "execute_role": "eom_catalog_manager_runtime",
    }
    for value in (
        "count(DISTINCT acl.grantee) = 2",
        "NOT acl.is_grantable",
        "procedure.prosrc = :expected_body",
        "pg_auth_members",
        "NOT object.relrowsecurity",
        "count(object.oid) = 3",
        "local_indexing_service_events",
        "NOT pg_catalog.has_table_privilege",
        "NOT pg_catalog.has_any_column_privilege",
        "object.relowner = :owner_oid",
    ):
        assert value in sql
    assert "SELECT procedure.prosrc" not in sql and "GRANT " not in sql


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("invalid", [False, None, 1, "true"])
def test_any_nontrue_security_condition_denies(field: str, invalid: object) -> None:
    connection = Inspection()
    connection.rows[0][field] = invalid
    with pytest.raises(fence.LocalIndexingFenceError, match="UNAVAILABLE"):
        fence.require_local_indexing_fence_installation(cast(Connection, connection), OWNER)


@pytest.mark.parametrize("fault", ["absent", "overload", "extra", "missing", "error", "sqlite"])
def test_incomplete_or_untrusted_installation_is_not_admitted(fault: str) -> None:
    connection = Inspection()
    if fault == "absent":
        connection.rows = []
    elif fault == "overload":
        connection.rows *= 2
    elif fault == "extra":
        connection.rows[0]["SECRET_MARKER"] = True
    elif fault == "missing":
        del connection.rows[0][FIELDS[0]]
    elif fault == "error":
        connection.error = SQLAlchemyError("SECRET_MARKER")
    else:
        connection.dialect.name = "sqlite"
    with pytest.raises(fence.LocalIndexingFenceError) as caught:
        fence.require_local_indexing_fence_installation(cast(Connection, connection), OWNER)
    assert str(caught.value) == "LOCAL_INDEXING_FENCE_UNAVAILABLE"


@pytest.mark.parametrize(
    "name,oid",
    [
        ("", 1),
        ("bad; role", 1),
        ("eom_catalog_manager_runtime", 1),
        ("synthetic_owner", True),
        ("synthetic_owner", 0),
        ("synthetic_owner", 4294967296),
    ],
)
def test_owner_pin_cannot_select_invalid_or_runtime_definer(name: str, oid: Any) -> None:
    with pytest.raises(fence.LocalIndexingFenceError, match="CONFIGURATION_INVALID"):
        fence.LocalIndexingFenceOwnerPin(name, oid)
