"""Synthetic root/admission and disposable SQLite; not GPU or PostgreSQL acceptance."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    EMPTY_SHA256,
    BenchmarkPreackObservation,
    benchmark_preack_bytes,
    parse_benchmark_preack_bytes,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import submit_benchmark_job_in_session
from eom_orchestrator.embedding_benchmark_launch_history import BenchmarkLaunchJournal
from eom_orchestrator.embedding_benchmark_preack_recovery import BenchmarkPreackRecoveryApplication
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for, receipt_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_benchmark_prelaunch_failure import SyntheticInspection
from tests.unit.test_embedding_device_benchmark_budget import successor_request_v12
from tests.unit.test_embedding_device_benchmark_owner import SyntheticOwnerAdmission


def root_observation(request, invocation):
    body = dict(
        schema_version="embedding-benchmark-preack-recovery/1.0",
        kind="ROOT_OBSERVATION",
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        request_sha256=request.request_sha256,
        invocation_sha256=invocation.invocation_sha256,
        device="CUDA",
        launch_ordinal=invocation.launch_ordinal,
        invocation_raw_sha256=sha256_bytes(embedding_device_benchmark_bytes(invocation)),
        association_sha256="sha256:" + "1" * 64,
        prepared_sha256="sha256:" + "2" * 64,
        ready_raw_sha256="sha256:" + "3" * 64,
        retirement_intent_raw_sha256="sha256:" + "4" * 64,
        retirement_result_raw_sha256="sha256:" + "5" * 64,
        native_service="eom-embedding-benchmark-cuda-budget1200@"
        + invocation.execution_id
        + ".service",
        native_invocation_id="6" * 32,
        original_service_raw_sha256="sha256:" + "7" * 64,
        original_outcome="FAILED",
        cleanup="CONFIRMED",
        root_ack_absent=True,
        constructor_calls=0,
        tokenizer_calls=0,
        cuda_init_calls=0,
        forward_calls=0,
        stored_descriptors=0,
        cgroup_empty=True,
        gpu_client_count=0,
        outputs=[
            dict(member_name=name, byte_count=0, sha256=EMPTY_SHA256)
            for name in benchmark_local_output_members(invocation.launch_ordinal)
        ],
        physical_fence_sha256="sha256:" + "8" * 64,
        boot_id="125d12ca-7fab-4162-bc7d-e290af618006",
        observed_at="2026-10-24T07:10:00Z",
    )
    return BenchmarkPreackObservation.model_validate(seal(body, "observation_sha256"))


@pytest.fixture
def recovery(storage):
    sessions, _old_source, reader, _journal, _job_id = storage
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
    source = SyntheticBenchmarkAdmission(request, inputs)
    journal = BenchmarkLaunchJournal(source, reader)
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=source)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    selected = (sessions, source, reader, journal, job_id)
    calls = []
    for ordinal in (1, 2):
        invocation = BenchmarkWorkerInvocation.model_validate(
            seal(
                invocation_for(selected, ordinal).model_dump(mode="json")
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
                journal.record(session, request, receipt_for(selected, invocation))
        calls.append(invocation)
    inspection = SyntheticInspection(root_observation(request, calls[-1]))
    admission = SyntheticOwnerAdmission(request, inputs, reader)
    app = BenchmarkPreackRecoveryApplication(sessions, admission=admission, inspection=inspection)
    return SimpleNamespace(
        sessions=sessions,
        request=request,
        journal=journal,
        job_id=job_id,
        calls=calls,
        inspection=inspection,
        app=app,
        admission=admission,
    )


def recover(case):
    return case.app.recover(
        case.request, job_id=case.job_id, execution_id=case.calls[-1].execution_id
    )


def test_append_only_same_job_preserves_cpu_and_failed_identity(recovery):
    case = recovery
    result = recover(case)
    assert result.created and not recover(case).created
    assert case.inspection.captures == 1
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.job_state == "RUNNING" and len(history.launches) == 1
        assert history.launches[0].invocation == case.calls[0]
        assert history.launches[0].receipt is not None
        assert history.retired_preack_launches[0].invocation == case.calls[1]
        rows = tuple(
            session.scalars(select(JobEventRecord).where(JobEventRecord.job_id == case.job_id))
        )
        assert len(rows) == 9 and rows[-2].event == "BENCHMARK_LAUNCH_RESERVED"
        assert rows[-1].event == "BENCHMARK_CUDA_PREACK_RECOVERED"
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert session.get(JobRecord, case.job_id).error_code is None
        with pytest.raises(ValueError, match="EXECUTION_REUSED"):
            case.journal.reserve(session, case.request, case.calls[1])


def test_exactly_one_recovery_per_ordinal_and_phase(recovery):
    case = recovery
    recover(case)
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(
            case.calls[-1].model_dump(mode="json") | {"execution_id": uuid4().hex},
            "invocation_sha256",
        )
    )
    with case.sessions() as session, session.begin():
        case.journal.reserve(session, case.request, invocation)
    case.calls[-1] = invocation
    case.inspection.observation = root_observation(case.request, invocation)
    with pytest.raises(ValueError, match="NOT_RECOVERABLE"):
        recover(case)


def test_before_ready_is_a_distinct_single_bounded_recovery_phase(recovery):
    case = recovery
    recover(case)
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(
            case.calls[-1].model_dump(mode="json") | {"execution_id": uuid4().hex},
            "invocation_sha256",
        )
    )
    with case.sessions() as session, session.begin():
        case.journal.reserve(session, case.request, invocation)
    case.calls[-1] = invocation
    body = root_observation(case.request, invocation).model_dump(mode="json") | {
        "ready_raw_sha256": EMPTY_SHA256,
        "physical_fence_sha256": content_sha256(None),
    }
    case.inspection.observation = BenchmarkPreackObservation.model_validate(
        seal(body, "observation_sha256")
    )
    assert recover(case).created
    assert not recover(case).created
    third = BenchmarkWorkerInvocation.model_validate(
        seal(
            invocation.model_dump(mode="json") | {"execution_id": uuid4().hex}, "invocation_sha256"
        )
    )
    with case.sessions() as session, session.begin():
        history, _ = case.journal.reserve(session, case.request, third)
        assert len(history.retired_preack_launches) == 2
    case.calls[-1] = third
    body = root_observation(case.request, third).model_dump(mode="json") | {
        "ready_raw_sha256": EMPTY_SHA256,
        "physical_fence_sha256": content_sha256(None),
    }
    case.inspection.observation = BenchmarkPreackObservation.model_validate(
        seal(body, "observation_sha256")
    )
    with pytest.raises(ValueError, match="NOT_RECOVERABLE"):
        recover(case)


@pytest.mark.parametrize("check", (1, 2, 3, 4))
def test_changed_live_root_proof_rolls_back_recovery(recovery, check):
    case = recovery
    case.inspection.fail_check = check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        recover(case)
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert not history.retired_preack_launches and len(history.launches) == 2


@pytest.mark.parametrize("replay", (False, True))
def test_actual_operator_source_fence_required_even_on_replay(recovery, replay):
    case = recovery
    if replay:
        recover(case)
    case.admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        recover(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("forward_calls", 1),
        ("root_ack_absent", False),
        ("stored_descriptors", 1),
        ("cleanup", "UNKNOWN"),
        ("launch_ordinal", 1),
        ("cuda_init_calls", True),
    ],
)
def test_nonzero_compute_or_ambiguous_cleanup_is_never_retry_evidence(recovery, field, value):
    body = recovery.inspection.observation.model_dump(mode="json") | {field: value}
    with pytest.raises((ValueError, SchemaError)):
        BenchmarkPreackObservation.model_validate(seal(body, "observation_sha256"))


def test_observation_canonical_codec_and_tampering(recovery):
    value = recovery.inspection.observation
    raw = benchmark_preack_bytes(value)
    assert parse_benchmark_preack_bytes(raw) == value
    with pytest.raises(ValueError):
        parse_benchmark_preack_bytes(raw + b"\n")
    with pytest.raises(ValueError):
        BenchmarkPreackObservation.model_validate(
            value.model_dump(mode="json") | {"execution_id": "f" * 32}
        )


@pytest.mark.parametrize("field", ("actor_id", "from_state", "request_sha256", "decision_sha256"))
def test_history_cannot_launder_foreign_or_tampered_recovery(recovery, field):
    case = recovery
    recover(case)
    with case.sessions() as session, session.begin():
        row = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == case.job_id,
                JobEventRecord.event == "BENCHMARK_CUDA_PREACK_RECOVERED",
            )
        )
        body = dict(row.data)
        if field == "actor_id":
            body[field] = "operator_" + "f" * 32
            row.data = seal(body, "decision_sha256")
        elif field == "from_state":
            row.from_state = "QUEUED"
        else:
            body[field] = "sha256:" + "f" * 64
            row.data = body
    with (
        case.sessions() as session,
        session.begin(),
        pytest.raises((ValueError, SchemaError), match="PREACK_HISTORY_INVALID"),
    ):
        case.journal.read(session, case.request, job_id=case.job_id)
