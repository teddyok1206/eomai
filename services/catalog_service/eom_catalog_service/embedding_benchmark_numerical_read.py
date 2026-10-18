"""Current-source numerical assessment of the original completed series; read only."""

from __future__ import annotations

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.state_machine import JobState

from eom_catalog_service.embedding_benchmark_numerical_assessment import (
    BenchmarkSeriesNumericalAssessment,
    assess_benchmark_series_numerics,
)
from eom_catalog_service.embedding_benchmark_owner_admission import CatalogBenchmarkOwnerAdmission


def read_completed_benchmark_series_numerics(
    owner: BenchmarkExecutionOwner, request: BenchmarkOwnerRequest, *, job_id: str
) -> BenchmarkSeriesNumericalAssessment:
    """Same current source root, original six receipts and CPU1 seal; never dispatch or commit."""
    if (
        type(owner) is not BenchmarkExecutionOwner
        or type(owner.admission) is not CatalogBenchmarkOwnerAdmission
    ):
        raise ValueError("BENCHMARK_NUMERICAL_READER_OWNER_INVALID")
    admission = owner.admission
    with (
        owner.sessions() as session,
        session.begin(),
        admission.admit_execution_in_session(session, request) as inputs,
    ):
        history = owner.journal.read(session, request, job_id=job_id)
        if history.job_state != JobState.VALIDATING_RESULT:
            raise ValueError("BENCHMARK_NUMERICAL_SERIES_NOT_READY")
        completed = owner.journal.require_completed_launches(session, request, job_id=job_id)
        first = completed[0]
        if (
            first.invocation.launch_ordinal != 1
            or first.invocation.device != "CPU"
            or (
                first.receipt.evidence.artifact_id,
                first.receipt.evidence.artifact_revision_id,
            )
            != (
                first.receipt.worker_result.artifact_id,
                first.receipt.worker_result.artifact_revision_id,
            )
        ):
            raise ValueError("BENCHMARK_NUMERICAL_CPU_REFERENCE_INVALID")
        reference = admission.read_cpu_numerical_reference_in_session(
            session, request, first.receipt.evidence
        )
        launches = tuple(
            admission.read_launch_numerics_in_session(session, request, launch)
            for launch in completed
        )
        assessed = assess_benchmark_series_numerics(
            request,
            inputs,
            launches,
            reference_pointer=reference.pointer,
            reference_raw=reference.raw,
            reference_scores=reference.scores,
        )
        if owner.journal.read(session, request, job_id=job_id) != history:
            raise ValueError("BENCHMARK_NUMERICAL_HISTORY_CHANGED")
        return assessed
