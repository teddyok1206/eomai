"""Sequential canaries prove read closure before advancing the next source."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_catalog_contracts.creative_learning_continuation import CreativeLearningExecutionScope
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_service import creative_cohort_execution as execution
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.models import ItemRevisionRecord
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_creative_learning_cohort import cohort_value
from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_execution_control_contracts import _preset


def _scope_pin_case(*, historical, logical_state="ACTIVE"):
    records, pins = {}, []
    for digit, purpose in (("1", "extract"), ("2", "analyse")):
        document = deepcopy(_preset())
        document.update(
            preset_id="execpreset_" + digit * 32, preset_revision_id="execpresetrev_" + digit * 32
        )
        document["content_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "content_sha256"}
        )
        row = NS(
            **{
                key: document[key]
                for key in (
                    "preset_id",
                    "preset_revision_id",
                    "state",
                    "revision_number",
                    "content_sha256",
                )
            },
            canonical_document=document,
        )
        logical = NS(state=logical_state, preset_key=purpose)
        records[ExecutionPresetRevisionRecord, row.preset_revision_id] = row
        records[ExecutionPresetRecord, row.preset_id] = logical
        pins.append(
            NS(
                preset_id=row.preset_id,
                preset_revision_id=row.preset_revision_id,
                sha256=row.content_sha256,
            )
        )
    scope = NS(
        cohort_id="previous" if historical else "current",
        extraction_preset=pins[0],
        analysis_preset=pins[1],
        extraction_preset_key="extract",
        analysis_preset_key="analyse",
        capacity_policy_revision_id=document["capacity_policy_revision_id"],
    )
    service = object.__new__(execution.CreativeCohortExecutionService)
    service.scope = NS(cohort_id="current")
    session = NS(get=lambda model, identity: records.get((model, identity)))
    return service, session, scope, records


@pytest.mark.parametrize(
    "historical,state", [(False, "ACTIVE"), (True, "ACTIVE"), (True, "RETIRED")]
)
def test_scope_pin_integrity_survives_historical_logical_retirement(historical, state):
    service, session, scope, _ = _scope_pin_case(historical=historical, logical_state=state)
    service._require_scope_pins(session, scope)


@pytest.mark.parametrize(
    "historical,state", [(False, "RETIRED"), (False, "UNKNOWN"), (True, "UNKNOWN")]
)
def test_history_read_does_not_authorize_retired_current_scope(historical, state):
    service, session, scope, _ = _scope_pin_case(historical=historical, logical_state=state)
    with pytest.raises(ValueError, match="CREATIVE_COHORT_PRESET_PIN_MISMATCH"):
        service._require_scope_pins(session, scope)


@pytest.mark.parametrize(
    "field", ["hash", "capacity", "key", "missing_revision", "missing_logical"]
)
def test_historical_preset_retirement_does_not_skip_pin_validation(field):
    service, session, scope, records = _scope_pin_case(historical=True, logical_state="RETIRED")
    pin = scope.analysis_preset
    if field == "hash":
        pin.sha256 = "sha256:" + "0" * 64
    elif field == "capacity":
        scope.capacity_policy_revision_id = "capacityrev_" + "0" * 32
    elif field == "key":
        scope.analysis_preset_key = "unrelated"
    elif field == "missing_revision":
        del records[ExecutionPresetRevisionRecord, pin.preset_revision_id]
    else:
        del records[ExecutionPresetRecord, pin.preset_id]
    with pytest.raises(ValueError, match="CREATIVE_COHORT_PRESET_PIN_MISMATCH"):
        service._require_scope_pins(session, scope)


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
    service.scope = CreativeLearningExecutionScope(cohort)
    service.targets = cohort.targets
    service.cursor = 0
    service.current = None
    service.preparation = NS(prepare=Mock(return_value=resolved.selection), source=object())
    service.publisher = object()
    service.registration = NS(
        register_completed=Mock(return_value=registered),
        find_registered_source=Mock(return_value=None),
    )
    service.learning = NS(
        advance_analysis=Mock(
            return_value=NS(
                analysis_run_id="analysisrun_" + "6" * 32,
                analysis_state="ACCEPTED",
                graph_snapshot_revision_id="graphrev_" + "7" * 32,
            )
        )
    )
    service.learning.publish_accepted = Mock(
        side_effect=lambda _sources, **_kwargs: (
            NS(
                item_revision_id=registered.item_revision_id,
                analysis_run_id="analysisrun_" + "6" * 32,
                analysis_state="ACCEPTED",
                graph_snapshot_revision_id="graphrev_" + "7" * 32,
            ),
        )
    )
    service._learning_for_registered = Mock(return_value=service.learning)
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
    assert case.service.current is None  # next target is not started in this tick


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


@pytest.mark.parametrize("recovered", [True, False])
def test_cached_failed_analysis_is_resolved_before_classifying_source(monkeypatch, recovered):
    from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord

    case = execution_case(monkeypatch)
    failed = NS(state="FAILED", analysis_run_id="analysisrun_" + "a" * 32)
    case.rows[KnowledgeAnalysisRunRecord] = failed
    case.service.current = execution.CreativeSourceExecution(
        case.cohort.targets[0],
        selection=case.resolved.selection,
        registered=case.registered,
        analysis=NS(analysis_run_id=failed.analysis_run_id),
    )
    if recovered:
        assert case.service.advance_once().state == "VERIFIED"
    else:
        case.service.learning.advance_analysis.return_value.analysis_state = "FAILED"
        with pytest.raises(execution.CreativeSourceTerminalFailure):
            case.service.advance_once()
        case.service.learning.publish_accepted.assert_not_called()
    assert failed.state == "FAILED"
    case.service.learning.advance_analysis.assert_called_once()
    case.start.assert_not_called()


def test_registered_source_is_reauthorized_and_reused_without_new_extraction(monkeypatch):
    case = execution_case(monkeypatch)
    case.service.registration.find_registered_source.return_value = case.registered
    result = case.service.advance_once()
    assert result.state == "VERIFIED" and result.verified_count == 1
    case.service.preparation.prepare.assert_not_called()
    case.service.registration.register_completed.assert_not_called()
    case.start.assert_not_called()
    case.service.read.resolve.assert_called_once()


def test_pending_first_is_a_stable_hint_and_never_omits_targets():
    target = CreativeLearningCohort.model_validate(cohort_value()).targets[0]
    targets = tuple(
        target.model_copy(update={"source_id": "extitem_" + f"{i:032x}"}) for i in range(6)
    )
    published = frozenset(
        execution.creative_registration_key(targets[i].source_id) for i in (0, 2, 4)
    )
    ordered = execution.pending_first_targets(targets, published)
    assert ordered == tuple(targets[i] for i in (1, 3, 5, 0, 2, 4))
    assert len(ordered) == len(targets) and set(t.source_id for t in ordered) == set(
        t.source_id for t in targets
    )
    assert execution.pending_first_targets(targets, frozenset()) == targets
    assert execution.pending_first_targets((), published) == ()


def test_pending_first_does_one_membership_lookup_per_target_at_large_scale():
    target = CreativeLearningCohort.model_validate(cohort_value()).targets[0]
    targets = tuple(
        target.model_copy(update={"source_id": "extitem_" + f"{i:032x}"}) for i in range(20_000)
    )

    class CountingSet(frozenset):
        checks = 0

        def __contains__(self, key):
            self.checks += 1
            return super().__contains__(key)

    published = CountingSet(execution.creative_registration_key(t.source_id) for t in targets[::2])
    assert len(execution.pending_first_targets(targets, published)) == len(targets)
    assert published.checks == len(targets)


def test_pending_hint_reads_one_pinned_graph_and_one_bounded_query(monkeypatch):
    case = execution_case(monkeypatch)
    publication = NS(
        current_structure_context=Mock(
            return_value=NS(graph_snapshot_revision_id="graphrev_" + "7" * 32)
        )
    )
    case.service.learning.publication = publication
    session = NS(
        scalars=Mock(
            return_value=[
                None,
                execution.creative_registration_key(case.service.targets[0].source_id),
            ]
        )
    )
    case.service.sessions = lambda: nullcontext(session)
    result = case.service.pending_first_targets()
    assert len(result) == len(case.service.targets)
    publication.current_structure_context.assert_called_once_with(
        execution.INTEGRATED_SCIENCE_CORPUS_KEY
    )
    session.scalars.assert_called_once()
    statement = session.scalars.call_args.args[0]
    parameters = statement.compile().params
    assert "graphrev_" + "7" * 32 in parameters.values()
    assert "ACCEPTED" in parameters.values() and "APPROVED_ITEM_REVISION" in parameters.values()
    assert ApprovedItemKnowledgeSourceV2.model_fields["source_kind"].default in parameters.values()
    assert tuple(
        execution.creative_registration_key(t.source_id) for t in case.service.targets
    ) in tuple(tuple(v) for v in parameters.values() if isinstance(v, (tuple, list)))
    case.service.read.resolve.assert_not_called()  # a scheduling hint is never completion evidence
