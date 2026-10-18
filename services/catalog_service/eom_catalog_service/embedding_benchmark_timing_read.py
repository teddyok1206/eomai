"""Current-source canonical timing assessment of the original completed series; read only."""

from __future__ import annotations

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.state_machine import JobState

from eom_catalog_service.embedding_benchmark_owner_admission import CatalogBenchmarkOwnerAdmission
from eom_catalog_service.embedding_benchmark_timing_evidence import (
    BenchmarkSeriesTimingAssessment,
    assess_benchmark_series_timings,
)


def read_completed_benchmark_series_timings(
    owner: BenchmarkExecutionOwner, request: BenchmarkOwnerRequest, *, job_id: str
) -> BenchmarkSeriesTimingAssessment:
    """One original Job, one current source root, no launch/probe/claim/publication.

    Reuse the journal's canonical result materialization rather than independently
    parsing its worker members again. Missing or unresolved history is not retried.
    """
    if (
        type(owner) is not BenchmarkExecutionOwner
        or type(owner.admission) is not CatalogBenchmarkOwnerAdmission
    ):
        raise ValueError("BENCHMARK_TIMING_READER_OWNER_INVALID")
    admission = owner.admission
    with (
        owner.sessions() as session,
        session.begin(),
        admission.admit_execution_in_session(session, request) as inputs,
    ):
        history = owner.journal.read(session, request, job_id=job_id)
        if history.job_state != JobState.VALIDATING_RESULT:
            raise ValueError("BENCHMARK_TIMING_SERIES_NOT_READY")
        completed = owner.journal.require_completed_launches(session, request, job_id=job_id)
        runs = tuple(
            admission.read_launch_timings_in_session(session, request, launch)
            for launch in completed
        )
        assessed = assess_benchmark_series_timings(request, inputs, runs)
        if owner.journal.read(session, request, job_id=job_id) != history:
            raise ValueError("BENCHMARK_TIMING_HISTORY_CHANGED")
        return assessed
