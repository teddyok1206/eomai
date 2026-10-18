"""Bound-root/SQL decisions with declared connection observations, no installed authority."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identity_service import OperatorAuthorizationFenceError, OperatorAuthorizationFenceOwnerPin
from eom_identity_service.owned_operator_authorization_fence import OwnedOperatorAuthorizationFence
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ACTOR = "operator_" + "a" * 32


@pytest.fixture
def case():
    root = SimpleNamespace(is_active=True)
    session = Mock(spec=Session)
    session.get_transaction.return_value = root
    session.is_active = True
    session.in_nested_transaction.return_value = False
    session.new, session.dirty, session.deleted = set(), set(), set()
    session.no_autoflush = nullcontext()
    connection = session.connection.return_value
    connection.dialect.name = "postgresql"
    connection.invalidated = False
    connection.in_transaction.return_value = True
    connection.get_execution_options.return_value = {}
    connection.engine.get_execution_options.return_value = {}
    connection.connection.driver_connection.autocommit = False
    connection.get_isolation_level.return_value = "READ COMMITTED"
    waits = dict(
        lock_timeout="2s", statement_timeout="3s", lock_timeout_ms=2000, statement_timeout_ms=3000
    )
    context = dict(
        role_name="eom_app",
        session_role_name="eom_app",
        role_oid=42,
        table_owner_oid=42,
        schema_owner_oid=42,
        superuser=False,
        bypassrls=False,
        isolation="read committed",
        read_only="off",
        schemas=["app", "pg_catalog"],
        temp_schema=0,
    )

    def execute(statement, *_args):
        value = waits if "lock_timeout_ms" in str(statement) else context
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: value))

    connection.execute.side_effect = execute
    row = SimpleNamespace(
        operator_id=ACTOR, status="ACTIVE", deleted_at=None, must_change_password=False
    )
    session.scalar.return_value = row
    return SimpleNamespace(
        session=session,
        connection=connection,
        root=root,
        waits=waits,
        context=context,
        row=row,
        fence=OwnedOperatorAuthorizationFence(
            OperatorAuthorizationFenceOwnerPin("eom_app", 42), ACTOR
        ),
    )


def test_rechecks_bound_target_with_share_lock_and_restores_stricter_waits(case):
    case.fence.fence_current_operator(case.session, ACTOR)
    statement = case.session.scalar.call_args.args[0]
    assert statement._for_update_arg.read is True
    assert statement.get_execution_options()["populate_existing"] is True
    calls = case.connection.execute.call_args_list
    assert calls[1].args[1] == {"lock_timeout": "2000ms", "statement_timeout": "3000ms"}
    assert calls[-1].args[1] == {"lock_timeout": "2s", "statement_timeout": "3s"}
    case.session.commit.assert_not_called()
    case.session.rollback.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("role_name", "other"),
        ("session_role_name", "other"),
        ("role_oid", 43),
        ("role_oid", True),
        ("table_owner_oid", 43),
        ("schema_owner_oid", 43),
        ("superuser", True),
        ("bypassrls", True),
        ("isolation", "repeatable read"),
        ("read_only", "on"),
        ("schemas", ["app", "public"]),
        ("temp_schema", 1),
    ),
)
def test_untrusted_owner_or_root_context_is_denied_before_target_read(case, field, value):
    case.context[field] = value
    with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
        case.fence.fence_current_operator(case.session, ACTOR)
    case.session.scalar.assert_not_called()


@pytest.mark.parametrize(
    "fault", ("absent", "inactive", "nested", "pending", "dirty", "deleted", "actor")
)
def test_invalid_root_or_actor_is_rejected_before_any_sql(case, fault):
    actor = ACTOR
    if fault == "absent":
        case.session.get_transaction.return_value = None
    elif fault == "inactive":
        case.root.is_active = False
    elif fault == "nested":
        case.session.in_nested_transaction.return_value = True
    elif fault == "actor":
        actor = "operator_" + "b" * 32
    else:
        setattr(case.session, {"pending": "new"}.get(fault, fault), {object()})
    with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
        case.fence.fence_current_operator(case.session, actor)
    case.session.connection.assert_not_called()


@pytest.mark.parametrize("fault", ("missing", "disabled", "deleted", "password", "wrong_actor"))
def test_current_target_state_cannot_be_reused_as_prior_success(case, fault):
    case.fence.fence_current_operator(case.session, ACTOR)
    if fault == "missing":
        case.session.scalar.return_value = None
    elif fault == "disabled":
        case.row.status = "DISABLED"
    elif fault == "deleted":
        case.row.deleted_at = datetime.now(UTC)
    elif fault == "password":
        case.row.must_change_password = True
    else:
        case.row.operator_id = "operator_" + "b" * 32
    with pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"):
        case.fence.fence_current_operator(case.session, ACTOR)
    assert case.session.scalar.call_count == 2


@pytest.mark.parametrize("value", (-1, True, "untrusted"))
def test_invalid_wait_metadata_is_not_interpreted_as_unlimited(case, value):
    case.waits["lock_timeout_ms"] = value
    with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
        case.fence.fence_current_operator(case.session, ACTOR)
    case.session.scalar.assert_not_called()


def test_database_error_is_redacted_and_does_not_commit_or_retry(case):
    case.connection.execute.side_effect = SQLAlchemyError("DO_NOT_DISCLOSE_DATABASE_URL")
    with pytest.raises(OperatorAuthorizationFenceError) as error:
        case.fence.fence_current_operator(case.session, ACTOR)
    assert str(error.value) == "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
    assert case.connection.execute.call_count == 1
    case.session.commit.assert_not_called()
    case.session.rollback.assert_not_called()
