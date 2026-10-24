"""Marker-guarded disposable PG only; synthetic identity/root proof and no GPU/NAS."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
)
from eom_orchestrator.embedding_benchmark_jobs import submit_benchmark_job_in_session
from eom_orchestrator.embedding_benchmark_launch_history import BenchmarkLaunchJournal
from eom_orchestrator.embedding_benchmark_preack_recovery import BenchmarkPreackRecoveryApplication
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from tests.integration.test_embedding_benchmark_prelaunch_failure import SyntheticRecoveryAdmission
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_benchmark_job_fixtures import benchmark_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import (
    SyntheticResultReader,
    invocation_for,
    receipt_for,
)
from tests.unit.test_embedding_benchmark_preack_recovery import root_observation
from tests.unit.test_embedding_device_benchmark_budget import successor_request_v12

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def case_for(engine):
    request, inputs = benchmark_case()
    template = successor_request_v12()
    request = BenchmarkOwnerRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "schema_version": template.schema_version,
                "execution_policy": template.execution_policy.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    admission = SyntheticRecoveryAdmission(request, inputs)
    sessions = sessionmaker(engine, expire_on_commit=False)
    reader = SyntheticResultReader()
    journal = BenchmarkLaunchJournal(admission, reader)
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    storage = sessions, SimpleNamespace(request=request, inputs=inputs), reader, journal, job_id
    for ordinal in (1, 2):
        invocation = BenchmarkWorkerInvocation.model_validate(
            seal(
                invocation_for(storage, ordinal).model_dump(mode="json")
                | {
                    "schema_version": "embedding-device-benchmark-invocation/1.2",
                    "execution_policy": request.execution_policy.model_dump(mode="json"),
                },
                "invocation_sha256",
            )
        )
        with sessions() as session, session.begin():
            journal.reserve(session, request, invocation)
            if ordinal == 1:
                journal.record(session, request, receipt_for(storage, invocation))
    barrier = Barrier(2)
    proof = root_observation(request, invocation)

    class Captured:
        observation = proof

        def assert_current(self):
            pass  # Synthetic stability, not an actual root-origin or GPU assertion.

    class Inspection:
        @contextmanager
        def capture(self, actual_request, actual_invocation):
            assert actual_request == request and actual_invocation == invocation
            barrier.wait(timeout=20)
            yield Captured()

    application = BenchmarkPreackRecoveryApplication(
        sessions, admission=admission, inspection=Inspection()
    )
    return SimpleNamespace(
        sessions=sessions,
        admission=admission,
        app=application,
        invocation=invocation,
        request=request,
        job_id=job_id,
        journal=journal,
    )


def test_postgres_concurrent_preack_recovery_is_exactly_one_append(guarded_engine):
    case = case_for(guarded_engine)

    def recover():
        return case.app.recover(
            case.request, job_id=case.job_id, execution_id=case.invocation.execution_id
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            f.result(timeout=40) for f in (executor.submit(recover), executor.submit(recover))
        )
    assert sorted(r.created for r in results) == [False, True]
    assert results[0].decision == results[1].decision
    assert not recover().created  # Replay does not recapture/wait at the two-party barrier.
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert len(history.launches) == len(history.retired_preack_launches) == 1
        assert history.launches[0].receipt is not None
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == case.job_id,
                    JobEventRecord.event == "BENCHMARK_CUDA_PREACK_RECOVERED",
                )
            )
            == 1
        )


def test_postgres_late_authorization_rolls_back_preack_event(guarded_engine):
    case = case_for(guarded_engine)
    case.admission.fail_after_event = "BENCHMARK_CUDA_PREACK_RECOVERED"

    def recover():
        with pytest.raises(ValueError, match="REVOKED"):
            case.app.recover(
                case.request, job_id=case.job_id, execution_id=case.invocation.execution_id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(recover), executor.submit(recover))
        for future in futures:
            future.result(timeout=40)
    case.admission.fail_after_event = None
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert len(history.launches) == 2 and not history.retired_preack_launches
