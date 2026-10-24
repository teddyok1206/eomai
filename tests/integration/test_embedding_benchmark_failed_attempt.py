"""Known failed attempt reconciliation in marker-guarded disposable PG; no GPU/NAS."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_orchestrator.embedding_benchmark_launch_recovery import BenchmarkLaunchRecoveryApplication
from eom_orchestrator.models import JobEventRecord, JobRecord
from sqlalchemy import func, select

from tests.integration.test_embedding_benchmark_preack_recovery import case_for
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_embedding_benchmark_failed_attempt import failed_observation

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def failed_case(engine):
    case = case_for(engine)
    proof = failed_observation(case.request, case.invocation)
    barrier = Barrier(2)

    @contextmanager
    def capture(request, invocation):
        assert request == case.request and invocation == case.invocation
        barrier.wait(timeout=20)
        yield SimpleNamespace(observation=proof, assert_current=lambda: None)

    case.app = BenchmarkLaunchRecoveryApplication(
        case.sessions, admission=case.admission, inspection=SimpleNamespace(capture=capture)
    )
    return case


def test_postgres_failed_attempt_concurrent_reconciliation_has_one_event(guarded_engine):
    case = failed_case(guarded_engine)

    def recover():
        return case.app.recover(
            case.request, job_id=case.job_id, execution_id=case.invocation.execution_id
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            f.result(timeout=40) for f in (executor.submit(recover), executor.submit(recover))
        )
    assert sorted(result.created for result in results) == [False, True]
    assert results[0].decision == results[1].decision
    assert not recover().created
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert len(history.failed_attempts) == 1 and not history.retired_preack_launches
        assert len(history.launches) == 1 and history.launches[0].receipt is not None
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == case.job_id,
                    JobEventRecord.event == "BENCHMARK_FAILED_ATTEMPT_RECONCILED",
                )
            )
            == 1
        )


def test_postgres_failed_attempt_late_authorization_rolls_back_all_changes(guarded_engine):
    case = failed_case(guarded_engine)
    case.admission.fail_after_event = "BENCHMARK_FAILED_ATTEMPT_RECONCILED"

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
        assert len(history.launches) == 2 and not history.retired_launches
