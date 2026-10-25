"""Marker-guarded PostgreSQL planning concurrency; no source grant, root unit or model."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
)
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    parse_embedding_batch_plan_request,
)
from eom_workflow.embedding_batch_plan_v11 import EmbeddingBatchPlanRequestV11
from eom_workflow.embedding_batch_plan_v12 import EmbeddingBatchPlanRequestV12
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_bulk_plan_fixtures import bulk_planning_case
from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case

pytestmark = pytest.mark.integration


@pytest.fixture(params=("legacy", "bulk", "paired_query"))
def planned(guarded_engine, request):
    builder = {
        "legacy": planning_case,
        "bulk": bulk_planning_case,
        "paired_query": paired_query_case,
    }[request.param]
    value = builder(batch_id="embeddingbatch_" + uuid4().hex)
    value.engine = guarded_engine
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, value.policy)
    # Explicit synthetic child-admission seam, not proof these fixture child Jobs exist.
    # The real source adapter/command/Job integration is a separate guarded suite.
    expected = {child.native_input_sha256: child for child in value.bound.children}
    value.authorize = lambda child: (
        None
        if expected.get(child.native_input_sha256) == child
        else (_ for _ in ()).throw(PermissionError("foreign child"))
    )
    return value


@pytest.mark.parametrize("autoflush", [False, True])
def test_atomic_plan_binding_and_exact_replay_are_not_numerical_success(planned, autoflush):
    with Session(planned.engine, autoflush=autoflush) as session, session.begin():
        assert planned.store.read(session) is None
        allocated, created = planned.store.allocate(session, planned.allocation)
        assert created and allocated.state == "CLAIMED"
        planned.store.route(session, planned.route)
        completed = planned.store.bind(
            session, planned.bound, planned.batch, authorize_child=planned.authorize
        )
    assert completed.state == "SUCCEEDED" and completed.bound == planned.bound
    # SUCCEEDED refers only to the planning Job. No numerical/child Job or Artifact is created.
    with Session(planned.engine) as session, session.begin():
        repeated, created = planned.store.allocate(session, planned.allocation)
        assert repeated == completed and not created
        assert planned.store.route(session, planned.route) == completed
        assert (
            planned.store.bind(
                session, planned.bound, planned.batch, authorize_child=planned.authorize
            )
            == completed
        )
        job = session.get(JobRecord, completed.job_id)
        protocol, _schema_sha = embedding_batch_plan_schema_identity(planned.request)
        assert job.protocol_version == protocol
        events = tuple(
            session.scalars(select(JobEventRecord).where(JobEventRecord.job_id == job.job_id))
        )
        assert len(events) == 8 and job.worker_slot_id is None
        assert "anchors" not in job.request and "vectors" not in job.request
        assert len(json.dumps(job.request)) < 16384
        assert all("text" not in event.data and "vectors" not in event.data for event in events)


def test_new_bulk_version_cannot_fork_or_replace_an_existing_logical_batch(guarded_engine):
    batch_id = "embeddingbatch_" + uuid4().hex
    old = planning_case(purpose="INDEX", batch_id=batch_id)
    new = bulk_planning_case(batch_id=batch_id)
    old_store = EmbeddingBatchPlanStore(old.request, old.selection, old.policy)
    new_store = EmbeddingBatchPlanStore(new.request, new.selection, new.policy)
    assert old_store.key == new_store.key
    with Session(guarded_engine) as session, session.begin():
        original, created = old_store.allocate(session, old.allocation)
        assert created
    with pytest.raises(ValueError), Session(guarded_engine) as session, session.begin():
        new_store.allocate(session, new.allocation)
    with Session(guarded_engine) as session, session.begin():
        assert old_store.read(session) == original
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == old_store.key)
            )
            == 1
        )


def test_query_index_successor_cannot_replace_existing_logical_query_history(guarded_engine):
    batch_id = "embeddingbatch_" + uuid4().hex
    old = planning_case(batch_id=batch_id)
    new = paired_query_case(batch_id=batch_id, actor_id=old.request.scope.actor_id)
    old_store = EmbeddingBatchPlanStore(old.request, old.selection, old.policy)
    new_store = EmbeddingBatchPlanStore(new.request, new.selection, new.policy)
    assert old_store.key == new_store.key
    with Session(guarded_engine) as session, session.begin():
        original, created = old_store.allocate(session, old.allocation)
        assert created
    with pytest.raises(ValueError), Session(guarded_engine) as session, session.begin():
        new_store.allocate(session, new.allocation)
    with Session(guarded_engine) as session, session.begin():
        assert old_store.read(session) == original


def test_concurrent_larger_window_candidates_keep_original_allocation_and_expiry(planned):
    with Session(planned.engine) as session, session.begin():
        original, created = planned.store.allocate(session, planned.allocation)
        assert created
    candidates = []
    for _ in range(2):
        control = seal(
            planned.allocation.control_request.model_dump(mode="json")
            | {
                "allocation_attempt_id": "embeddingallocation_" + uuid4().hex,
                "expires_monotonic_ns": planned.allocation.control_request.expires_monotonic_ns
                + 240 * 10**9,
            },
            "message_sha256",
        )
        candidates.append(
            EmbeddingBatchAllocation.model_validate(
                seal(
                    planned.allocation.model_dump(mode="json") | {"control_request": control},
                    "record_sha256",
                )
            )
        )
    barrier = Barrier(2)

    def replay(candidate):
        with Session(planned.engine) as session, session.begin():
            barrier.wait(timeout=10)
            return planned.store.allocate(session, candidate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(replay, candidate) for candidate in candidates]
        for future in futures:
            observed, created = future.result(timeout=30)
            assert not created and observed == original
            assert (
                observed.allocation.control_request.expires_monotonic_ns
                == planned.allocation.control_request.expires_monotonic_ns
            )
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original


def test_two_controllers_reserve_one_original_allocation_and_only_one_dispatch_owner(planned):
    body = planned.allocation.model_dump(mode="json")
    body["control_request"] = seal(
        body["control_request"] | {"allocation_attempt_id": "embeddingallocation_" + "b" * 32},
        "message_sha256",
    )
    other = EmbeddingBatchAllocation.model_validate(seal(body, "record_sha256"))
    barrier = Barrier(2)

    def allocate(record):
        with Session(planned.engine) as session, session.begin():
            barrier.wait(timeout=10)
            return planned.store.allocate(session, record)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(allocate, row) for row in (planned.allocation, other)]
        result = [future.result(timeout=30) for future in futures]
    assert sorted(created for _, created in result) == [False, True]
    assert result[0][0] == result[1][0]
    with Session(planned.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == planned.store.key)
            )
            == 1
        )


def test_route_and_binding_roll_back_with_the_caller_root(planned):
    with pytest.raises(KeyboardInterrupt), Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        raise KeyboardInterrupt("synthetic original owner death")
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) is None
        allocated, _ = planned.store.allocate(session, planned.allocation)
    with pytest.raises(KeyboardInterrupt), Session(planned.engine) as session, session.begin():
        planned.store.route(session, planned.route)
        planned.store.bind(session, planned.bound, planned.batch, authorize_child=planned.authorize)
        raise KeyboardInterrupt("synthetic crash before plan commit")
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == allocated


def test_gpu_availability_change_does_not_replace_original_route_or_child_identity(planned):
    with Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        original = planned.store.route(session, planned.route)
    builder = {
        EmbeddingBatchPlanRequestV11: bulk_planning_case,
        EmbeddingBatchPlanRequestV12: paired_query_case,
    }.get(type(planned.request), planning_case)
    other = builder(status="BUSY", batch_id=planned.request.batch_id)
    assert other.request == planned.request and other.allocation == planned.allocation
    with pytest.raises(ValueError), Session(planned.engine) as session, session.begin():
        planned.store.route(session, other.route)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original


def test_original_batch_key_cannot_be_widened_by_a_changed_request(planned):
    with Session(planned.engine) as session, session.begin():
        original, _ = planned.store.allocate(session, planned.allocation)
    changed = parse_embedding_batch_plan_request(
        seal(
            planned.request.model_dump(mode="json")
            | {"parent_request_sha256": "sha256:" + "f" * 64},
            "request_sha256",
        )
    )
    conflict = EmbeddingBatchPlanStore(changed, planned.selection, planned.policy)
    assert conflict.key == planned.store.key
    with pytest.raises(ValueError), Session(planned.engine) as session, session.begin():
        conflict.read(session)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original


@pytest.mark.parametrize("after_route", [False, True])
def test_failed_planning_history_is_preserved_and_cannot_bind_or_become_success(
    planned, after_route
):
    with Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        if after_route:
            planned.store.route(session, planned.route)
        failed = planned.store.record_failure(session, planned.failure)
        assert failed.state == "FAILED"
    with Session(planned.engine) as session, session.begin():
        assert planned.store.record_failure(session, planned.failure) == failed
        assert planned.store.allocate(session, planned.allocation) == (failed, False)
    with pytest.raises(ValueError), Session(planned.engine) as session, session.begin():
        planned.store.bind(session, planned.bound, planned.batch, authorize_child=planned.authorize)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == failed


def test_concurrent_unbound_failure_has_one_terminal_event_and_exact_replay(planned):
    with Session(planned.engine) as session, session.begin():
        original, _ = planned.store.allocate(session, planned.allocation)
    barrier = Barrier(2)

    def fail_once(_):
        barrier.wait(timeout=10)
        with Session(planned.engine) as session, session.begin():
            return planned.store.record_failure(session, planned.failure)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(fail_once, range(2)))
    assert first == second and first.state == "FAILED"
    assert first.allocation == original.allocation and first.bound is first.route is None
    with Session(planned.engine) as session, session.begin():
        assert planned.store.record_failure(session, planned.failure) == first
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == original.job_id,
                    JobEventRecord.event == "EMBEDDING_PLAN_FAILED",
                )
            )
            == 1
        )


def test_late_unbound_failure_evidence_change_rolls_back_terminal_history(planned):
    with Session(planned.engine) as session, session.begin():
        original, _ = planned.store.allocate(session, planned.allocation)
    with (
        pytest.raises(ValueError, match="synthetic late physical evidence change"),
        Session(planned.engine) as session,
        session.begin(),
    ):
        planned.store.record_failure(session, planned.failure)
        raise ValueError("synthetic late physical evidence change")
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original


def test_missing_allocation_and_savepoint_are_not_dispatch_authority(planned):
    with Session(planned.engine) as session, session.begin():
        with pytest.raises(ValueError):
            planned.store.route(session, planned.route)
        with session.begin_nested(), pytest.raises(ValueError):
            planned.store.allocate(session, planned.allocation)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) is None


def test_plan_key_lookup_uses_existing_unique_btree_capability(planned):
    with Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        # Small fixtures may legitimately choose a sequential scan. Verify index
        # capability, not a claim of production latency or production query plans.
        session.execute(text("SET LOCAL enable_seqscan=off"))
        rows = session.execute(
            text("EXPLAIN SELECT job_id FROM app.jobs WHERE idempotency_key=:key"),
            {"key": planned.store.key},
        )
        assert "Index" in "\n".join(str(row[0]) for row in rows)


@pytest.mark.parametrize("failure", ["denied", "false_return", "denied_late", "false_return_late"])
def test_child_authorization_denial_rolls_back_binding_without_changing_route(planned, failure):
    with Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        routed = planned.store.route(session, planned.route)

    checks = []

    def deny(child):
        checks.append(child)
        if failure.endswith("_late") and len(checks) <= len(planned.bound.children):
            return None
        if failure.startswith("denied"):
            raise PermissionError("source revoked")
        return False

    with (
        pytest.raises((ValueError, PermissionError)),
        Session(planned.engine) as session,
        session.begin(),
    ):
        planned.store.bind(session, planned.bound, planned.batch, authorize_child=deny)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == routed
