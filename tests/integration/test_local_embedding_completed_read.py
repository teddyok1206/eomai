"""Canonical completion replay in actual PG; numerical backend/IAM are synthetic."""

import pytest
from eom_orchestrator.models import JobRecord
from eom_workflow_runner import local_embedding_completed_read as application
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import func, select

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.mark.parametrize(
    "execution", ["operator", "service", "public", "registered_public"], indirect=True
)
def test_actual_completed_read_replays_all_released_families_without_encoding(
    execution, monkeypatch
):
    value = execution
    # Reuse this fixture's explicit synthetic IAM/source owner. Canonical launch,
    # coordinator, committed receipt, registration and transaction reads are real.
    monkeypatch.setattr(application, "CatalogLocalEmbeddingOwnerAdmission", type(value.owner))
    started = value.start()
    assert value.advance(*started) is True
    value.finish(*started)
    with value.sessions.begin() as session:
        count_before = session.scalar(select(func.count()).select_from(JobRecord))
        workflow = session.get(WorkflowInstanceRecord, started[0].workflow_id)
        first = application.read_completed_local_embedding(session, value.owner, workflow)
        second = application.read_completed_local_embedding(session, value.owner, workflow)
        assert first == second
        assert first.workflow_id == workflow.workflow_id
        assert session.scalar(select(func.count()).select_from(JobRecord)) == count_before
    assert value.launcher.forwards == 1
    value.current.allowed = False
    with value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, started[0].workflow_id)
        with pytest.raises(AssertionError):
            application.read_completed_local_embedding(session, value.owner, workflow)
    assert value.launcher.forwards == 1
