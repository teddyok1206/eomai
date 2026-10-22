"""Disposable PG row locks/replay only; root inspection and identity are synthetic.

No ambient URL alone authorizes writes. Reuse the existing marker-guarded
fixture; no installed units, native models, GPU, NAS or actual operators.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    MAX_POSTSTART_FAILURE_BYTES,
    POSTSTART_FAILURE_CODE,
    POSTSTART_FAILURE_EVENT,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
    benchmark_poststart_failure_bytes,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, new_revision_id, sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import BenchmarkJobAdmissionError, benchmark_job_key
from eom_orchestrator.embedding_benchmark_launch_history import (
    POSTSTART_PREDECESSOR_EVENT,
    RECORDED_EVENT,
    RESERVED_EVENT,
)
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
    submit_benchmark_poststart_successor_in_session,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from sqlalchemy import Engine, Text, cast, func, select

from tests.integration.test_embedding_benchmark_prelaunch_failure import (
    _case as _base_case,
)
from tests.integration.test_embedding_benchmark_prelaunch_failure import (
    _events as _events,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@dataclass(frozen=True)
class SyntheticCapturedPoststartInspection:
    observation: BenchmarkPoststartObservation

    def assert_current(self):
        """Synthetic filesystem stability, never a real root-origin or PID1 assertion."""


class SyntheticPoststartInspection:
    def __init__(self, case):
        self.request, self.invocation = case.request, case.invocation
        self.barrier = None
        self.captures = 0
        body = observation(self.request, self.invocation).model_dump(mode="json")
        body["observed_at"] = (
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
        self.observation = BenchmarkPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )

    @contextmanager
    def capture(self, request, invocation):
        assert request == self.request and invocation == self.invocation
        self.captures += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        yield SyntheticCapturedPoststartInspection(self.observation)


def _case(engine):
    # Reuse the exact original six-event Job/reservation and its synthetic admission;
    # only the post-start inspector/application differ. No parallel DB setup path.
    case = _base_case(engine)
    case.inspection = SyntheticPoststartInspection(case)
    case.application = BenchmarkPoststartFailureApplication(
        case.sessions, admission=case.admission, inspection=case.inspection
    )
    return case


def _successor(case):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
    )
    policy = case.request.execution_policy.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-policy/1.1",
        "policy_revision_id": "embeddingbenchmarkpolicyrev_" + uuid4().hex,
        "timeout_seconds": 600,
    }
    body = case.request.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-request/1.1",
        "benchmark_revision_id": revision,
        "execution_policy": seal(policy, "policy_sha256"),
    }
    body["input_manifest"]["artifact_revision_id"] = new_revision_id()
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    case.admission.register(request, inputs)
    return request


def _submit(case, request, reference):
    with case.sessions() as session, session.begin():
        job, created = submit_benchmark_poststart_successor_in_session(
            session, request, reference, source_admission=case.admission
        )
        return job.job_id, created


def test_postgres_concurrent_started_failure_closes_once_preserving_partial_metadata_and_history(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    start = Barrier(2)
    case.inspection.barrier = Barrier(2)

    def close():
        start.wait(timeout=10)
        return case.application.close(case.request, job_id=case.job_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(close) for _ in range(2)]
        results = tuple(future.result(timeout=30) for future in futures)
    case.inspection.barrier = None
    assert sorted(result.created for result in results) == [False, True]
    recorded = next(result for result in results if result.created)
    assert all(result.decision == recorded.decision for result in results)
    assert all(result.event_sequence == 7 for result in results)
    captures = case.inspection.captures
    replay = case.application.close(case.request, job_id=case.job_id)
    assert not replay.created and replay.decision == recorded.decision
    assert replay.predecessor == recorded.predecessor and case.inspection.captures == captures
    with case.sessions() as session, session.begin():
        job = session.get(JobRecord, case.job_id)
        assert job.status == "FAILED" and job.error_code == POSTSTART_FAILURE_CODE
        assert job.request == case.request.model_dump(mode="json")
        events = _events(session, case.job_id)
        assert tuple(row.sequence for row in events) == tuple(range(1, 8))
        assert [row.event for row in events].count(POSTSTART_FAILURE_EVENT) == 1
        assert [row.event for row in events].count(RESERVED_EVENT) == 1
        assert RECORDED_EVENT not in {row.event for row in events}
        assert events[-1].data == recorded.decision.model_dump(mode="json")
        raw = benchmark_poststart_failure_bytes(recorded.decision)
        assert len(raw) < MAX_POSTSTART_FAILURE_BYTES
        assert all(token not in raw for token in (b'"text"', b'"vectors"', b'"input_ids"'))
        assert (
            session.scalar(
                select(func.octet_length(cast(JobEventRecord.data, Text))).where(
                    JobEventRecord.job_id == case.job_id,
                    JobEventRecord.sequence == 7,
                )
            )
            < MAX_POSTSTART_FAILURE_BYTES
        )
        for model in (ArtifactRecord, ArtifactRevisionRecord):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.job_id == case.job_id)
                )
                == 0
            )
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert (
            history.poststart_failure.decision == recorded.decision
            and history.prelaunch_failure is None
        )
        assert (
            history.launches[0].invocation == case.invocation
            and history.launches[0].receipt is None
        )


def test_postgres_concurrent_explicit_budget_successor_allocates_one_job_and_reference(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    closed = case.application.close(case.request, job_id=case.job_id)
    request = _successor(case)
    start = Barrier(2)

    def submit():
        start.wait(timeout=10)
        try:
            return _submit(case, request, closed.predecessor)
        except BenchmarkJobAdmissionError as error:
            # Existing global allocation is intentionally nonblocking. The failed
            # transaction rolls back; replay must reuse this exact request/key.
            assert error.code == "BENCHMARK_JOB_SUBMISSION_BUSY"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        results = tuple(future.result(timeout=30) for future in futures)
    completed = tuple(result for result in results if result is not None)
    assert len(completed) in (1, 2)
    assert sum(created for _identifier, created in completed) == 1
    assert len({identifier for identifier, _created in completed}) == 1
    identifier = completed[0][0]
    assert identifier != case.job_id and _submit(case, request, closed.predecessor) == (
        identifier,
        False,
    )
    with case.sessions() as session:
        parent, child = session.get(JobRecord, case.job_id), session.get(JobRecord, identifier)
        assert parent.status == "FAILED" and parent.request == case.request.model_dump(mode="json")
        assert child.status == "VALIDATED" and child.request == request.model_dump(mode="json")
        assert request.execution_policy.policy_id == case.request.execution_policy.policy_id
        assert (
            request.execution_policy.policy_revision_id
            != case.request.execution_policy.policy_revision_id
        )
        assert request.execution_policy.timeout_seconds == 600
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.request["benchmark_id"].as_string() == case.request.benchmark_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            == 1
        )
        events = _events(session, identifier)
        assert tuple(row.sequence for row in events) == (1, 2, 3)
        assert events[-1].event == POSTSTART_PREDECESSOR_EVENT
        assert events[-1].data == closed.predecessor.model_dump(mode="json")
        assert _events(session, case.job_id)[-1].data == closed.decision.model_dump(mode="json")


def test_postgres_late_closure_authority_revocation_rolls_back_then_original_can_close(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    case.admission.fail_after_event = POSTSTART_FAILURE_EVENT
    with pytest.raises(ValueError, match="LATE_AUTHORIZATION_REVOKED"):
        case.application.close(case.request, job_id=case.job_id)
    assert case.admission.late_failures == 1
    with case.sessions() as session:
        job = session.get(JobRecord, case.job_id)
        assert job.status == "RUNNING" and job.error_code is None and job.completed_at is None
        assert len(_events(session, case.job_id)) == 6
    case.admission.fail_after_event = None
    closed = case.application.close(case.request, job_id=case.job_id)
    assert closed.created and closed.decision.observation == case.inspection.observation


def test_postgres_late_successor_authority_revocation_rolls_back_all_new_identity_and_events(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    closed = case.application.close(case.request, job_id=case.job_id)
    request = _successor(case)
    case.admission.fail_after_event = POSTSTART_PREDECESSOR_EVENT
    with pytest.raises(ValueError, match="LATE_AUTHORIZATION_REVOKED"):
        _submit(case, request, closed.predecessor)
    assert case.admission.late_failures == 1
    with case.sessions() as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
        assert len(_events(session, case.job_id)) == 7
        assert session.get(JobRecord, case.job_id).status == "FAILED"
    case.admission.fail_after_event = None
    identifier, created = _submit(case, request, closed.predecessor)
    assert created and _submit(case, request, closed.predecessor) == (identifier, False)


def test_postgres_unclosed_parent_cannot_allocate_budget_successor(guarded_engine: Engine):
    case = _case(guarded_engine)
    request = _successor(case)
    reference = BenchmarkPoststartPredecessorReference(
        schema_version="embedding-benchmark-poststart-failure/1.0",
        kind="PREDECESSOR_REFERENCE",
        job_id=case.job_id,
        execution_id=case.invocation.execution_id,
        request_sha256=case.request.request_sha256,
        invocation_sha256=case.invocation.invocation_sha256,
        event_sequence=7,
        decision_sha256=content_sha256("synthetic unrecorded poststart closure"),
    )
    with pytest.raises(BenchmarkJobAdmissionError, match="PREDECESSOR_NOT_TERMINAL"):
        _submit(case, request, reference)
    with case.sessions() as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert len(_events(session, case.job_id)) == 6
