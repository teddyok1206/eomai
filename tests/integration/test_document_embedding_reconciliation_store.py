"""Actual existing Job/CPU completion concurrency; synthetic OS/model/IAM leaves only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.document_embedding_reconciliation_store import (
    DocumentEmbeddingReconciliationStore,
)
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.document_embedding_reconciliation import (
    DOCUMENT_RECONCILIATION_PROTOCOL,
    DocumentEmbeddingReconciliationCompleted,
    DocumentEmbeddingReconciliationRequest,
    document_reconciliation_parent,
    prepare_document_reconciliation_intent,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation, EmbeddingBatchRoute
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.local_embedding_completed_read import read_completed_local_embedding
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from sqlalchemy import func, insert, select, text

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def reconciliation(execution):
    value = execution
    started = value.start()
    assert value.advance(*started) is True
    value.finish(*started)
    with value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, started[0].workflow_id)
        output = read_completed_local_embedding(session, value.owner, workflow)
        history = value.gpu.store.read(session)
        assert history is not None and history.state == "SUCCEEDED"
    request = DocumentEmbeddingReconciliationRequest.model_validate(
        seal(
            dict(
                schema_version=DOCUMENT_RECONCILIATION_PROTOCOL,
                message_type="REQUEST",
                source_request_sha256=value.gpu.request.parent_request_sha256,
                origin_parent_job_id=history.job_id,
                origin_parent_request_sha256=value.gpu.request.request_sha256,
                scope=value.gpu.request.scope.model_dump(mode="json"),
                cpu_request_sha256=value.request.request_sha256,
                cpu_output=output.model_dump(mode="json"),
            ),
            "request_sha256",
        )
    )
    first = prepare_document_reconciliation_intent(
        request,
        value.gpu.request,
        ordinal=1,
        previous_parent_job_id=history.job_id,
        previous_parent_request_sha256=value.gpu.request.request_sha256,
    )
    return SimpleNamespace(
        value=value,
        started=started,
        request=request,
        first=first,
        store=DocumentEmbeddingReconciliationStore(request),
    )


def authorize(case, session):
    """Actual completed-read leaf, not a DTO or historical command token."""
    workflow = session.get(WorkflowInstanceRecord, case.started[0].workflow_id)
    assert (
        read_completed_local_embedding(session, case.value.owner, workflow)
        == case.request.cpu_output
    )


def ensure(case):
    with case.value.sessions.begin() as session:
        return case.store.ensure(session, case.first, authorize=lambda: authorize(case, session))


def close_precompute_busy_parent(case, intent):
    """Synthetic allocation/BUSY values; actual Plan schema/history/SQL ownership."""
    value = case.value
    parent = document_reconciliation_parent(value.gpu.request, intent)
    control = seal(
        value.gpu.allocation.control_request.model_dump(mode="json")
        | dict(
            parent_request_sha256=parent.request_sha256,
            allocation_attempt_id="embeddingallocation_" + uuid4().hex,
        ),
        "message_sha256",
    )
    allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            value.gpu.allocation.model_dump(mode="json")
            | dict(request_sha256=parent.request_sha256, control_request=control),
            "record_sha256",
        )
    )
    with (
        value.sessions.begin() as session,
        value.gpu.operation.admission.admit(session, parent) as sources,
    ):
        store = EmbeddingBatchPlanStore(parent, sources.selection, sources.policy)
        allocated, created = store.allocate(session, allocation)
        assert created
        original = value.gpu.adapter.unavailable.history.route
        observation = EmbeddingGpuAllocationObservation.model_validate(
            seal(
                original.observation.model_dump(mode="json")
                | dict(
                    request_sha256=parent.request_sha256,
                    allocation_attempt_id=allocation.control_request.allocation_attempt_id,
                ),
                "observation_sha256",
            )
        )
        decision = plan_embedding_device_route(sources.policy, observation)
        route = EmbeddingBatchRoute.model_validate(
            seal(
                original.model_dump(mode="json")
                | dict(
                    request_sha256=parent.request_sha256,
                    allocation_record_sha256=allocation.record_sha256,
                    observation=observation.model_dump(mode="json"),
                    decision=decision.model_dump(mode="json"),
                ),
                "record_sha256",
            )
        )
        store.route(session, route)
        return allocated.job_id


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_concurrent_head_is_one_identity_and_replays_after_client_interruption(reconciliation):
    case, gate = reconciliation, Barrier(2)

    def create(_index):
        gate.wait(timeout=30)
        return ensure(case)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, concurrent = tuple(pool.map(create, range(2)))
    assert first == concurrent and first.intent == case.first and first.completion is None
    assert ensure(case) == first
    with case.value.sessions.begin() as session:
        count = session.scalar(
            select(func.count())
            .select_from(JobEventRecord)
            .where(JobEventRecord.job_id == first.job_id)
        )
        assert count == 6
        job = session.get(JobRecord, first.job_id)
        assert job.worker_slot_id is None
        raw = canonical_json_bytes(job.request)
        assert len(raw) < 16 * 1024 and b'"vectors":' not in raw and b'"text":' not in raw
    assert case.value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_concurrent_advance_uses_one_next_intent_without_another_cpu_or_worker(reconciliation):
    case = reconciliation
    first = ensure(case)
    previous_job_id = close_precompute_busy_parent(case, first.intent)
    successor = prepare_document_reconciliation_intent(
        case.request,
        case.value.gpu.request,
        ordinal=2,
        previous_parent_job_id=previous_job_id,
        previous_parent_request_sha256=first.intent.parent_request_sha256,
    )
    gate = Barrier(2)

    def advance(_index):
        gate.wait(timeout=30)
        with case.value.sessions.begin() as session:
            return case.store.advance(
                session,
                first.intent,
                successor,
                authorize=lambda: authorize(case, session),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(advance, range(2)))
    assert left == right and left.intent == successor
    with case.value.sessions.begin() as session:
        assert case.store.read(session) == left
        count = session.scalar(
            select(func.count())
            .select_from(JobEventRecord)
            .where(JobEventRecord.job_id == left.job_id)
        )
        assert count == 7
    assert case.value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_forged_predecessor_or_revoked_source_never_advances_or_repairs_history(reconciliation):
    case = reconciliation
    first = ensure(case)
    forged = prepare_document_reconciliation_intent(
        case.request,
        case.value.gpu.request,
        ordinal=2,
        previous_parent_job_id="job_" + "f" * 32,
        previous_parent_request_sha256=first.intent.parent_request_sha256,
    )
    with pytest.raises(ValueError), case.value.sessions.begin() as session:
        case.store.advance(
            session, first.intent, forged, authorize=lambda: authorize(case, session)
        )
    case.value.current.allowed = False
    with pytest.raises((ValueError, AssertionError)), case.value.sessions.begin() as session:
        case.store.ensure(session, case.first, authorize=lambda: authorize(case, session))
    case.value.current.allowed = True
    with case.value.sessions.begin() as session:
        assert case.store.read(session) == first
    assert case.value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_completed_read_needs_no_command_lease_and_never_changes_a_failure(reconciliation):
    case = reconciliation
    with case.value.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, case.started[1].command_id)
        command.lease_expires_at = datetime.now(UTC) - timedelta(hours=2)
    with case.value.sessions.begin() as session:
        authorize(case, session)
    with case.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, case.started[0].workflow_id)
        workflow.state = "FAILED"  # Disposable terminal-state fixture only.
    with pytest.raises(ValueError), case.value.sessions.begin() as session:
        authorize(case, session)
    with case.value.sessions.begin() as session:
        assert session.get(WorkflowInstanceRecord, case.started[0].workflow_id).state == "FAILED"
    assert case.value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_terminal_head_replays_exact_completion_without_overwriting_cpu_or_failed_history(
    reconciliation,
):
    case = reconciliation
    first = ensure(case)
    completion = DocumentEmbeddingReconciliationCompleted.model_validate(
        seal(
            dict(
                schema_version=DOCUMENT_RECONCILIATION_PROTOCOL,
                message_type="COMPLETED",
                reconciliation_request_sha256=case.request.request_sha256,
                intent_sha256=first.intent.intent_sha256,
                output=case.request.cpu_output.model_dump(mode="json"),
            ),
            "completion_sha256",
        )
    )
    # Explicit store-only seam: production separately verifies the new CUDA
    # Workflow/output. The store cannot obtain source/compute authority from DTOs.
    for _ in range(2):
        with case.value.sessions.begin() as session:
            done = case.store.complete(
                session, completion, authorize=lambda: authorize(case, session)
            )
        assert done.completion == completion
    with case.value.sessions.begin() as session:
        assert case.store.read(session) == done
        assert session.get(JobRecord, first.job_id).status == "SUCCEEDED"
    successor = prepare_document_reconciliation_intent(
        case.request,
        case.value.gpu.request,
        ordinal=2,
        previous_parent_job_id=case.request.origin_parent_job_id,
        previous_parent_request_sha256=first.intent.parent_request_sha256,
    )
    with pytest.raises(ValueError), case.value.sessions.begin() as session:
        case.store.advance(
            session, first.intent, successor, authorize=lambda: authorize(case, session)
        )


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_late_authority_denial_rolls_back_new_intent_without_touching_completed_cpu(reconciliation):
    case = reconciliation
    calls = []
    with pytest.raises(PermissionError), case.value.sessions.begin() as session:

        def late_revocation():
            authorize(case, session)
            calls.append("current")
            if len(calls) == 2:
                raise PermissionError("synthetic late revocation")

        case.store.ensure(session, case.first, authorize=late_revocation)
    with case.value.sessions.begin() as session:
        assert case.store.read(session) is None
        assert session.get(WorkflowInstanceRecord, case.started[0].workflow_id).state == "COMPLETED"
    assert case.value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_latest_event_access_uses_existing_unique_btree_with_long_history(reconciliation):
    case = reconciliation
    first = ensure(case)
    with case.value.sessions.begin() as session:
        # Deliberately synthetic *query-plan* data, not valid reconciliation
        # events. No production history or application state is rewritten.
        session.execute(
            insert(JobEventRecord),
            [
                dict(
                    job_id=first.job_id,
                    sequence=number,
                    from_state="RUNNING",
                    to_state="RUNNING",
                    event="TEST_QUERY_PLAN_SCALE",
                    data={},
                )
                for number in range(7, 10007)
            ],
        )
        session.execute(text("ANALYZE job_events"))
        plan = session.execute(
            text(
                "EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM job_events "
                "WHERE job_id=:job_id AND sequence>5 ORDER BY sequence DESC LIMIT 5"
            ),
            {"job_id": first.job_id},
        ).scalar_one()[0]["Plan"]

        def nodes(value):
            yield value
            for child in value.get("Plans", ()):
                yield from nodes(child)

        indexed = [
            node for node in nodes(plan) if node.get("Index Name") == "uq_job_events_sequence"
        ]
        assert indexed and all(node["Actual Rows"] <= 5 for node in indexed), [
            (node.get("Node Type"), node.get("Index Name"), node.get("Actual Rows"))
            for node in nodes(plan)
        ]
