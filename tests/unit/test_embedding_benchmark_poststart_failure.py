"""Synthetic inspection and disposable SQLite, not real root proof or PG locking."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_budget1200_failure import (
    BenchmarkBudget1200PredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_budget1200_retry_failure import (
    BenchmarkBudget1200RetryFailureDecision,
    BenchmarkBudget1200RetryPoststartObservation,
    BenchmarkBudget1200RetryPredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    POSTSTART_FAILURE_CODE,
    POSTSTART_FAILURE_EVENT,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import new_revision_id, sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import submit_benchmark_job_in_session
from eom_orchestrator.embedding_benchmark_launch_history import (
    BenchmarkLaunchJournal,
    require_benchmark_poststart_observation,
)
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
    submit_benchmark_poststart_successor_in_session,
)
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for, receipt_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_benchmark_prelaunch_failure import SyntheticInspection
from tests.unit.test_embedding_device_benchmark_budget import successor_request_v12
from tests.unit.test_embedding_device_benchmark_owner import SyntheticOwnerAdmission


@pytest.fixture
def closure(storage):
    sessions, source, reader, journal, job_id = storage
    invocation = invocation_for(storage, 1)
    with sessions() as session, session.begin():
        journal.reserve(session, source.request, invocation)
    inspection = SyntheticInspection(observation(source.request, invocation))
    admission = SyntheticOwnerAdmission(source.request, source.inputs, reader)
    application = BenchmarkPoststartFailureApplication(
        sessions, admission=admission, inspection=inspection
    )
    return SimpleNamespace(
        sessions=sessions,
        journal=journal,
        job_id=job_id,
        invocation=invocation,
        inspection=inspection,
        admission=admission,
        application=application,
        request=source.request,
        storage=storage,
    )


def close(case):
    return case.application.close(case.request, job_id=case.job_id)


def test_failure_closure_preserves_partial_reservation_and_stored_replay(closure):
    case = closure
    result = close(case)
    assert result.created and result.event_sequence == 7
    assert result.predecessor == BenchmarkPoststartPredecessorReference.from_decision(
        result.decision, event_sequence=7
    )
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.job_state == "FAILED" and history.launches[0].receipt is None
        assert history.launches[0].invocation == case.invocation
        assert history.prelaunch_failure is None
        assert history.poststart_failure.decision == result.decision
        job = session.get(JobRecord, case.job_id)
        assert job.error_code == POSTSTART_FAILURE_CODE and job.completed_at is not None
        rows = tuple(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert len(rows) == 7 and rows[5].event == "BENCHMARK_LAUNCH_RESERVED"
        assert rows[6].event == POSTSTART_FAILURE_EVENT
        assert rows[6].data == result.decision.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert all(
            token not in json.dumps(rows[6].data)
            for token in ('"text"', '"vectors"', '"input_ids"')
        )
    checks = case.inspection.checks
    case.inspection.fail_check = checks + 1
    replay = close(case)
    assert not replay.created and replay.decision == result.decision
    assert replay.event_sequence == result.event_sequence
    assert case.inspection.captures == 1 and case.inspection.checks == checks


@pytest.mark.parametrize("fail_check", (1, 2, 3, 4))
def test_initial_and_late_proof_changes_roll_back_state_and_event(closure, fail_check):
    case = closure
    case.inspection.fail_check = fail_check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 6


@pytest.mark.parametrize("replay", (False, True))
def test_current_and_late_source_or_identity_authority_protects_closure(closure, replay):
    case = closure
    if replay:
        close(case)
    case.admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == ("FAILED" if replay else "RUNNING")
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == (
            7 if replay else 6
        )


@pytest.mark.parametrize(
    "field", ("execution_id", "invocation_raw_sha256", "invocation_sha256", "job_id")
)
def test_foreign_rehashed_observation_is_not_original_failure_proof(closure, field):
    case = closure
    body = case.inspection.observation.model_dump(mode="json")
    body[field] = {
        "execution_id": "f" * 32,
        "job_id": "job_" + "f" * 32,
        "invocation_raw_sha256": "sha256:" + "f" * 64,
        "invocation_sha256": "sha256:" + "f" * 64,
    }[field]
    if field == "execution_id":
        prefix = "eom-embedding-benchmark-cpu@" + body[field]
        body["terminal"].update(
            native_service=prefix + ".service", native_socket=prefix + ".socket"
        )
    case.inspection.observation = BenchmarkPoststartObservation.model_validate(
        seal(body, "observation_sha256")
    )
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        close(case)


@pytest.mark.parametrize("state", (JobState.FAILED, JobState.CANCELLED))
def test_different_terminal_history_is_never_reinterpreted(closure, state):
    case = closure
    with case.sessions() as session, session.begin():
        transition_job(session, case.job_id, state, "SYNTHETIC_FOREIGN_FAILURE")
    with pytest.raises(ValueError, match="TERMINAL_OR_FOREIGN"):
        close(case)
    assert case.inspection.captures == 0


def test_any_native_receipt_blocks_partial_failure_closure(closure):
    case = closure
    with case.sessions() as session, session.begin():
        case.journal.record(session, case.request, receipt_for(case.storage, case.invocation))
    with pytest.raises(ValueError, match="ORIGINAL_UNRESOLVED_REQUIRED"):
        close(case)


@pytest.mark.parametrize("fault", ("actor", "linkage", "error", "transition", "date"))
def test_tampered_terminal_decision_is_not_laundered_by_history(closure, fault):
    case = closure
    close(case)
    with case.sessions() as session, session.begin():
        row = session.scalar(select(JobEventRecord).where(JobEventRecord.sequence == 7))
        if fault in {"actor", "linkage", "date"}:
            body = dict(row.data)
            if fault == "actor":
                body["actor_id"] = "operator_" + "f" * 32
            elif fault == "linkage":
                body["invocation_sha256"] = "sha256:" + "f" * 64
            else:
                body["decided_at"] = "2026-10-21T00:00:00Z"
            row.data = seal(body, "decision_sha256")
        elif fault == "error":
            session.get(JobRecord, case.job_id).error_code = "FOREIGN_FAILURE"
        else:
            row.from_state = "QUEUED"
    with pytest.raises(ValueError, match="POSTSTART_HISTORY_INVALID"):
        close(case)


def test_untrusted_extras_and_direct_observation_are_not_authority(closure):
    case = closure
    malformed = case.request.model_copy(update={"private_note": "PRIVATE_NOT_FOR_ERRORS"})
    with pytest.raises(ValueError, match="REQUEST_INVALID") as error:
        case.application.close(malformed, job_id=case.job_id)
    assert "PRIVATE_NOT_FOR_ERRORS" not in str(error.value)
    with pytest.raises(TypeError):
        case.application.close(case.request, job_id=case.job_id, observation=observation())


def successor(case, **changes):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.storage[1].inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
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
    body.update(changes)
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    return request, SyntheticBenchmarkAdmission(request, inputs)


def submit(case, request, admission, reference):
    with case.sessions() as session, session.begin():
        job, created = submit_benchmark_poststart_successor_in_session(
            session, request, reference, source_admission=admission
        )
        return job.job_id, created


def test_only_explicit_budget_successor_is_registered_once_with_failed_parent_preserved(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case)
    job_id, created = submit(case, request, admission, closed.predecessor)
    assert created and job_id != case.job_id
    assert submit(case, request, admission, closed.predecessor) == (job_id, False)
    with case.sessions() as session:
        parent = session.get(JobRecord, case.job_id)
        child = session.get(JobRecord, job_id)
        assert parent.status == "FAILED" and child.status == "VALIDATED"
        assert parent.request == case.request.model_dump(mode="json")
        assert child.request == request.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        child_events = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert child_events[2].event == "BENCHMARK_POSTSTART_SUCCESSOR_REGISTERED"
        assert child_events[2].data == closed.predecessor.model_dump(mode="json")


def test_changed_actor_cannot_be_laundered_as_budget_only_successor(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case, operator_audit_id="operator_" + "f" * 32)
    with pytest.raises(ValueError, match="SUCCESSOR_SELECTION_CONFLICT"):
        submit(case, request, admission, closed.predecessor)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_late_successor_source_revocation_rolls_back_new_identity_and_event(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case)
    admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        submit(case, request, admission, closed.predecessor)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.fixture
def retry_closure(storage):
    sessions, _original_source, reader, _original_journal, _original_job = storage
    initial, inputs = benchmark_case()
    template = successor_request_v12()
    request = BenchmarkOwnerRequest.model_validate(
        seal(
            initial.model_dump(mode="json")
            | {
                "schema_version": template.schema_version,
                "execution_policy": template.execution_policy.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    source = SyntheticBenchmarkAdmission(request, inputs)
    journal = BenchmarkLaunchJournal(source, reader)
    with sessions() as session, session.begin():
        job, _created = submit_benchmark_job_in_session(session, request, source_admission=source)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    selected_storage = (sessions, source, reader, journal, job_id)
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(
            invocation_for(selected_storage, 1).model_dump(mode="json")
            | {
                "schema_version": "embedding-device-benchmark-invocation/1.2",
                "execution_policy": request.execution_policy.model_dump(mode="json"),
            },
            "invocation_sha256",
        )
    )
    with sessions() as session, session.begin():
        journal.reserve(session, request, invocation)
    body = observation(request, invocation).model_dump(mode="json")
    body["schema_version"] = "embedding-benchmark-poststart-failure/1.3"
    body["controller"]["unit"] = "eom-embedding-benchmark-retry-bbbbbbbb.service"
    prefix = "eom-embedding-benchmark-cpu-budget1200@" + invocation.execution_id
    body["terminal"].update(native_service=prefix + ".service", native_socket=prefix + ".socket")
    inspected = BenchmarkBudget1200RetryPoststartObservation.model_validate(
        seal(body, "observation_sha256")
    )
    inspection = SyntheticInspection(inspected)
    admission = SyntheticOwnerAdmission(request, inputs, reader)
    return SimpleNamespace(
        sessions=sessions,
        request=request,
        inputs=inputs,
        invocation=invocation,
        journal=journal,
        inspection=inspection,
        admission=admission,
        application=BenchmarkPoststartFailureApplication(
            sessions, admission=admission, inspection=inspection
        ),
        job_id=job_id,
    )


def retry_successor(case, *, version="1.2", **changes):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
    )
    timeout = {"1.0": 180, "1.1": 600, "1.2": 1200}[version]
    policy = case.request.execution_policy.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-policy/" + version,
        "policy_revision_id": "embeddingbenchmarkpolicyrev_" + uuid4().hex,
        "timeout_seconds": timeout,
    }
    body = case.request.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-request/" + version,
        "benchmark_revision_id": revision,
        "execution_policy": seal(policy, "policy_sha256"),
        "input_manifest": case.request.input_manifest.model_dump(mode="json")
        | {
            "artifact_revision_id": new_revision_id(),
            "sha256": sha256_bytes(embedding_device_benchmark_bytes(inputs)),
        },
    }
    body.update(changes)
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    return request, SyntheticBenchmarkAdmission(request, inputs)


def test_retry_controller_closure_preserves_native_v12_and_exact_append_only_replay(retry_closure):
    case = retry_closure
    result = close(case)
    assert result.created and isinstance(result.decision, BenchmarkBudget1200RetryFailureDecision)
    assert result.event_sequence == 7
    assert result.predecessor == BenchmarkBudget1200RetryPredecessorReference.from_decision(
        result.decision, event_sequence=7
    )
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert (
            history.job_state == "FAILED" and history.poststart_failure.decision == result.decision
        )
        assert history.launches[0].invocation == case.invocation
        assert history.launches[0].receipt is None and history.prelaunch_failure is None
        rows = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == case.job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert len(rows) == 7 and rows[-1].event == POSTSTART_FAILURE_EVENT
        assert (rows[-1].from_state, rows[-1].to_state) == ("RUNNING", "FAILED")
        assert rows[-1].data == result.decision.model_dump(mode="json")
        assert case.request.schema_version == "embedding-device-benchmark-request/1.2"
        assert case.invocation.schema_version == "embedding-device-benchmark-invocation/1.2"
        assert case.invocation.execution_policy.timeout_seconds == 1200
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
    checks = case.inspection.checks
    replay = close(case)
    assert not replay.created and replay.decision == result.decision
    assert replay.event_sequence == 7 and case.inspection.captures == 1
    assert case.inspection.checks == checks


@pytest.mark.parametrize("fail_check", (1, 2, 3, 4))
def test_retry_controller_late_proof_changes_roll_back_original_failure(retry_closure, fail_check):
    case = retry_closure
    case.inspection.fail_check = fail_check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert session.scalar(select(func.count()).where(JobEventRecord.job_id == case.job_id)) == 6


@pytest.mark.parametrize("replay", (False, True))
def test_retry_controller_current_source_and_identity_authority_still_fence_closure(
    retry_closure, replay
):
    case = retry_closure
    if replay:
        close(case)
    case.admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == ("FAILED" if replay else "RUNNING")
        assert session.scalar(select(func.count()).where(JobEventRecord.job_id == case.job_id)) == (
            7 if replay else 6
        )


@pytest.mark.parametrize("field", ("request_sha256", "invocation_sha256", "invocation_raw_sha256"))
def test_retry_controller_rehashed_foreign_request_or_invocation_never_closes_original(
    retry_closure, field
):
    case = retry_closure
    body = case.inspection.observation.model_dump(mode="json")
    body[field] = "sha256:" + "f" * 64
    inspected = BenchmarkBudget1200RetryPoststartObservation.model_validate(
        seal(body, "observation_sha256")
    )
    if field == "request_sha256":
        case.inspection.on_capture = lambda: setattr(case.inspection, "observation", inspected)
    else:
        case.inspection.observation = inspected
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        close(case)


def test_retry_controller_successor_is_same_native_budget_and_idempotent_pinned_history(
    retry_closure,
):
    case = retry_closure
    result = close(case)
    request, admission = retry_successor(case)
    job_id, created = submit(case, request, admission, result.predecessor)
    assert created and job_id != case.job_id
    assert submit(case, request, admission, result.predecessor) == (job_id, False)
    with case.sessions() as session, session.begin():
        history = BenchmarkLaunchJournal(admission, case.admission.reader).read(
            session, request, job_id=job_id
        )
        assert history.predecessor == result.predecessor and not history.launches
        assert history.job_state == "VALIDATED"
        assert session.get(JobRecord, case.job_id).status == "FAILED"
        assert session.get(JobRecord, case.job_id).request == case.request.model_dump(mode="json")
        assert (
            session.scalar(
                select(func.count()).where(
                    JobEventRecord.job_id == job_id,
                    JobEventRecord.event == "BENCHMARK_POSTSTART_SUCCESSOR_REGISTERED",
                )
            )
            == 1
        )


@pytest.mark.parametrize("version", ("1.0", "1.1"))
def test_retry_controller_predecessor_cannot_change_released_native_budget(retry_closure, version):
    case = retry_closure
    result = close(case)
    request, admission = retry_successor(case, version=version)
    with pytest.raises(ValueError, match="SUCCESSOR_SELECTION_CONFLICT"):
        submit(case, request, admission, result.predecessor)


@pytest.mark.parametrize("fault", ("actor", "input_hash", "runtime", "graph", "policy_id"))
def test_retry_controller_successor_preserves_original_source_runtime_and_policy_pins(
    retry_closure, fault
):
    case = retry_closure
    result = close(case)
    request, admission = retry_successor(case)
    body = request.model_dump(mode="json")
    if fault == "actor":
        body["operator_audit_id"] = "operator_" + "f" * 32
    elif fault == "input_hash":
        body["input_set_sha256"] = "sha256:" + "f" * 64
    elif fault == "runtime":
        body["cpu"]["installed_proof"]["proof_revision_id"] = "embeddingruntimeproofrev_" + "f" * 32
    elif fault == "graph":
        body["graph_snapshot"]["manifest_sha256"] = "sha256:" + "f" * 64
        body["graph_snapshot"]["manifest_artifact"]["sha256"] = "sha256:" + "f" * 64
    else:
        policy = body["execution_policy"] | {"policy_id": "embeddingbenchmarkpolicy_" + "f" * 32}
        body["execution_policy"] = seal(policy, "policy_sha256")
    altered = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="SUCCESSOR_SELECTION_CONFLICT"):
        submit(
            case,
            altered,
            SyntheticBenchmarkAdmission(altered, admission.inputs),
            result.predecessor,
        )


def test_retry_controller_parent_cannot_be_retagged_as_v12_failure_history(retry_closure):
    case = retry_closure
    result = close(case)
    request, admission = retry_successor(case)
    legacy = BenchmarkBudget1200PredecessorReference.model_validate(
        result.predecessor.model_dump(mode="json")
        | {"schema_version": "embedding-benchmark-poststart-failure/1.2"}
    )
    with pytest.raises(ValueError, match="PREDECESSOR_CLOSURE_REQUIRED"):
        submit(case, request, admission, legacy)


def test_retry_failure_observation_never_attests_legacy_execution(closure, retry_closure):
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        require_benchmark_poststart_observation(
            closure.request, closure.invocation, retry_closure.inspection.observation
        )
