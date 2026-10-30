"""Bounded driver concurrency is application scheduling, not live worker acceptance."""

from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
)
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
        return NS(state=state, verified_count=verified_count, **kwargs)

    owner = NS(
        scope=scope,
        targets=targets,
        advance_report=Mock(side_effect=advance),
        publish_sources=Mock(side_effect=publish),
        progress=progress,
    )
    executor = PublicationExecutor()
    monkeypatch.setattr(
        "eom_catalog_service.creative_cohort_parallel_execution.ThreadPoolExecutor",
        lambda **_kwargs: executor,
    )
    driver = CreativeCohortParallelExecutionService(owner, verified_limit=limit or count)
    return NS(**locals())


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
    case.driver.advance_once()
    assert len(case.visited) == len(case.driver.publishing) == 2
    case.executor.complete()
    result = case.driver.advance_once()
    assert result.verified_count == 2 and result.state == "VERIFIED"
    assert not case.driver.window and len(case.visited) == 2
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
