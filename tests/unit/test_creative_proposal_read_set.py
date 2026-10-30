"""Fixed-query metadata capture is not permission to skip original completion checks."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service.creative_learning_proposal import (
    CreativeLearningProposalError,
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.creative_proposal_read_set import capture_creative_proposal_read_set
from sqlalchemy.dialects.postgresql import dialect

from tests.unit.test_creative_proposal_resolution_v2 import _case


def captured_case(monkeypatch):
    value = _case(monkeypatch)
    value.artifact.revision_id = value.job.revision_id
    value.session.in_nested_transaction.return_value = False
    value.session.get_transaction.return_value = NS(is_active=True)
    value.session.get_nested_transaction.return_value = None
    value.session.scalars.side_effect = [
        (value.workflow,),
        (value.step,),
        (value.row,),
        (value.job,),
        (value.artifact,),
    ]
    read_set = capture_creative_proposal_read_set(value.session, (value.selection,))
    return value, read_set


def test_captured_resolution_performs_five_indexed_queries_and_no_per_item_get(monkeypatch):
    value, read_set = captured_case(monkeypatch)
    result = resolve_completed_creative_learning_proposal(
        value.session, value.artifacts, value.selection, read_set=read_set
    )
    assert result.selection == value.selection and result.role.job_id == value.job.job_id
    assert value.session.scalars.call_count == 5
    value.session.get.assert_not_called()
    for ordinal, call in enumerate(value.session.scalars.call_args_list):
        sql = str(call.args[0].compile(dialect=dialect()))
        assert "ORDER BY" in sql and " IN " in sql
        assert ("FOR SHARE" in sql) == (ordinal in (0, 1, 3))


@pytest.mark.parametrize("state", ["FAILED", "RUNNING", "CANCELLED"])
def test_captured_job_does_not_override_the_original_completion_guard(monkeypatch, state):
    value, read_set = captured_case(monkeypatch)
    value.job.status = state
    with pytest.raises(CreativeLearningProposalError, match="RESULT_POINTER_INVALID"):
        resolve_completed_creative_learning_proposal(
            value.session, value.artifacts, value.selection, read_set=read_set
        )


@pytest.mark.parametrize("change", ["session", "transaction", "thread", "selection", "nested"])
def test_read_set_cannot_be_reused_after_its_exact_root_scope(monkeypatch, change):
    value, read_set = captured_case(monkeypatch)
    session, selection = value.session, value.selection
    if change == "session":
        session = Mock()
    elif change == "transaction":
        value.session.get_transaction.return_value = NS(is_active=True)
    elif change == "thread":
        read_set = replace(read_set, _thread=-1)
    elif change == "selection":
        selection = selection.model_copy(update={"work_input_sha256": "sha256:" + "e" * 64})
    else:
        value.session.get_nested_transaction.return_value = NS(is_active=True)
    with pytest.raises(ValueError, match="READ_SET_INVALID"):
        read_set.for_selection(session, selection)


@pytest.mark.parametrize("count", [0, 2, 17])
def test_invalid_duplicate_or_over_budget_capture_has_no_sql(monkeypatch, count):
    value = _case(monkeypatch)
    value.session.in_nested_transaction.return_value = False
    with pytest.raises(ValueError, match="READ_SET_INVALID"):
        capture_creative_proposal_read_set(value.session, (value.selection,) * count)
    value.session.scalars.assert_not_called()


def test_matching_active_savepoint_is_allowed_but_not_reusable_after_it_exits(monkeypatch):
    value, _ = captured_case(monkeypatch)
    savepoint = NS(is_active=True)
    value.session.get_nested_transaction.return_value = savepoint
    value.session.scalars.side_effect = [
        (value.workflow,),
        (value.step,),
        (value.row,),
        (value.job,),
        (value.artifact,),
    ]
    read_set = capture_creative_proposal_read_set(value.session, (value.selection,))
    assert read_set.for_selection(value.session, value.selection).job is value.job
    value.session.get_nested_transaction.return_value = None
    with pytest.raises(ValueError, match="READ_SET_INVALID"):
        read_set.for_selection(value.session, value.selection)
