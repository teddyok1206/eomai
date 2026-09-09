from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
)
from eom_orchestrator.preset_lifecycle import (
    deprecate_execution_preset,
    release_execution_preset,
)
from sqlalchemy.orm import Session


@pytest.mark.parametrize("publisher", ["capacity", "preset"])
def test_current_pointer_publisher_takes_learning_lock_before_row_lock(publisher: str) -> None:
    session = Mock(spec=Session)
    logical_result = Mock()
    session.execute.side_effect = [Mock(), logical_result]

    if publisher == "capacity":
        target_id = "capacityrev_" + "2" * 32
        logical = SimpleNamespace(current_revision_id=target_id)
        revision = SimpleNamespace(
            capacity_policy_id="capacity_" + "1" * 32,
            capacity_policy_revision_id=target_id,
            state="RELEASED",
        )
        logical_result.scalar_one_or_none.return_value = logical
        session.get.return_value = revision
        result = publish_capacity_policy_revision(
            cast(Any, session),
            capacity_policy_id=revision.capacity_policy_id,
            capacity_policy_revision_id=target_id,
        )
    else:
        target_id = "execpresetrev_" + "2" * 32
        logical = SimpleNamespace(current_revision_id=target_id)
        revision = SimpleNamespace(
            preset_id="execpreset_" + "1" * 32,
            preset_revision_id=target_id,
            state="RELEASED",
        )
        logical_result.scalar_one_or_none.return_value = logical
        session.get.return_value = revision
        result = publish_execution_preset_revision(
            cast(Any, session),
            preset_id=revision.preset_id,
            preset_revision_id=target_id,
        )

    assert result is revision
    assert session.execute.call_count == 2
    advisory_statement = str(session.execute.call_args_list[0].args[0])
    row_lock_statement = str(session.execute.call_args_list[1].args[0])
    advisory_parameters = session.execute.call_args_list[0].args[0].compile().params
    assert "pg_advisory_xact_lock" in advisory_statement
    assert LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID in advisory_parameters.values()
    assert "FOR UPDATE" in row_lock_statement


@pytest.mark.parametrize("operation", ["release", "deprecate"])
def test_preset_lifecycle_mutation_takes_learning_lock_before_row_lock(operation: str) -> None:
    session = Mock(spec=Session)
    advisory_result = Mock()
    logical_result = Mock()
    logical_result.scalar_one_or_none.return_value = None
    session.execute.side_effect = [advisory_result, logical_result]

    with pytest.raises(ControlPlaneError):
        if operation == "release":
            session.get.return_value = SimpleNamespace(
                state="DRAFT",
                preset_id="execpreset_" + "1" * 32,
            )
            release_execution_preset(
                cast(Any, session),
                draft_revision_id="execpresetrev_" + "2" * 32,
                released_by="operator_test",
                released_at=datetime.now(UTC),
            )
        else:
            deprecate_execution_preset(
                cast(Any, session),
                preset_id="execpreset_" + "1" * 32,
                deprecated_by="operator_test",
                deprecated_at=datetime.now(UTC),
            )

    assert session.execute.call_count == 2
    advisory = session.execute.call_args_list[0].args[0]
    row_lock = session.execute.call_args_list[1].args[0]
    assert "pg_advisory_xact_lock" in str(advisory)
    assert LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID in advisory.compile().params.values()
    assert "FOR UPDATE" in str(row_lock)
