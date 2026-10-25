"""Actual-owner admission shape with synthetic SQL leaves; no DB or root privilege proof."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow_runner.native_workflow_maintenance_authority import (
    ALLOCATED_MAINTENANCE_TABLES,
    WORKFLOW_MAINTENANCE_TABLES,
    NativeWorkflowMaintenanceAuthorityError,
    require_native_workflow_maintenance_owner,
)
from sqlalchemy.orm import Session


def owner_session(tables):
    session = Mock(spec=Session)
    session.get_transaction.return_value = SimpleNamespace(is_active=True)
    session.in_nested_transaction.return_value = False
    session.new, session.dirty, session.deleted = set(), set(), set()
    session.get_bind.return_value.dialect.name = "postgresql"
    principal = Mock()
    principal.one.return_value = ("synthetic_owner", "synthetic_owner", True, "read committed")
    owners = Mock()
    owners.all.return_value = [(name, "synthetic_owner") for name in tables]
    session.execute.side_effect = (principal, owners)
    return session, principal, owners


@pytest.mark.parametrize("tables", (WORKFLOW_MAINTENANCE_TABLES, ALLOCATED_MAINTENANCE_TABLES))
def test_only_actual_owner_of_exact_fixed_table_set_is_accepted(tables):
    session, _, _ = owner_session(tables)
    assert require_native_workflow_maintenance_owner(session, tables) == "synthetic_owner"
    assert session.execute.call_count == 2
    assert session.execute.call_args.args[1] == {"required_names": list(tables)}


@pytest.mark.parametrize(
    "fault", ("set_role", "missing", "foreign", "read_only", "isolation", "narrow")
)
def test_saved_role_or_partial_table_ownership_is_not_authority(fault):
    tables = ALLOCATED_MAINTENANCE_TABLES
    session, principal, owners = owner_session(tables)
    if fault == "set_role":
        principal.one.return_value = ("login_user", "synthetic_owner", True, "read committed")
    elif fault == "missing":
        owners.all.return_value = owners.all.return_value[:-1]
    elif fault == "foreign":
        owners.all.return_value = [
            (n, "other" if n == "job_events" else "synthetic_owner") for n in tables
        ]
    elif fault == "read_only":
        principal.one.return_value = ("synthetic_owner", "synthetic_owner", False, "read committed")
    elif fault == "isolation":
        principal.one.return_value = ("synthetic_owner", "synthetic_owner", True, "repeatable read")
    else:
        tables = ("jobs",)
    with pytest.raises(NativeWorkflowMaintenanceAuthorityError):
        require_native_workflow_maintenance_owner(session, tables)
    if fault == "narrow":
        session.execute.assert_not_called()
