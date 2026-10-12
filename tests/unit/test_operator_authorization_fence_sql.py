"""Read-only SQL-shape/security tests; never install a routine or connect to PostgreSQL."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_BODY,
    OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
    OPERATOR_AUTHORIZATION_FENCE_CALL_SQL,
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE,
    OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL,
    OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
    OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    require_operator_authorization_fence_installation,
)
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
    "iam_privileges_ok",
)
OWNER = OperatorAuthorizationFenceOwnerPin("synthetic_owner", 12345)
ROOT = Path(__file__).resolve().parents[2]


class SyntheticResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> SyntheticResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def one(self) -> dict[str, object]:
        assert len(self.rows) == 1
        return self.rows[0]


class SyntheticInspectionConnection:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.rows: list[dict[str, object]] = [{field: True for field in FIELDS}]
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: SQLAlchemyError | None = None

    def execute(self, statement: object, parameters: dict[str, object]) -> SyntheticResult:
        self.calls.append((str(statement), parameters))
        if self.error is not None:
            raise self.error
        return SyntheticResult(self.rows)


def test_fixed_routine_body_signature_and_null_behavior_are_pinned() -> None:
    assert (
        OPERATOR_AUTHORIZATION_FENCE_SIGNATURE == "public.eom_fence_operator_authorization_v1(text)"
    )
    assert (
        OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256
        == "sha256:df9f676d1cb4c587598ee81d22c68a7a21b81deb0e4da28aa01e26c446fa9801"
    )
    assert (
        hashlib.sha256(OPERATOR_AUTHORIZATION_FENCE_BODY.encode()).hexdigest()
        == OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256[7:]
    )
    assert OPERATOR_AUTHORIZATION_FENCE_BODY.startswith(
        "\n"
    ) and OPERATOR_AUTHORIZATION_FENCE_BODY.endswith("\n")
    for required in (
        "FOR SHARE",
        "FROM app.operators",
        "requested_operator_id IS NULL",
        "octet_length",
        "IF NOT FOUND",
        "RETURN;",
    ):
        assert required in OPERATOR_AUTHORIZATION_FENCE_BODY
    for forbidden in (
        "FOR KEY SHARE",
        "SKIP LOCKED",
        "EXECUTE ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "COMMIT",
        "EXCEPTION WHEN",
        "pg_advisory",
        "api_sessions",
        "password_hash",
    ):
        assert forbidden not in OPERATOR_AUTHORIZATION_FENCE_BODY
    for required in (
        "CREATE FUNCTION public.",
        "RETURNS pg_catalog.void",
        "SECURITY DEFINER",
        "VOLATILE",
        "PARALLEL UNSAFE",
        "CALLED ON NULL INPUT",
        "SET search_path TO pg_catalog, pg_temp",
    ):
        assert required in OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL
    assert "OR REPLACE" not in OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL
    assert OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL.count(OPERATOR_AUTHORIZATION_FENCE_BODY) == 1
    assert OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL.endswith("FROM PUBLIC")
    assert OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL.endswith("TO eom_catalog_manager_runtime")
    assert "GRANT EXECUTE" in OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL
    assert (
        OPERATOR_AUTHORIZATION_FENCE_CALL_SQL
        == "SELECT public.eom_fence_operator_authorization_v1("
        "CAST(:operator_id AS pg_catalog.text))"
    )


def test_exact_read_only_inspection_and_fixed_execute_role() -> None:
    connection = SyntheticInspectionConnection()
    require_operator_authorization_fence_installation(cast(Connection, connection), OWNER)
    assert len(connection.calls) == 1
    sql, parameters = connection.calls[0]
    assert sql.lstrip().startswith("SELECT") and sql.rstrip().endswith("LIMIT 2")
    assert parameters == {
        "owner_oid": 12345,
        "owner_name": "synthetic_owner",
        "execute_role": "eom_catalog_manager_runtime",
        "expected_body": OPERATOR_AUTHORIZATION_FENCE_BODY,
    }
    assert OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE == "eom_catalog_manager_runtime"
    for rule in (
        "procedure.proowner = :owner_oid",
        "application.nspowner = :owner_oid",
        "operator_table.relowner = :owner_oid",
        "procedure.prosrc = :expected_body",
        "count(*) = 2",
        "count(DISTINCT acl.grantee) = 2",
        "acl.grantor = :owner_oid",
        "NOT acl.is_grantable",
        "schema_acl.grantee NOT IN",
        "pg_auth_members",
        "has_any_column_privilege",
        "operator_credentials",
        "api_sessions",
        "api_tokens",
        "procedure.prosupport = 0",
        "NOT operator_table.relrowsecurity",
    ):
        assert rule in sql
    assert "SELECT procedure.prosrc" not in sql
    assert "GRANT " not in sql and "REVOKE " not in sql


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("bad", [False, None, 1, "true"])
def test_security_metadata_not_exact_true_is_unavailable(field: str, bad: object) -> None:
    connection = SyntheticInspectionConnection()
    connection.rows[0][field] = bad
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
    ):
        require_operator_authorization_fence_installation(cast(Connection, connection), OWNER)


@pytest.mark.parametrize("shape", ["absent", "overload", "extra", "missing"])
def test_missing_extra_or_wrong_installed_metadata_is_unavailable(shape: str) -> None:
    connection = SyntheticInspectionConnection()
    if shape == "absent":
        connection.rows = []
    elif shape == "overload":
        connection.rows *= 2
    elif shape == "extra":
        connection.rows[0]["synthetic_secret_marker"] = True
    elif shape == "missing":
        del connection.rows[0][FIELDS[0]]
    with pytest.raises(OperatorAuthorizationFenceError) as caught:
        require_operator_authorization_fence_installation(cast(Connection, connection), OWNER)
    assert str(caught.value) == "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
    assert "synthetic_secret_marker" not in str(caught.value)


@pytest.mark.parametrize(
    "name,oid",
    [
        ("", 1),
        ("catalog; DROP", 1),
        ("eom_catalog_manager_runtime", 1),
        ("synthetic_owner", True),
        ("synthetic_owner", 0),
        ("synthetic_owner", 4294967296),
    ],
)
def test_owner_pin_is_small_exact_value_not_an_arbitrary_role_grant(name: str, oid: Any) -> None:
    with pytest.raises(OperatorAuthorizationFenceError):
        OperatorAuthorizationFenceOwnerPin(name, oid)


def test_backend_error_is_redacted_and_sqlite_cannot_pass_inspection() -> None:
    connection = SyntheticInspectionConnection()
    connection.error = SQLAlchemyError("synthetic-secret-marker")
    with pytest.raises(OperatorAuthorizationFenceError) as caught:
        require_operator_authorization_fence_installation(cast(Connection, connection), OWNER)
    assert str(caught.value) == "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
    connection.dialect.name = "sqlite"
    connection.calls.clear()
    with pytest.raises(OperatorAuthorizationFenceError):
        require_operator_authorization_fence_installation(cast(Connection, connection), OWNER)
    assert not connection.calls


def test_sql_module_has_no_install_side_effect_or_cross_private_catalog_import() -> None:
    source = (
        ROOT / "services/identity_service/eom_identity_service/operator_authorization_fence_sql.py"
    )
    tree = ast.parse(source.read_text())
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"eom_catalog_service", "eom_workflow_runner", "subprocess", "psycopg"}
    functions = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert [node.name for node in functions] == [
        "require_operator_authorization_fence_installation"
    ]
