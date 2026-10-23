"""Synthetic budget600 terminal closure; no real PID1 or PostgreSQL authority."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_budget600_failure import (
    BenchmarkBudget600FailureDecision,
    BenchmarkBudget600PoststartObservation,
    BenchmarkBudget600PredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, new_revision_id, sha256_bytes
from eom_orchestrator.embedding_benchmark_launch_history import (
    BenchmarkLaunchJournal,
    require_benchmark_poststart_observation,
)
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
)
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission
from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_benchmark_poststart_failure import (
    close,
    submit,
    successor,
)
from tests.unit.test_embedding_benchmark_poststart_failure import (
    closure as closure,
)
from tests.unit.test_embedding_benchmark_prelaunch_failure import SyntheticInspection
from tests.unit.test_embedding_device_benchmark_owner import SyntheticOwnerAdmission


def test_budget600_timeout_closes_only_exact_reserved_successor_once(closure) -> None:
    original = closure
    predecessor = close(original).predecessor
    request, source = successor(original)
    job_id, created = submit(original, request, source, predecessor)
    assert created
    sessions, reader = original.sessions, original.storage[2]
    journal = BenchmarkLaunchJournal(source, reader)
    with sessions() as session, session.begin():
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    second_storage = (sessions, source, reader, journal, job_id)
    base_invocation = invocation_for(second_storage, 1)
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(
            base_invocation.model_dump(mode="json")
            | {
                "schema_version": "embedding-device-benchmark-invocation/1.1",
                "execution_policy": request.execution_policy.model_dump(mode="json"),
            },
            "invocation_sha256",
        )
    )
    with sessions() as session, session.begin():
        journal.reserve(session, request, invocation)

    legacy_observation = observation(request, invocation)
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        require_benchmark_poststart_observation(request, invocation, legacy_observation)
    legacy = legacy_observation.model_dump(mode="json")
    body = legacy | {
        "schema_version": "embedding-benchmark-poststart-failure/1.1",
        "failure_kind": "BUDGET600_TIMEOUT",
        "uncertain_raw_sha256": "sha256:" + "1" * 64,
    }
    terminal = dict(body["terminal"])
    prefix = "eom-embedding-benchmark-cpu-budget600@" + invocation.execution_id
    terminal.update(
        native_service=prefix + ".service",
        native_socket=prefix + ".socket",
        retired_service_template_sha256="sha256:" + "2" * 64,
        retired_socket_template_sha256="sha256:" + "3" * 64,
        window_before_raw_sha256="sha256:" + "4" * 64,
        window_stopped_raw_sha256="sha256:" + "5" * 64,
        window_restored_raw_sha256="sha256:" + "6" * 64,
    )
    body["terminal"] = terminal
    body["observation_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "observation_sha256"}
    )
    inspected = BenchmarkBudget600PoststartObservation.model_validate(body)
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        require_benchmark_poststart_observation(original.request, original.invocation, inspected)
    inspection = SyntheticInspection(inspected)
    admission = SyntheticOwnerAdmission(request, source.inputs, reader)
    application = BenchmarkPoststartFailureApplication(
        sessions, admission=admission, inspection=inspection
    )
    case = SimpleNamespace(application=application, request=request, job_id=job_id)
    result = close(case)
    assert result.created and isinstance(result.decision, BenchmarkBudget600FailureDecision)
    assert result.predecessor == BenchmarkBudget600PredecessorReference.from_decision(
        result.decision, event_sequence=result.event_sequence
    )
    with sessions() as session, session.begin():
        history = journal.read(session, request, job_id=job_id)
        assert history.job_state == "FAILED"
        assert history.launches[0].invocation == invocation
        assert history.launches[0].receipt is None
        assert history.poststart_failure is not None
        assert history.poststart_failure.decision == result.decision
        assert session.get(JobRecord, original.job_id).status == "FAILED"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 15
    replay = close(case)
    assert replay.decision == result.decision and not replay.created
    assert inspection.captures == 1

    # A proven 600-second failure can lead only to an immutable 1200-second
    # successor; its parent failure and partial output remain unchanged.
    successor_revision = "embeddingbenchmarkrev_" + uuid4().hex
    successor_inputs = BenchmarkStagedInputs.model_validate(
        source.inputs.model_dump(mode="json") | {"benchmark_revision_id": successor_revision}
    )
    policy = request.execution_policy.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-policy/1.2",
        "policy_revision_id": "embeddingbenchmarkpolicyrev_" + uuid4().hex,
        "timeout_seconds": 1200,
    }
    manifest = request.input_manifest.model_dump(mode="json") | {
        "artifact_revision_id": new_revision_id(),
        "sha256": sha256_bytes(embedding_device_benchmark_bytes(successor_inputs)),
    }
    successor_body = request.model_dump(mode="json", exclude={"request_sha256"}) | {
        "schema_version": "embedding-device-benchmark-request/1.2",
        "benchmark_revision_id": successor_revision,
        "input_manifest": manifest,
        "execution_policy": seal(policy, "policy_sha256"),
    }
    successor_request = BenchmarkOwnerRequest.model_validate(seal(successor_body, "request_sha256"))
    altered_body = successor_request.model_dump(mode="json", exclude={"request_sha256"}) | {
        "operator_audit_id": "operator_" + "f" * 32,
    }
    altered_request = BenchmarkOwnerRequest.model_validate(seal(altered_body, "request_sha256"))
    with pytest.raises(ValueError, match="SUCCESSOR_SELECTION_CONFLICT"):
        submit(
            original,
            altered_request,
            SyntheticBenchmarkAdmission(altered_request, successor_inputs),
            result.predecessor,
        )
    successor_admission = SyntheticBenchmarkAdmission(successor_request, successor_inputs)
    successor_job_id, successor_created = submit(
        original, successor_request, successor_admission, result.predecessor
    )
    assert successor_created and successor_job_id != job_id
    assert submit(original, successor_request, successor_admission, result.predecessor) == (
        successor_job_id,
        False,
    )
    with sessions() as session, session.begin():
        parent = session.get(JobRecord, job_id)
        child = session.get(JobRecord, successor_job_id)
        assert parent.status == "FAILED"
        assert child.status == "VALIDATED"
        history = BenchmarkLaunchJournal(successor_admission, reader).read(
            session, successor_request, job_id=successor_job_id
        )
        assert history.predecessor == result.predecessor
        assert (
            session.scalar(
                select(func.count()).where(
                    JobEventRecord.job_id == successor_job_id,
                    JobEventRecord.event == "BENCHMARK_POSTSTART_SUCCESSOR_REGISTERED",
                )
            )
            == 1
        )
