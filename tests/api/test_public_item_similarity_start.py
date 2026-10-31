"""Real Item transaction/START and replay; current controls/QUERY/source are synthetic.

SQLite does not qualify PostgreSQL constraints, native execution or live IAM.
"""

import pytest
from eom_api.errors import ApiError
from eom_api.services.item_similarity_start import (
    PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
)
from eom_catalog_contracts.knowledge import EducationalRetrievalRequirementV2
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from sqlalchemy import func, select

from tests.api.test_item_similarity_start import KEY
from tests.api.test_item_similarity_start import start_case as start_case
from tests.unit.public_item_start_fixtures import promote_public_source


@pytest.fixture(params=(False, True))
def public_case(start_case, request, tmp_path, monkeypatch):
    ordinary = not isinstance(
        start_case.source.request.educational_retrieval, EducationalRetrievalRequirementV2
    )
    value = promote_public_source(
        start_case, tmp_path, monkeypatch, ordinary=ordinary, registered=request.param
    )
    start_case.prepared = value.prepared
    return start_case


@pytest.mark.parametrize("start_case", (False, True), indirect=True)
def test_public_start_atomically_persists_exact_plan_family_and_acceptance2_then_replays_one_start(
    public_case,
):
    value = public_case
    first = value.adapter.start_workflow(
        value.request, value.actor, idempotency_key=KEY, prepared_similarity=value.prepared
    )
    assert (
        value.adapter.start_workflow(
            value.request, value.actor, idempotency_key=KEY, prepared_similarity=value.prepared
        )
        == first
    )
    with value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, first[1])
        record = session.get(
            ResolvedExecutionPlanRecord, workflow.runtime_context["execution_plan"]["plan_id"]
        )
        version = (
            30
            if isinstance(
                value.source.request.educational_retrieval, EducationalRetrievalRequirementV2
            )
            else 31
        )
        assert record.canonical_document["schema_version"] == f"resolved-execution-plan/{version}.0"
        assert PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY in workflow.runtime_context
        assert SIMILARITY_PREPARATION_ACCEPTANCE_KEY not in workflow.runtime_context
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 1


@pytest.mark.parametrize("start_case", (False, True), indirect=True)
def test_error_after_actual_plan_flush_rolls_back_item_and_start_before_same_key_retry(
    public_case, monkeypatch
):
    value = public_case
    from eom_api.services import command_adapter as module

    original = module.similarity_start_context

    def interrupted(*arguments):
        raise ApiError(503, "TEST_INTERRUPTED", "synthetic interruption", "after plan flush")

    monkeypatch.setattr(module, "similarity_start_context", interrupted)
    with pytest.raises(ApiError):
        value.adapter.start_workflow(
            value.request, value.actor, idempotency_key=KEY, prepared_similarity=value.prepared
        )
    with value.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ResolvedExecutionPlanRecord)) == 0
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 0
    monkeypatch.setattr(module, "similarity_start_context", original)
    assert value.adapter.start_workflow(
        value.request, value.actor, idempotency_key=KEY, prepared_similarity=value.prepared
    )[1].startswith("workflow_")
