"""Opt-in host lock and current-work evidence in a guarded disposable DB only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.codex_compatibility_maintenance import CodexCompatibilityMaintenance
from eom_orchestrator.control_commands import (
    build_codex_control_command,
    claim_next_codex_control_command,
    enqueue_codex_control_command,
    terminalize_codex_control_command,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import (
    WORKER_HOST_CAPACITY_LOCK_ID,
    ControlPlaneError,
    acquire_worker_lease,
    begin_worker_lease_reconciliation,
    terminalize_worker_lease,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from tests.integration import test_control_plane_persistence as control_fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


def _no_host_mutations() -> None:
    """Only the disposable database boundary is under test; no systemd calls."""


@pytest.fixture
def control_seed(guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.setattr(control_fixture, "NOW", datetime.now(UTC) - timedelta(seconds=3))
    with Session(guarded_engine) as session, session.begin():
        plan_id, workflow_id, _ = control_fixture._complete_control_plane(session)
    return plan_id, workflow_id


def _finish_fixture_job(engine: Engine, job_id: str) -> None:
    with Session(engine) as session, session.begin():
        job = session.get(JobRecord, job_id)
        assert job is not None
        if JobState(job.status) not in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            transition_job(session, job_id, JobState.FAILED, "DISPOSABLE_FIXTURE_FINISHED")


def test_host_session_lock_survives_short_transactions_and_blocks_atomic_claim(
    guarded_engine: Engine,
) -> None:
    with (
        guarded_engine.connect() as contender,
        CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations) as fence,
    ):
        for _ in range(3):
            fence.assert_quiescent()
            # The fence has committed its reads, but the *session* host lock remains.
            assert (
                contender.scalar(
                    select(func.pg_try_advisory_xact_lock(WORKER_HOST_CAPACITY_LOCK_ID))
                )
                is False
            )
            no_long_transaction = contender.scalar(
                text(
                    "SELECT activity.xact_start IS NULL FROM pg_locks AS lock "
                    "JOIN pg_stat_activity AS activity ON activity.pid = lock.pid "
                    "WHERE lock.locktype = 'advisory' AND lock.granted AND lock.objsubid = 1 "
                    "AND lock.classid = :classid AND lock.objid = :objid"
                ),
                {
                    "classid": WORKER_HOST_CAPACITY_LOCK_ID >> 32,
                    "objid": WORKER_HOST_CAPACITY_LOCK_ID & 0xFFFFFFFF,
                },
            )
            assert no_long_transaction is True
            contender.commit()
    with guarded_engine.connect() as contender:
        assert (
            contender.scalar(select(func.pg_try_advisory_xact_lock(WORKER_HOST_CAPACITY_LOCK_ID)))
            is True
        )
        contender.rollback()


def test_busy_session_lock_never_enters_compatibility_epoch(guarded_engine: Engine) -> None:
    with guarded_engine.connect() as owner:
        assert owner.scalar(select(func.pg_try_advisory_lock(WORKER_HOST_CAPACITY_LOCK_ID))) is True
        owner.commit()
        try:
            with (
                pytest.raises(ControlPlaneError) as error,
                CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations),
            ):
                pytest.fail("busy host cannot enter")
            assert error.value.code == "CODEX_COMPATIBILITY_FENCE_BUSY"
        finally:
            assert (
                owner.scalar(select(func.pg_advisory_unlock(WORKER_HOST_CAPACITY_LOCK_ID))) is True
            )
            owner.commit()


@pytest.mark.parametrize(
    "state", ["VALIDATED", "QUEUED", "CLAIMED", "RUNNING", "VALIDATING_RESULT", "COMMITTING"]
)
def test_executable_job_prevents_false_quiescence(
    guarded_engine: Engine, control_seed: tuple[str, str], state: str
) -> None:
    with Session(guarded_engine) as session, session.begin():
        job = control_fixture._job(session, workflow_id=control_seed[1])
        # Isolated seed of each persisted lifecycle shape, not a runtime repair.
        job.status = state
        job_id = job.job_id
    try:
        with (
            pytest.raises(ControlPlaneError) as error,
            CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations),
        ):
            pytest.fail("executable job cannot be hidden")
        assert error.value.code == "CODEX_COMPATIBILITY_JOB_BUSY"
    finally:
        _finish_fixture_job(guarded_engine, job_id)


@pytest.mark.parametrize("state", ["CREATED", "SUCCEEDED", "FAILED", "CANCELLED"])
def test_nonexecuting_and_terminal_history_does_not_block_maintenance(
    guarded_engine: Engine, control_seed: tuple[str, str], state: str
) -> None:
    with Session(guarded_engine) as session, session.begin():
        job = control_fixture._job(session, workflow_id=control_seed[1])
        job.status = state
        job_id = job.job_id
    try:
        with CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations) as fence:
            fence.assert_quiescent()
        with Session(guarded_engine) as session:
            preserved = session.get(JobRecord, job_id)
            assert preserved is not None and preserved.status == state
    finally:
        _finish_fixture_job(guarded_engine, job_id)


@pytest.mark.parametrize("reconciling", [False, True])
def test_held_or_uncertain_worker_lease_always_blocks_diagnostics(
    guarded_engine: Engine, control_seed: tuple[str, str], reconciling: bool
) -> None:
    acquired_at = control_fixture.NOW + timedelta(seconds=30)
    with Session(guarded_engine) as session, session.begin():
        job = control_fixture._job(session, workflow_id=control_seed[1])
        job_id = job.job_id
        lease = acquire_worker_lease(
            session,
            plan_id=control_seed[0],
            step_key="authoring",
            job_id=job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=acquired_at,
            ttl=timedelta(minutes=5),
        )
        lease_id = lease.lease_id
        if reconciling:
            begin_worker_lease_reconciliation(
                session,
                lease_id=lease_id,
                observed_at=acquired_at + timedelta(seconds=1),
                reason_code="PROCESS_TERMINAL_UNCONFIRMED",
            )
    try:
        with (
            pytest.raises(ControlPlaneError) as error,
            CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations),
        ):
            pytest.fail("held or uncertain process cannot be hidden")
        assert error.value.code == "CODEX_COMPATIBILITY_LEASE_BUSY"
    finally:
        with Session(guarded_engine) as session, session.begin():
            terminalize_worker_lease(
                session,
                lease_id=lease_id,
                terminal_state="RELEASED",
                reason_code="DISPOSABLE_FIXTURE_FINISHED",
                released_at=acquired_at + timedelta(minutes=1),
            )
        _finish_fixture_job(guarded_engine, job_id)


def test_processing_control_observation_is_not_false_quiescence(
    guarded_engine: Engine, control_seed: tuple[str, str]
) -> None:
    owner = "disposable-compatibility-fixture"
    observed_at = control_fixture.NOW + timedelta(seconds=30)
    with Session(guarded_engine) as session, session.begin():
        binding = session.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
        )
        assert binding is not None
        operator_id = "operator_" + uuid4().hex
        session.add(
            OperatorRecord(
                operator_id=operator_id,
                username="compatibility-" + uuid4().hex[:12],
                normalized_username="compatibility-" + uuid4().hex,
                display_name="Disposable compatibility operator",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-test",
            )
        )
        session.flush()
        command = enqueue_codex_control_command(
            session,
            document=build_codex_control_command(
                command_type="OBSERVE",
                binding_id=binding.binding_id,
                expected_resource_version=binding.resource_version,
                requested_by_operator_id=operator_id,
                requested_at=observed_at,
                reason_code=None,
            ),
            idempotency_key="disposable-compatibility-" + uuid4().hex,
        )
        claimed = claim_next_codex_control_command(
            session,
            lease_owner=owner,
            claimed_at=observed_at,
            lease_ttl=timedelta(minutes=3),
        )
        assert claimed is command
        command_id = command.command_id
    try:
        with (
            pytest.raises(ControlPlaneError) as error,
            CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations),
        ):
            pytest.fail("processing account observation cannot be hidden")
        assert error.value.code == "CODEX_COMPATIBILITY_CONTROL_BUSY"
    finally:
        with Session(guarded_engine) as session, session.begin():
            terminalize_codex_control_command(
                session,
                command_id=command_id,
                lease_owner=owner,
                outcome="FAILED",
                result_resource_version=None,
                binding_state=None,
                reason_code="DISPOSABLE_FIXTURE_FINISHED",
                processed_at=observed_at + timedelta(seconds=1),
            )


def test_newly_committed_job_is_visible_to_each_launch_recheck(
    guarded_engine: Engine, control_seed: tuple[str, str]
) -> None:
    job_id: str | None = None
    try:
        with CodexCompatibilityMaintenance(guarded_engine, host_reader=_no_host_mutations) as fence:
            with Session(guarded_engine) as session, session.begin():
                job_id = control_fixture._job(session, workflow_id=control_seed[1]).job_id
            with pytest.raises(ControlPlaneError) as error:
                fence.assert_quiescent()
            assert error.value.code == "CODEX_COMPATIBILITY_JOB_BUSY"
    finally:
        if job_id is not None:
            _finish_fixture_job(guarded_engine, job_id)
