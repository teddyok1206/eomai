"""Bounded driver concurrency is application scheduling, not live worker acceptance."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
)
from eom_catalog_service.creative_cohort_execution import CreativeCohortProgress
from eom_catalog_service.creative_cohort_parallel_execution import (
    CreativeCohortParallelExecutionService,
)

from tests.unit.test_creative_learning_parallel_continuation import parallel_case


class PublicationExecutor:
    def __init__(self):
        self.pending = None
        self.calls = 0
        self.closed = False

    def submit(self, function, sources):
        assert self.pending is None
        future = Future()
        self.pending = (future, function, sources)
        self.calls += 1
        return future

    def complete(self, error=None):
        future, function, sources = self.pending
        self.pending = None
        if error is None:
            function(sources)
            future.set_result(None)
        else:
            future.set_exception(error)

    def shutdown(self, *, wait, cancel_futures):
        assert wait and not cancel_futures
        self.closed = True
        if self.pending:
            self.complete()


def driver_case(monkeypatch, *, count=12, limit=None):
    previous, _, value = parallel_case()
    scope = CreativeLearningExecutionScope(
        previous.cohort, CreativeLearningParallelContinuation.model_validate(value), previous
    )
    target = previous.cohort.targets[0]
    targets = tuple(
        target.model_copy(
            update={
                "source_id": "extitem_" + f"{index:032x}",
                "external_number": str(11000 + index),
            }
        )
        for index in range(count)
    )
    visited = []

    def advance(source):
        visited.append(source.target.source_id)
        source.state = "READY_TO_PUBLISH"

    def publish(sources):
        for source in sources:
            source.state = "VERIFIED"

    def progress(state, current, verified_count, **kwargs):
        return CreativeCohortProgress(
            cohort_id=scope.cohort_id,
            state=state,
            verified_count=verified_count,
            target_count=count,
            external_number=None,
            workflow_id=None,
            item_revision_id=None,
            analysis_run_id=None,
            graph_snapshot_revision_id=None,
            **kwargs,
        )

    owner = NS(
        scope=scope,
        targets=targets,
        advance_report=Mock(side_effect=advance),
        publish_sources=Mock(side_effect=publish),
        progress=progress,
        pending_first_targets=Mock(return_value=targets),
    )
    executor = PublicationExecutor()
    monkeypatch.setattr(
        "eom_catalog_service.creative_cohort_parallel_execution.ThreadPoolExecutor",
        lambda **_kwargs: executor,
    )
    driver = CreativeCohortParallelExecutionService(owner, verified_limit=limit or count)
    return NS(**locals())


def test_readiness_refresh_only_rechecks_original_held_sources(monkeypatch):
    case = driver_case(monkeypatch, count=3)
    driver = case.driver
    retained = driver.targets[2]
    driver.verified_count = 2
    driver.next_target = len(driver.targets)
    driver.blocked[retained.source_id] = (retained.external_number, "SOURCE_NOT_READY")
    driver.refresh_blocked_source_readiness()
    assert driver.targets == (retained,) and driver.verified_count == 2
    assert driver.next_target == 0 and driver.blocked == {}
    driver.advance_once()
    assert case.visited == [retained.source_id]
    with pytest.raises(ValueError, match="NOT_QUIESCENT"):
        driver.refresh_blocked_source_readiness()
    driver.close()


def test_stop_during_report_does_not_submit_the_rest_or_a_new_publication(monkeypatch):
    case = driver_case(monkeypatch)
    stopping = False

    def advance(source):
        nonlocal stopping
        case.visited.append(source.target.source_id)
        source.state = "READY_TO_PUBLISH"
        stopping = True

    case.owner.advance_report.side_effect = advance
    case.driver.stop_requested = lambda: stopping
    case.driver.advance_once()
    assert len(case.visited) == 1
    assert case.executor.calls == 0
    case.driver.close()
    case.owner.publish_sources.assert_not_called()


def test_stop_harvests_existing_publication_without_refill_or_duplicate_work(monkeypatch):
    case = driver_case(monkeypatch)
    case.driver.advance_once()
    original = case.driver.publishing
    case.driver.stop_requested = lambda: True
    case.executor.complete()
    result = case.driver.advance_once()
    assert result.verified_count == len(original)
    assert len(case.visited) == 6 and case.executor.calls == 1
    case.driver.close()
    case.owner.publish_sources.assert_called_once_with(original)


def test_stop_before_admission_has_no_work_or_empty_publication(monkeypatch):
    case = driver_case(monkeypatch)
    case.driver.stop_requested = lambda: True
    case.driver.advance_once()
    assert case.driver.next_target == 0 and not case.driver.window
    case.driver.close()
    case.owner.advance_report.assert_not_called()
    case.owner.publish_sources.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_close_drains_inflight_publication_and_preserves_its_outcome(monkeypatch, failure):
    case = driver_case(monkeypatch)
    started, release, closing, closed = Event(), Event(), Event(), Event()
    case.driver.executor = ThreadPoolExecutor(max_workers=1)

    def publish(sources):
        started.set()
        assert release.wait(5)
        if failure:
            raise ValueError("KNOWLEDGE_GRAPH_STALE_CURRENT")
        for source in sources:
            source.state = "VERIFIED"

    def close():
        closing.set()
        try:
            case.driver.close()
        finally:
            closed.set()

    case.owner.publish_sources.side_effect = publish
    case.driver.advance_once()
    try:
        assert started.wait(5)
        case.driver.stop_requested = lambda: True
        with ThreadPoolExecutor(max_workers=1) as closer:
            future = closer.submit(close)
            try:
                assert closing.wait(5)
                assert not closed.wait(0.05)
            finally:
                release.set()
            if failure:
                with pytest.raises(ValueError, match="STALE_CURRENT"):
                    future.result(timeout=5)
            else:
                future.result(timeout=5)
    finally:
        release.set()
        case.driver.executor.shutdown(wait=True)
    assert closed.is_set()
    assert len(case.visited) == 6
    case.owner.publish_sources.assert_called_once()
    assert all(
        source.state == ("READY_TO_PUBLISH" if failure else "VERIFIED")
        for source in case.driver.publishing
    )


def test_graph_publication_does_not_block_other_reports_or_expand_the_six_source_window(
    monkeypatch,
):
    case = driver_case(monkeypatch)
    first = case.driver.advance_once()
    assert first.verified_count == 0 and len(case.driver.window) == 6
    assert case.executor.calls == 1
    assert sum(state == "PUBLISHING" for _, state in first.active_sources) == 3
    assert len(case.driver.publishing) == 3
    # Graph I/O remains incomplete. Observation neither launches another publisher
    # nor repeats completed report submissions.
    for _ in range(10):
        case.driver.advance_once()
    assert len(case.visited) == 6 and case.executor.calls == 1
    case.executor.complete()
    after = case.driver.advance_once()
    assert after.verified_count == 3 and len(case.driver.window) == 6
    assert len(case.visited) == 9
    assert len(set(case.visited)) == 9
    assert case.executor.calls == 2  # refill and next serial Graph batch
    case.driver.close()


def test_canary_limit_does_not_submit_sources_beyond_the_approved_limit(monkeypatch):
    case = driver_case(monkeypatch, limit=2)
    case.owner.pending_first_targets.assert_not_called()
    case.driver.advance_once()
    assert len(case.visited) == len(case.driver.publishing) == 2
    case.executor.complete()
    result = case.driver.advance_once()
    assert result.verified_count == 2 and result.state == "VERIFIED"
    assert not case.driver.window and len(case.visited) == 2
    case.driver.close()


def test_full_run_uses_priority_hint_without_mutating_admitted_targets(monkeypatch):
    case = driver_case(monkeypatch)
    case.owner.pending_first_targets.assert_called_once_with()
    assert case.owner.targets == case.targets
    assert case.driver.verified_count == 0
    case.driver.close()


def test_out_of_order_report_readiness_and_final_batch_keep_all_targets_once(monkeypatch):
    case = driver_case(monkeypatch, count=11)
    for _ in range(4):
        case.driver.advance_once()
        case.executor.complete()
    result = case.driver.advance_once()
    assert result.state == "COMPLETED" and result.verified_count == 11
    assert len(case.visited) == len(set(case.visited)) == 11
    assert [len(call.args[0]) for call in case.owner.publish_sources.call_args_list] == [3, 3, 3, 2]
    case.driver.close()


def test_graph_failure_never_becomes_verified_or_refills_the_window(monkeypatch):
    case = driver_case(monkeypatch)
    case.driver.advance_once()
    case.executor.complete(ValueError("KNOWLEDGE_GRAPH_STALE_CURRENT"))
    with pytest.raises(ValueError, match="STALE_CURRENT"):
        case.driver.advance_once()
    assert case.driver.verified_count == 0 and len(case.visited) == 6
    with pytest.raises(ValueError, match="STALE_CURRENT"):
        case.driver.close()
    assert case.executor.closed


def test_parallel_driver_rejects_unadmitted_serial_scope(monkeypatch):
    case = driver_case(monkeypatch)
    case.owner.scope = replace(case.scope, continuation=None, predecessor_scope=None)
    with pytest.raises(ValueError, match="PARALLEL_CONTINUATION_REQUIRED"):
        CreativeCohortParallelExecutionService(case.owner, verified_limit=12)
    case.driver.close()


@pytest.mark.parametrize("native", [False, True])
def test_only_native_successor_continues_past_a_proven_terminal_source(monkeypatch, native):
    from eom_catalog_service.creative_cohort_execution import CreativeSourceTerminalFailure

    from tests.unit.test_office_creative_continuation import office_continuation_case

    case = driver_case(monkeypatch, count=12)
    if native:
        previous, _, continuation = office_continuation_case()
        case.owner.scope = CreativeLearningExecutionScope(previous.cohort, continuation, previous)
    original = case.owner.advance_report.side_effect

    def advance(source):
        if source.target == case.targets[0]:
            raise CreativeSourceTerminalFailure(
                source.target, source.selection, "CREATIVE_COHORT_EXTRACTION_TERMINAL_FAILURE"
            )
        original(source)

    case.owner.advance_report.side_effect = advance
    if native:
        progress = case.driver.advance_once()
        assert progress.blocked_sources == (
            (case.targets[0].external_number, "CREATIVE_COHORT_EXTRACTION_TERMINAL_FAILURE"),
        )
        assert len(case.visited) == 5 and case.driver.verified_count == 0
        assert case.targets[0].source_id not in case.driver.window
    else:
        with pytest.raises(CreativeSourceTerminalFailure):
            case.driver.advance_once()
        assert not case.driver.blocked
    case.driver.close()


def test_unclassified_source_error_still_stops_instead_of_being_hidden(monkeypatch):
    case = driver_case(monkeypatch)
    case.owner.advance_report.side_effect = ValueError("CREATIVE_COHORT_WORKFLOW_POLICY_MISMATCH")
    with pytest.raises(ValueError, match="POLICY_MISMATCH"):
        case.driver.advance_once()
    assert not case.driver.blocked and case.driver.verified_count == 0
    case.driver.close()
