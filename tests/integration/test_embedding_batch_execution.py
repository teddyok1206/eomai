"""Real guarded PG parent/Artifact flow; explicit synthetic root/numerical/current IAM leaves."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_allocation_window_seconds
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    EmbeddingWorkBatchInput,
)
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_workspace import StagedOwnerEmbeddingBatch
from eom_orchestrator.local_embedding_control_artifacts import BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE
from eom_orchestrator.models import ArtifactRecord, JobRecord
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation, EmbeddingBatchBound
from eom_workflow_runner import embedding_batch_execution as execution
from eom_workflow_runner.embedding_batch_result_read import VerifiedLocalEmbeddingBatchResult
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)
from sqlalchemy import func, select

from tests.integration.test_embedding_batch_plan_admission import admitted as admitted
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import RELEASE, control_frames

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_case(admitted, monkeypatch):
    value = admitted
    control = seal(
        value.allocation.control_request.model_dump(mode="json")
        | {"expires_monotonic_ns": time.monotonic_ns() + 180 * 10**9},
        "message_sha256",
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            value.allocation.model_dump(mode="json") | {"control_request": control}, "record_sha256"
        )
    )
    value.frames = control_frames(request=value.allocation.control_request)
    value.observation = value.frames.ready
    value.channel = object.__new__(EmbeddingBatchOwnerChannel)
    channel = value.channel
    channel.request = value.allocation.control_request
    channel.side, channel.controller_release = "OWNER", RELEASE
    channel.require_direct_peer = Mock()
    channel.receive_allocation = Mock(side_effect=lambda: value.observation)
    channel.send_binding = Mock()
    channel.close = Mock()
    value.dispatched, value.acked, value.source_denied = [], False, False
    value.checks = []
    listener = SimpleNamespace(accept_root=Mock(return_value=channel))

    @contextmanager
    def listen(staged):
        assert staged == value.allocation.control_request
        yield listener

    def stage_control(request):
        if request != value.allocation.control_request:
            value.allocation = EmbeddingBatchAllocation.model_validate(
                seal(
                    value.allocation.model_dump(mode="json")
                    | {"control_request": request.model_dump(mode="json")},
                    "record_sha256",
                )
            )
            value.frames = control_frames(request=request)
            value.observation = value.frames.ready
            channel.request = request
        return request

    monkeypatch.setattr(execution, "stage_embedding_batch_control", stage_control)
    monkeypatch.setattr(execution, "owner_embedding_batch_listener", listen)
    monkeypatch.setattr(
        execution,
        "dispatch_embedding_batch_control",
        lambda original: value.dispatched.append(original),
    )

    def source(self):
        assert self is value.authorization
        if value.source_denied:
            raise PermissionError("synthetic current child authority denied")

    def child(self, batch_hash, child_hash):
        source(self)
        assert batch_hash == value.batch.request_sha256
        assert child_hash in {row.request.request_sha256 for row in value.batch.children}
        value.checks.append(child_hash)

    def binding(self, row):
        source(self)
        assert row in value.bound.children

    def terminal(self):
        assert self is channel and value.acked and channel.close.called
        return value.numeric.completed

    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_batch", source)
    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_child", child)
    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_binding", binding)
    monkeypatch.setattr(EmbeddingBatchOwnerChannel, "acknowledged_completion", property(terminal))
    monkeypatch.setattr(VerifiedLocalEmbeddingBatchResult, "assert_current", lambda _: None)
    value.operation = execution.CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release=RELEASE
    )
    return value


def prepare_synthetic_children(value, active, monkeypatch):
    """Numerical/source fixtures, not a real GPU execution or source permission claim."""
    route = active.history.route
    assert route is not None
    value.batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            value.case.batch.model_dump(mode="json")
            | {
                "scope": value.request.scope.model_dump(mode="json"),
                "routing_decision_sha256": route.decision.decision_sha256,
                "children": [
                    row.model_dump(mode="json") | {"scope_sha256": value.request.scope.scope_sha256}
                    for row in value.case.batch.children
                ],
            },
            "request_sha256",
        )
    )
    value.bound = EmbeddingBatchBound.model_validate(
        seal(
            value.case.bound.model_dump(mode="json")
            | {
                "request_sha256": value.request.request_sha256,
                "route_record_sha256": route.record_sha256,
                "batch_request_sha256": value.batch.request_sha256,
                "children": [
                    row.model_dump(mode="json") | {"selection_sha256": selected}
                    for row, selected in zip(
                        value.case.bound.children,
                        value.request.child_selection_sha256s,
                        strict=True,
                    )
                ],
            },
            "record_sha256",
        )
    )
    value.numeric = execution_case(
        planned=SimpleNamespace(allocation=value.allocation, batch=value.batch, bound=value.bound)
    )
    value.authorization = object.__new__(CatalogEmbeddingBatchSourceAuthorization)
    value.authorization._batch = value.batch
    staged = StagedOwnerEmbeddingBatch(value.numeric.frames.bound, value.batch, (), ())
    value.verified = VerifiedLocalEmbeddingBatchResult(
        staged,
        value.frames.ready,
        value.numeric.completed,
        value.numeric.result,
        validate_embedding_work_batch_binary(
            value.batch, value.numeric.result, value.numeric.vectors
        ),
        (),
        (),
    )

    def stage(request, ready, bound, batch):
        assert (request, ready, bound, batch) == (
            value.channel.request,
            value.frames.ready,
            value.bound,
            value.batch,
        )
        return staged

    requests = iter(value.batch.children)

    def next_check(authorize):
        row = next(requests, None)
        if row is None:
            return value.numeric.completed
        authorize(value.batch.request_sha256, row.request.request_sha256)
        return None

    def ack(verify):
        verify(value.numeric.completed)
        value.acked = True

    value.channel.authorize_next = Mock(side_effect=next_check)
    value.channel.acknowledge_completion = Mock(side_effect=ack)
    monkeypatch.setattr(execution, "stage_owner_embedding_batch", stage)
    monkeypatch.setattr(
        execution, "read_verified_embedding_batch_result", Mock(return_value=value.verified)
    )


def history(value):
    with value.publisher.sessions.begin() as session:
        return value.store.read(session)


def receipt_count(value):
    with value.publisher.sessions() as session:
        return session.scalar(
            select(func.count())
            .select_from(ArtifactRecord)
            .where(ArtifactRecord.artifact_type == BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE)
        )


@pytest.mark.parametrize("admitted", ["bulk"], indirect=True)
@pytest.mark.parametrize("interrupted", [False, True])
def test_index_clock_begins_after_late_source_admission_and_replay_never_renews_it(
    owner_case, monkeypatch, interrupted
):
    value = owner_case
    original_request = value.request.model_dump(mode="json")
    original_admit = value.owner.admit
    original_candidate = execution.new_embedding_batch_allocation_candidate
    clock = [time.monotonic_ns()]
    prepared = SimpleNamespace(first=True, finished=False, session=None)
    starts = []

    @contextmanager
    def delayed_admit(session, request):
        first = prepared.first
        prepared.first = False
        with original_admit(session, request) as sources:
            if first:
                prepared.session = session
                clock[0] += 600 * 10**9
            yield sources
            if first:
                clock[0] += 600 * 10**9
        if first:
            prepared.finished = True

    def candidate(request, policy):
        assert prepared.finished and prepared.session.in_transaction()
        starts.append(clock[0])
        return original_candidate(request, policy, now_monotonic_ns=clock[0])

    monkeypatch.setattr(value.owner, "admit", delayed_admit)
    monkeypatch.setattr(execution, "new_embedding_batch_allocation_candidate", candidate)
    if interrupted:

        def dispatch(listener):
            value.dispatched.append(listener)
            raise TimeoutError("synthetic original dispatch interrupted")

        monkeypatch.setattr(execution, "dispatch_embedding_batch_control", dispatch)
        with pytest.raises(TimeoutError), value.operation.open_index(value.request):
            pytest.fail("interrupted root offered execution")
    else:
        with value.operation.open_index(value.request) as active:
            assert type(active) is execution.ActiveEmbeddingBatchExecution
    original = history(value)
    numerical = min(
        value.case.policy.cuda.profile.resource_profile.timeout_seconds,
        MAX_EMBEDDING_WORK_BATCH_SECONDS,
    )
    assert original.allocation.control_request.expires_monotonic_ns == (
        starts[0] + embedding_gpu_allocation_window_seconds(numerical) * 10**9
    )
    assert value.request.model_dump(mode="json") == original_request
    clock[0] += 3600 * 10**9
    with value.operation.open_index(value.request) as replay:
        assert type(replay) is execution.ExistingEmbeddingBatchExecution
        assert replay.history == original
    assert len(starts) == len(value.dispatched) == 1


@pytest.mark.parametrize("admitted", ["bulk"], indirect=True)
def test_concurrent_index_open_keeps_one_original_allocation_and_dispatch(owner_case):
    value, barrier = owner_case, Barrier(2)

    def open_once():
        barrier.wait(timeout=10)
        with value.operation.open_index(value.request) as result:
            return type(result), result.history.job_id, result.history.allocation

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_once) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert {kind for kind, _job, _allocation in results} == {
        execution.ActiveEmbeddingBatchExecution,
        execution.ExistingEmbeddingBatchExecution,
    }
    assert results[0][1:] == results[1][1:] and len(value.dispatched) == 1


@pytest.mark.parametrize("admitted", ["bulk"], indirect=True)
@pytest.mark.parametrize("phase", ["entry", "exit"])
def test_index_preparation_denial_creates_no_allocation_or_dispatch(owner_case, monkeypatch, phase):
    value = owner_case
    original_admit = value.owner.admit

    @contextmanager
    def denied(session, request):
        with original_admit(session, request) as sources:
            if phase == "entry":
                raise PermissionError("synthetic entry denial")
            yield sources
            raise PermissionError("synthetic late denial")

    candidate = Mock(side_effect=AssertionError("denied source created an allocation"))
    monkeypatch.setattr(value.owner, "admit", denied)
    monkeypatch.setattr(execution, "new_embedding_batch_allocation_candidate", candidate)
    with pytest.raises(PermissionError), value.operation.open_index(value.request):
        pytest.fail("denied source offered execution")
    assert history(value) is None and value.dispatched == []
    candidate.assert_not_called()


def test_actual_application_orders_parent_route_binding_checks_ack_and_publication(
    owner_case, monkeypatch
):
    value = owner_case
    before = receipt_count(value)
    with value.operation.open(value.request, value.allocation) as active:
        assert isinstance(active, execution.ActiveEmbeddingBatchExecution)
        assert history(value).route == active.history.route
        assert (
            active.history.route.observation.allocation_reference_sha256
            == value.frames.ready.message_sha256
        )
        prepare_synthetic_children(value, active, monkeypatch)
        saved = active.run(value.bound, value.batch, authorization=value.authorization)
        assert saved.verified is value.verified and value.acked
        assert value.checks == [row.request.request_sha256 for row in value.batch.children]
        assert receipt_count(value) == before + 1
        with value.publisher.sessions() as session:
            assert session.get(JobRecord, saved.publication.owner_job_id).status == "SUCCEEDED"
        with pytest.raises(ValueError):
            active.run(value.bound, value.batch, authorization=value.authorization)
    original = history(value)
    assert original.state == "SUCCEEDED" and original.bound == value.bound
    with value.operation.open(value.request, value.allocation) as replay:
        assert isinstance(replay, execution.ExistingEmbeddingBatchExecution)
        assert replay.history == original
    assert len(value.dispatched) == 1 and receipt_count(value) == before + 1


def test_busy_pins_cpu_only_after_original_root_unavailable_and_never_reselects(owner_case):
    value = owner_case
    value.observation = value.frames.busy
    before = receipt_count(value)
    with value.operation.open(value.request, value.allocation) as busy:
        assert isinstance(busy, execution.UnavailableEmbeddingBatchExecution)
        assert busy.root_observation == value.frames.busy
        assert busy.history.route.decision.selected.backend.device == "CPU"
        assert (
            busy.history.route.observation.allocation_reference_sha256
            == value.frames.busy.message_sha256
        )
    value.observation = value.frames.ready
    with value.operation.open(value.request, value.allocation) as replay:
        assert isinstance(replay, execution.ExistingEmbeddingBatchExecution)
        assert replay.history.route.decision.selected.backend.device == "CPU"
    assert len(value.dispatched) == 1 and receipt_count(value) == before
    value.channel.send_binding.assert_not_called()


@pytest.mark.parametrize("failure", ("dispatch", "receive", "late_parent"))
def test_unknown_or_late_denial_preserves_original_allocation_without_fallback_or_redispatch(
    owner_case, monkeypatch, failure
):
    value = owner_case
    if failure == "dispatch":

        def dispatch(listener):
            value.dispatched.append(listener)
            raise TimeoutError("synthetic unknown side effect")

        monkeypatch.setattr(execution, "dispatch_embedding_batch_control", dispatch)
    elif failure == "receive":
        value.channel.receive_allocation.side_effect = TimeoutError("synthetic unknown root")
    else:

        def revoke():
            value.denied = True
            return value.frames.ready

        value.channel.receive_allocation.side_effect = revoke
    with (
        pytest.raises((ValueError, TimeoutError)),
        value.operation.open(value.request, value.allocation),
    ):
        pytest.fail("unknown/revoked execution was offered")
    value.denied = False
    original = history(value)
    assert original.state == "CLAIMED" and original.route is None and original.bound is None
    with value.operation.open(value.request, value.allocation) as replay:
        assert replay.history == original
    assert len(value.dispatched) == 1


def test_interruption_during_child_preparation_keeps_route_and_disables_closed_active_handle(
    owner_case, monkeypatch
):
    value = owner_case
    with (
        pytest.raises(RuntimeError),
        value.operation.open(value.request, value.allocation) as active,
    ):
        prepare_synthetic_children(value, active, monkeypatch)
        raise RuntimeError("synthetic owner interruption")
    original = history(value)
    assert original.state == "RUNNING" and original.bound is None
    with pytest.raises(ValueError):
        active.run(value.bound, value.batch, authorization=value.authorization)
    with value.operation.open(value.request, value.allocation) as replay:
        assert replay.history == original
    assert len(value.dispatched) == 1


@pytest.mark.parametrize("failure", ("child_authority", "result"))
def test_child_denial_or_bad_result_is_not_a_completed_execution(owner_case, monkeypatch, failure):
    value = owner_case
    before = receipt_count(value)
    with value.operation.open(value.request, value.allocation) as active:
        prepare_synthetic_children(value, active, monkeypatch)
        if failure == "child_authority":
            value.source_denied = True
        else:
            execution.read_verified_embedding_batch_result.side_effect = ValueError(
                "synthetic result mismatch"
            )
        with pytest.raises((PermissionError, ValueError)):
            active.run(value.bound, value.batch, authorization=value.authorization)
        with pytest.raises(ValueError):
            active.run(value.bound, value.batch, authorization=value.authorization)
    original = history(value)
    assert (original.bound is None) == (failure == "child_authority")
    assert receipt_count(value) == before and not value.acked
    value.source_denied = False
    with value.operation.open(value.request, value.allocation) as replay:
        assert replay.history == original
    assert len(value.dispatched) == 1


def test_two_actual_parent_roots_offer_only_one_original_physical_dispatch(owner_case):
    value = owner_case
    barrier = Barrier(2)

    def open_once():
        barrier.wait(timeout=10)
        with value.operation.open(value.request, value.allocation) as result:
            return type(result), result.history.job_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_once) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert {kind for kind, _ in results} == {
        execution.ActiveEmbeddingBatchExecution,
        execution.ExistingEmbeddingBatchExecution,
    }
    assert results[0][1] == results[1][1] and len(value.dispatched) == 1


def test_denied_current_source_never_creates_parent_or_starts_root(owner_case):
    value = owner_case
    value.denied = True
    with (
        pytest.raises(ValueError),
        value.operation.open(value.request, value.allocation),
    ):
        pytest.fail("denied caller was offered execution")
    value.denied = False
    assert history(value) is None and value.dispatched == []


@pytest.mark.parametrize("field", ("source_commit", "controller_release"))
def test_mutable_or_unpinned_release_is_not_accepted_as_execution_configuration(owner_case, field):
    value = owner_case
    pins = {"source_commit": "a" * 40, "controller_release": RELEASE}
    pins[field] = "latest"
    with pytest.raises(ValueError):
        execution.CatalogEmbeddingBatchExecution(value.owner, value.publisher, **pins)
    assert history(value) is None and value.dispatched == []
