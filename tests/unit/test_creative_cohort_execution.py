"""Sequential canaries prove read closure before advancing the next source."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_catalog_service import creative_cohort_execution as execution
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.models import ItemRevisionRecord
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_creative_learning_cohort import cohort_value
from tests.unit.test_creative_registered_report import proposal


def execution_case(monkeypatch, *, state="COMPLETED", missing_notes=False):
    cohort = CreativeLearningCohort.model_validate(cohort_value())
    resolved, lineage = proposal()
    registered = NS(
        item_id="item_" + "2" * 32, item_revision_id="itemrev_" + "3" * 32, lineage=lineage
    )
    revision = NS(
        item_id=registered.item_id,
        item_revision_id=registered.item_revision_id,
        manifest_sha256="sha256:" + "4" * 64,
    )
    workflow = NS(state=state)
    rows = {
        WorkflowInstanceRecord: workflow,
        ItemRevisionRecord: revision,
        KnowledgeGraphSnapshotRecord: NS(snapshot_sha256="sha256:" + "5" * 64),
    }
    session = NS(get=lambda model, _id: rows[model])

    class Sessions:
        def __call__(self):
            return nullcontext(session)

        def begin(self):
            return nullcontext(session)

    service = object.__new__(execution.CreativeCohortExecutionService)
    service.sessions = Sessions()
    service.cohort = cohort
    service.targets = cohort.targets
    service.cursor = 0
    service.selection = service.registered = service.analysis_run_id = None
    service.started = False
    service.preparation = NS(prepare=Mock(return_value=resolved.selection), source=object())
    service.publisher = object()
    service.registration = NS(register_completed=Mock(return_value=registered))
    service.learning = NS(
        advance=Mock(
            return_value=NS(
                analysis_run_id="analysisrun_" + "6" * 32,
                analysis_state="ACCEPTED",
                graph_snapshot_revision_id="graphrev_" + "7" * 32,
            )
        )
    )
    service.read = NS(
        resolve=Mock(
            return_value=NS(
                context=NS(
                    sources=(
                        NS(
                            kind="SOLUTION_REPORT",
                            pointer=lineage.role_result,
                            text="" if missing_notes else " ".join(lineage.warning_codes),
                        ),
                    )
                )
            )
        )
    )
    start = Mock()
    monkeypatch.setattr(execution, "start_prepared_external_item_learning", start)
    return NS(**locals())


def test_warning_bearing_source_is_verified_only_after_official_report_read(monkeypatch):
    case = execution_case(monkeypatch)
    result = case.service.advance_once()
    assert result.state == "VERIFIED" and result.verified_count == 1
    assert result.graph_snapshot_revision_id == "graphrev_" + "7" * 32
    assert case.lineage.warning_codes == ("ANSWER_DISAGREEMENT",)
    case.service.read.resolve.assert_called_once()
    case.start.assert_not_called()
    assert case.service.selection is None  # next target is not started in this tick


def test_missing_report_warning_does_not_advance_or_start_another_source(monkeypatch):
    case = execution_case(monkeypatch, missing_notes=True)
    with pytest.raises(ValueError, match="READ_NOTES_MISSING"):
        case.service.advance_once()
    assert case.service.cursor == 0
    case.start.assert_not_called()


def test_waiting_for_existing_extraction_does_not_reenqueue_on_each_observation(monkeypatch):
    case = execution_case(monkeypatch, state="RUNNING")
    for _ in range(10):
        assert case.service.advance_once().state == "EXTRACTING"
    case.start.assert_called_once()
    case.service.preparation.prepare.assert_called_once()
    case.service.registration.register_completed.assert_not_called()


def test_historical_worker_failure_is_not_accepted_or_recreated(monkeypatch):
    case = execution_case(monkeypatch, state="FAILED")
    with pytest.raises(ValueError, match="TERMINAL_FAILURE"):
        case.service.advance_once()
    assert case.workflow.state == "FAILED"
    case.start.assert_not_called()
    case.service.registration.register_completed.assert_not_called()
