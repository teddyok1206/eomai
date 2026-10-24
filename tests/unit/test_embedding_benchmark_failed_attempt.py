"""Synthetic root/Identity/SQLite only; post-ACK model work deliberately stays unknown."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_failed_attempt import (
    BenchmarkFailedAttemptObservation,
    benchmark_failed_attempt_bytes,
    parse_benchmark_failed_attempt_bytes,
)
from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    EMPTY_SHA256,
    BenchmarkPreackObservation,
)
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_benchmark_launch_recovery import BenchmarkLaunchRecoveryApplication
from eom_orchestrator.models import JobEventRecord
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for, receipt_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_benchmark_preack_recovery import recover, root_observation
from tests.unit.test_embedding_benchmark_preack_recovery import recovery as recovery
from tests.unit.test_embedding_benchmark_prelaunch_failure import SyntheticInspection


def failed_observation(request, invocation):
    body = root_observation(request, invocation).model_dump(mode="json")
    for key in (
        "original_service_raw_sha256",
        "root_ack_absent",
        "constructor_calls",
        "tokenizer_calls",
        "cuda_init_calls",
        "forward_calls",
    ):
        body.pop(key)
    body.update(
        schema_version="embedding-benchmark-failed-attempt/1.0",
        root_ack_sent=True,
        model_progress="NOT_RECORDED",
        reuse_failed_outputs=False,
        ack_result_raw_sha256="sha256:" + "a" * 64,
    )
    return BenchmarkFailedAttemptObservation.model_validate(seal(body, "observation_sha256"))


def select_failed(case):
    inspection = SyntheticInspection(failed_observation(case.request, case.calls[-1]))
    case.inspection = inspection
    case.app = BenchmarkLaunchRecoveryApplication(
        case.sessions, admission=case.admission, inspection=inspection
    )


def reserve_next_attempt(case):
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(
            case.calls[-1].model_dump(mode="json") | {"execution_id": uuid4().hex},
            "invocation_sha256",
        )
    )
    with case.sessions() as session, session.begin():
        case.journal.reserve(session, case.request, invocation)
    case.calls[-1] = invocation


def test_postack_recovery_retains_original_failed_identity_and_unknown_progress(recovery):
    case = recovery
    select_failed(case)
    original = case.calls[-1]
    result = recover(case)
    assert result.created and not recover(case).created
    assert case.inspection.captures == 1
    assert result.decision.observation.model_progress == "NOT_RECORDED"
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.job_state == "RUNNING" and len(history.launches) == 1
        assert history.launches[0].receipt is not None
        assert (
            not history.retired_preack_launches
            and history.failed_attempts[0].invocation == original
        )
        rows = tuple(
            session.scalars(select(JobEventRecord).where(JobEventRecord.job_id == case.job_id))
        )
        assert rows[-1].event == "BENCHMARK_FAILED_ATTEMPT_RECONCILED"
        assert rows[-1].data["observation"]["model_progress"] == "NOT_RECORDED"
        assert "constructor_calls" not in rows[-1].data["observation"]
        with pytest.raises(ValueError, match="EXECUTION_REUSED"):
            case.journal.reserve(session, case.request, original)
    reserve_next_attempt(case)
    select_failed(case)
    with pytest.raises(ValueError, match="NOT_RECOVERABLE"):
        recover(case)


def test_two_preack_failures_and_one_explicit_failed_postack_share_one_journal(recovery):
    case = recovery
    recover(case)
    reserve_next_attempt(case)
    body = root_observation(case.request, case.calls[-1]).model_dump(mode="json") | {
        "ready_raw_sha256": EMPTY_SHA256,
        "physical_fence_sha256": content_sha256(None),
    }
    case.inspection.observation = BenchmarkPreackObservation.model_validate(
        seal(body, "observation_sha256")
    )
    recover(case)
    reserve_next_attempt(case)
    select_failed(case)
    assert recover(case).created
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert len(history.retired_launches) == 3
        assert len(history.retired_preack_launches) == 2 and len(history.failed_attempts) == 1
        assert len(history.launches) == 1 and history.launches[0].receipt is not None


@pytest.mark.parametrize("check", (1, 2, 3, 4))
def test_postack_live_root_fence_changes_roll_back_append(recovery, check):
    case = recovery
    select_failed(case)
    case.inspection.fail_check = check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        recover(case)
    with case.sessions() as session, session.begin():
        assert not case.journal.read(session, case.request, job_id=case.job_id).retired_launches


@pytest.mark.parametrize("replay", (False, True))
def test_postack_reconciliation_and_replay_still_require_current_identity_source(recovery, replay):
    case = recovery
    select_failed(case)
    if replay:
        recover(case)
    case.admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        recover(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_progress", "ZERO"),
        ("root_ack_sent", False),
        ("cleanup", "UNKNOWN"),
        ("reuse_failed_outputs", True),
        ("stored_descriptors", 1),
        ("cgroup_empty", False),
        ("ready_raw_sha256", EMPTY_SHA256),
        ("ack_result_raw_sha256", EMPTY_SHA256),
    ],
)
def test_postack_cannot_be_laundered_into_zero_compute_or_partial_cleanup(recovery, field, value):
    body = failed_observation(recovery.request, recovery.calls[-1]).model_dump(mode="json") | {
        field: value
    }
    with pytest.raises((ValueError, SchemaError)):
        BenchmarkFailedAttemptObservation.model_validate(seal(body, "observation_sha256"))


def test_failed_attempt_canonical_codec(recovery):
    value = failed_observation(recovery.request, recovery.calls[-1])
    raw = benchmark_failed_attempt_bytes(value)
    assert parse_benchmark_failed_attempt_bytes(raw) == value
    with pytest.raises(ValueError):
        parse_benchmark_failed_attempt_bytes(raw + b"\n")


def test_completed_series_contains_six_real_receipts_not_retired_failure(recovery):
    case = recovery
    original_cpu = case.calls[0]
    select_failed(case)
    failed_execution = case.calls[-1].execution_id
    recover(case)
    storage_case = (
        case.sessions,
        SimpleNamespace(request=case.request, inputs=case.admission.inputs),
        case.admission.reader,
        case.journal,
        case.job_id,
    )
    for ordinal in range(2, 7):
        body = invocation_for(storage_case, ordinal).model_dump(mode="json") | {
            "execution_id": uuid4().hex,
            "schema_version": "embedding-device-benchmark-invocation/1.2",
            "execution_policy": case.request.execution_policy.model_dump(mode="json"),
        }
        invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
        with case.sessions() as session, session.begin():
            case.journal.reserve(session, case.request, invocation)
            case.journal.record(session, case.request, receipt_for(storage_case, invocation))
    with case.sessions() as session, session.begin():
        completed = case.journal.require_completed_launches(
            session, case.request, job_id=case.job_id
        )
        assert len(completed) == 6 and completed[0].invocation == original_cpu
        assert tuple(row.invocation.launch_ordinal for row in completed) == tuple(range(1, 7))
        assert failed_execution not in {row.invocation.execution_id for row in completed}
        assert (
            len(case.journal.read(session, case.request, job_id=case.job_id).failed_attempts) == 1
        )
