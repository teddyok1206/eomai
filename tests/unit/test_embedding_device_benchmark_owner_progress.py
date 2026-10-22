"""One-launch clean boundaries on synthetic SQLite; no real login, unit or inference grant."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    benchmark_timeout_seconds,
    embedding_device_benchmark_bytes,
)
from eom_orchestrator import embedding_device_benchmark_owner as module
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchProgress
from eom_orchestrator.models import JobEventRecord, JobRecord
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_budget import successor_policy
from tests.unit.test_embedding_device_benchmark_owner import owner_case as owner_case


def test_six_clean_progress_calls_dispatch_the_fixed_sequence_once_on_one_original_job(owner_case):
    case = owner_case
    original_request = embedding_device_benchmark_bytes(case.request)
    original_inputs = embedding_device_benchmark_bytes(case.inputs)
    progresses = []
    for ordinal in range(1, 7):
        progress = case.owner.run_next_launch(case.request)
        progresses.append(progress)
        assert type(progress) is BenchmarkLaunchProgress
        assert progress.dispatch_count == 1
        assert progress.request_sha256 == case.request.request_sha256
        assert len(progress.receipts) == len(case.execution.calls) == ordinal
        assert progress.state == ("RUNNING" if ordinal < 6 else "VALIDATING_RESULT")
        assert progress.next_launch_ordinal == (ordinal + 1 if ordinal < 6 else None)
        assert not case.capacity[0] and case.admission.active == 0
        with case.sessions() as session:
            assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
            assert session.get(JobRecord, progress.job_id).status == progress.state
            assert session.scalar(select(func.count()).select_from(JobEventRecord)) == (
                5 + ordinal * 2 + int(ordinal == 6)
            )
    assert [invocation.device for invocation in case.execution.calls] == [
        "CPU",
        "CUDA",
        "CUDA",
        "CPU",
        "CPU",
        "CUDA",
    ]
    assert len({invocation.execution_id for invocation in case.execution.calls}) == 6
    assert {progress.job_id for progress in progresses} == {progresses[0].job_id}
    assert embedding_device_benchmark_bytes(case.request) == original_request
    assert embedding_device_benchmark_bytes(case.inputs) == original_inputs
    assert all(
        progress.receipts == progresses[-1].receipts[:ordinal]
        for ordinal, progress in enumerate(progresses, 1)
    )
    with pytest.raises(FrozenInstanceError):
        progresses[0].state = "VALIDATING_RESULT"


def test_complete_progress_replay_reads_evidence_without_installation_or_capacity(
    owner_case, monkeypatch
):
    case = owner_case
    complete = case.owner.run_launches(case.request)
    case.owner.execution = None

    def unavailable():
        pytest.fail("completed replay must not reacquire numerical capacity")

    monkeypatch.setattr(module, "native_cpu_capacity", unavailable)
    replay = case.owner.run_next_launch(case.request)
    assert replay.dispatch_count == 0 and len(case.execution.calls) == 6
    assert replay.job_id == complete.job_id and replay.receipts == complete.receipts
    assert replay.state == "VALIDATING_RESULT" and replay.next_launch_ordinal is None


def test_full_series_call_resumes_a_clean_progress_prefix_without_replacing_executions(owner_case):
    case = owner_case
    first = case.owner.run_next_launch(case.request)
    second = case.owner.run_next_launch(case.request)
    original = tuple(case.execution.calls)
    complete = case.owner.run_launches(case.request)
    assert complete.dispatch_count == 4 and complete.state == "VALIDATING_RESULT"
    assert complete.job_id == first.job_id == second.job_id
    assert complete.receipts[:2] == second.receipts
    assert tuple(case.execution.calls[:2]) == original
    assert len(case.execution.calls) == 6


@pytest.mark.parametrize("failed_ordinal", (1, 2, 6))
def test_uncertain_dispatch_keeps_its_original_reservation_and_prevents_any_replacement(
    owner_case, failed_ordinal
):
    case = owner_case
    case.execution.fail_ordinal = failed_ordinal
    for _ in range(1, failed_ordinal):
        case.owner.run_next_launch(case.request)
    with pytest.raises(ValueError, match="EXECUTION_UNCERTAIN"):
        case.owner.run_next_launch(case.request)
    original = tuple(case.execution.calls)
    case.execution.fail_ordinal = None
    with pytest.raises(ValueError, match="ORIGINAL_EXECUTION_UNRESOLVED"):
        case.owner.run_next_launch(case.request)
    assert tuple(case.execution.calls) == original
    assert len(original) == failed_ordinal and not case.capacity[0]
    with case.sessions() as session, session.begin():
        jobs = tuple(session.scalars(select(JobRecord)))
        assert len(jobs) == 1 and jobs[0].status == "RUNNING"
        history = case.owner.journal.read(session, case.request, job_id=jobs[0].job_id)
        assert len(history.launches) == failed_ordinal and history.launches[-1].receipt is None


def test_authority_revoked_after_output_does_not_return_a_clean_progress_boundary(owner_case):
    case = owner_case
    case.execution.revoke_after_output = True
    with pytest.raises(ValueError, match="EXPIRED_AFTER_PUBLICATION"):
        case.owner.run_next_launch(case.request)
    assert len(case.reader.members) == len(case.execution.calls) == 1
    case.admission.late_error = None
    with pytest.raises(ValueError, match="ORIGINAL_EXECUTION_UNRESOLVED"):
        case.owner.run_next_launch(case.request)
    assert len(case.execution.calls) == 1 and not case.capacity[0]


def test_failed_receipt_is_preserved_but_is_not_a_clean_progress_or_reauthentication_boundary(
    owner_case,
):
    case = owner_case
    case.execution.failed_result = True
    with pytest.raises(ValueError, match="SERIES_INCOMPLETE"):
        case.owner.run_next_launch(case.request)
    assert len(case.execution.calls) == 1 and not case.capacity[0]
    with case.sessions() as session, session.begin():
        job = session.scalar(select(JobRecord))
        history = case.owner.journal.read(session, case.request, job_id=job.job_id)
        assert len(history.launches) == 1 and history.launches[0].receipt is not None
        assert job.status == "RUNNING"
    with pytest.raises(ValueError, match="PREVIOUS_NOT_COMPLETED"):
        case.owner.run_next_launch(case.request)
    assert len(case.execution.calls) == 1


def test_each_clean_boundary_requires_current_authority_again_without_extending_it(owner_case):
    case = owner_case
    first = case.owner.run_next_launch(case.request)
    case.admission.late_error = ValueError("SYNTHETIC_EXPIRED_BETWEEN_CALLS")
    with pytest.raises(ValueError, match="EXPIRED_BETWEEN_CALLS"):
        case.owner.run_next_launch(case.request)
    assert len(case.execution.calls) == 1
    assert first.state == "RUNNING" and first.next_launch_ordinal == 2
    case.admission.late_error = None
    second = case.owner.run_next_launch(case.request)
    assert second.job_id == first.job_id and second.receipts[:1] == first.receipts
    assert len(case.execution.calls) == 2


@pytest.mark.parametrize("fault", ("missing", "runtime", "orphan", "source"))
def test_progress_requires_installed_capacity_and_authority_before_new_job(
    owner_case, monkeypatch, fault
):
    case = owner_case

    def unavailable(*_args):
        raise ValueError("SYNTHETIC_UNAVAILABLE")

    if fault == "missing":
        case.owner.execution = None
    elif fault == "runtime":
        monkeypatch.setattr(case.execution, "assert_installed", unavailable)
    elif fault == "orphan":
        monkeypatch.setattr(module, "require_no_active_native_cpu_execution", unavailable)
    else:
        case.admission.late_error = ValueError("SYNTHETIC_UNAVAILABLE")
    with pytest.raises(ValueError):
        case.owner.run_next_launch(case.request)
    assert not case.execution.calls and not case.capacity[0]
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


@pytest.mark.parametrize("version", ("1.0", "1.1"))
def test_owner_projects_the_explicit_request_policy_to_the_matching_invocation_version(
    owner_case, version
):
    case = owner_case
    if version == "1.1":
        body = case.request.model_dump(mode="json")
        body.update(
            schema_version="embedding-device-benchmark-request/1.1",
            execution_policy=successor_policy().model_dump(mode="json"),
        )
        case.request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
        case.admission.request = case.request
    progress = case.owner.run_next_launch(case.request)
    invocation = case.execution.calls[0]
    assert invocation.schema_version == "embedding-device-benchmark-invocation/" + version
    assert invocation.execution_policy == case.request.execution_policy
    assert benchmark_timeout_seconds(invocation.execution_policy) == (
        600 if version == "1.1" else 180
    )
    assert invocation.owner_request_sha256 == case.request.request_sha256
    assert invocation.family == case.request.family
    assert invocation.runtime == case.request.cpu
    assert progress.state == "RUNNING" and progress.dispatch_count == 1
