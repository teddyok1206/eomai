"""Finite gathering/thread/source-identity tests; root/GPU/current IAM remain synthetic."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    PublishedEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_source_authorization import ReferenceQueryBatchSource
from eom_workflow_runner.reference_query_batch_group import (
    CatalogReferenceQueryBatchGroup,
    PreparedReferenceQueryBatchChild,
)
from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_source_read import ReferenceQueryOwnerConfiguration
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.reference_query_batch_execution_fixtures import two_query_plan_case
from tests.unit.test_embedding_batch_plan_admission import source_case


@pytest.fixture
def grouped(tmp_path, monkeypatch):
    queries, plan = two_query_plan_case()
    value = source_case(tmp_path, monkeypatch, planned=plan)
    registry = replace(
        value.catalog.configuration,
        namespace=type(value.catalog.configuration.namespace).model_validate(
            value.catalog.configuration.namespace.model_dump(mode="json")
            | {"space_sha256": plan.policy.cuda.profile.space.space_sha256}
        ),
        space=plan.policy.cuda.profile.space,
    )
    owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
    owner.configuration = ReferenceQueryOwnerConfiguration(
        registry,
        queries[0].request.native_execution_policy,
        queries[0].request.native_execution_policy_sha256,
        queries[0].request.runtime_bundle,
    )
    owner.settings = value.catalog.settings
    owner.catalog = CatalogEmbeddingRegistryVerifier(
        value.engine, registry, identity_fence=Mock(), settings=owner.settings
    )
    channel = SimpleNamespace(
        request=SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 30 * 10**9),
        require_direct_peer=Mock(),
    )
    operation = SimpleNamespace(
        publisher=value.publisher, admission=value.owner, source_commit="a" * 40
    )
    active = ActiveEmbeddingBatchExecution(
        operation, value.request, SimpleNamespace(route=plan.route), channel, object()
    )
    group = CatalogReferenceQueryBatchGroup(active, owner)
    value.group, value.channel, value.run_calls, value.source_calls = group, channel, [], []
    saved = PublishedEmbeddingBatchExecution(SimpleNamespace(), SimpleNamespace())

    def source(self, batch, child):
        with self.transaction() as session:
            assert session.info["source_workflow"] == self.launch.workflow_id
            value.source_calls.append(self.launch.workflow_id)

    def run(self, binding, batch, *, authorization):
        value.run_calls.append((binding, batch))
        authorization.authorize_batch()
        return saved

    monkeypatch.setattr(ReferenceQueryBatchSource, "authorize", source)
    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", run)
    children = []
    for ordinal, query in enumerate(queries):

        @contextmanager
        def transaction(workflow_id=query.launch.workflow_id):
            with value.publisher.sessions.begin() as session:
                session.info["source_workflow"] = workflow_id
                yield session

        material = PreparedBatchReferenceQuery(
            query.request, query.policy, query.bundle, query.launch, query.native_input
        )
        source = ReferenceQueryBatchSource(
            owner,
            query.request,
            query.launch,
            CommandLeaseIdentity("wfcmd_" + str(ordinal + 1) * 32, "test", "test", 1),
            transaction,
        )
        children.append(PreparedReferenceQueryBatchChild(ordinal, material, source))
    value.children, value.saved = tuple(children), saved
    yield value
    value.group.abort()
    value.engine.dispose()


def test_out_of_order_gathering_keeps_original_child_order_and_one_shared_result(grouped):
    value = grouped
    with ThreadPoolExecutor(max_workers=2) as pool:
        second = pool.submit(value.group.join, value.children[1])
        first = pool.submit(value.group.join, value.children[0])
        assert first.result(timeout=10) is value.saved
        assert second.result(timeout=10) is value.saved
    assert len(value.run_calls) == 1
    binding, batch = value.run_calls[0]
    assert tuple(row.native_job_id for row in binding.children) == tuple(
        child.material.request.job_id for child in value.children
    )
    assert tuple(row.request for row in batch.children) == tuple(
        child.material.request for child in value.children
    )
    assert value.source_calls == [
        child.material.association.workflow_id for child in value.children
    ]
    value.channel.require_direct_peer.side_effect = AssertionError("completed read revived a root")
    value.group.assert_available()
    value.group.assert_original_material(value.children[0].material)
    replay = replace(
        value.children[0],
        source=replace(
            value.children[0].source,
            command_lease=CommandLeaseIdentity("wfcmd_" + "f" * 32, "next", "next", 2),
        ),
    )
    assert value.group.join(replay) is value.saved and len(value.run_calls) == 1


def test_duplicate_child_is_not_a_second_source_or_numerical_dispatch(grouped):
    value = grouped
    started = Event()

    def wait_first():
        started.set()
        return value.group.join(value.children[0])

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(wait_first)
        assert started.wait(1)
        # Wait for the actual entry rather than racing a second duplicate caller.
        with value.group._condition:
            assert value.group._condition.wait_for(lambda: bool(value.group._children), timeout=1)
        with pytest.raises(ValueError):
            value.group.join(value.children[0])
        value.group.abort()
        with pytest.raises(ValueError):
            first.result(timeout=2)
    assert value.run_calls == []


def test_original_gather_deadline_or_abort_never_runs_a_partial_batch(grouped):
    value = grouped
    value.channel.request.expires_monotonic_ns = time.monotonic_ns() + 20_000_000
    with pytest.raises(TimeoutError):
        value.group.join(value.children[0])
    with pytest.raises(ValueError):
        value.group.join(value.children[1])
    assert value.run_calls == []


def test_post_compute_metadata_wait_does_not_extend_gpu_grant_or_lose_completed_result(
    grouped, monkeypatch
):
    value = grouped
    running, finish = Event(), Event()
    original = ActiveEmbeddingBatchExecution.run

    def run(self, *args, **kwargs):
        running.set()
        assert finish.wait(2)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(value.group.join, child) for child in value.children]
        assert running.wait(2)
        # Synthetic clock/window only; no real compute deadline is changed.
        with value.group._condition:
            value.channel.request.expires_monotonic_ns = time.monotonic_ns() - 1
            value.group._condition.notify_all()
        finish.set()
        assert all(future.result(timeout=3) is value.saved for future in futures)
    assert len(value.run_calls) == 1


def test_failed_root_wakes_every_original_child_without_cpu_fallback(grouped, monkeypatch):
    value = grouped

    def fail(*_args, **_kwargs):
        raise ValueError("synthetic original root failure")

    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", fail)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(value.group.join, child) for child in value.children]
        for future in futures:
            with pytest.raises(ValueError):
                future.result(timeout=3)
    assert value.run_calls == []
