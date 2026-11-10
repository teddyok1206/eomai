"""Fixed chat reservation and real contention in the guarded disposable chat database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identity_service.models import ApiSessionRecord
from eom_orchestrator.auth_enrollment import (
    build_codex_auth_enrollment_request,
    claim_due_codex_auth_enrollment,
    create_auth_assignment_revision,
    create_codex_auth_enrollment,
    held_lease_exists,
    transition_codex_auth_enrollment,
)
from eom_orchestrator.chat_slot_reservation import reserve_chat_slot
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    acquire_worker_lease,
    record_auth_health,
    record_capability_snapshot,
    terminalize_worker_lease,
)
from eom_orchestrator.general_chat_models import GeneralChatTurnRecord
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow.control_plane import WorkerRole
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from tests.integration import test_control_plane_persistence as control
from tests.integration.general_chat_fixtures import IDENTITY, RUNTIME

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def reserved(chat, monkeypatch):
    # No login, model call or filesystem credentials. Use ordinary enrollment transitions
    # to create the exact synthetic assignment; all mutations are disposable fixtures.
    monkeypatch.setattr(control, "NOW", chat.now - timedelta(minutes=1))
    now = chat.now - timedelta(seconds=30)
    with chat.repository.sessions.begin() as session:
        plan, workflow, _ = control._complete_control_plane(
            session, roles=(WorkerRole.SUPPORT,), slot_id_by_role={WorkerRole.SUPPORT: "06"}
        )
        job = control._job(session, workflow_id=workflow, role="support")
        job_id = job.job_id
        binding = session.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "06")
        )
        binding_id = binding.binding_id
        now = max(now, binding.observed_at + timedelta(seconds=1))
        chat.now = now + timedelta(seconds=30)
        api_session = ApiSessionRecord(
            api_session_id="apisession_" + uuid4().hex,
            operator_id=chat.actors[0],
            token_family_id="tokenfamily_" + uuid4().hex,
            client_name="Disposable chat slot fixture",
            authenticated_at=now,
            created_at=now,
            last_seen_at=now,
            absolute_expires_at=now + timedelta(hours=1),
            idle_expires_at=now + timedelta(hours=1),
            refresh_generation=1,
            lock_version=1,
        )
        session.add(api_session)
        session.flush()
        document = build_codex_auth_enrollment_request(
            binding_id=binding_id,
            expected_binding_resource_version=binding.resource_version,
            slot_key="slot06",
            requested_account_label="synthetic-chat-" + uuid4().hex[:12],
            requested_by_operator_id=chat.actors[0],
            requested_by_api_session_id=api_session.api_session_id,
            requested_at=now,
        )
        enrollment = create_codex_auth_enrollment(
            session, document=document, idempotency_key="chat-enrollment-" + uuid4().hex
        )
        for state in ("DRAINING", "READY_FOR_LOGIN", "WAITING_FOR_USER", "VERIFYING"):
            claim_due_codex_auth_enrollment(session, lease_owner="fixture", claimed_at=now)
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner="fixture",
                target_state=state,
                transitioned_at=now,
                next_action_at=now,
            )
        claim_due_codex_auth_enrollment(session, lease_owner="fixture", claimed_at=now)
        assignment = create_auth_assignment_revision(
            session,
            enrollment=enrollment,
            codex_cli_version=binding.codex_cli_version,
            assigned_at=now,
        )
        binding.current_assignment_revision_id = assignment.assignment_revision_id
        # Assignment, label and version must be published in the same health UPDATE.
        with session.no_autoflush:
            record_auth_health(
                session,
                document={
                    "schema_version": "codex-auth-health-view/1.0",
                    "binding_id": binding_id,
                    "slot_key": "slot06",
                    "account_label": assignment.account_label,
                    "state": "READY",
                    "reason_code": None,
                    "codex_cli_version": binding.codex_cli_version,
                    "observed_at": now.isoformat().replace("+00:00", "Z"),
                    "valid_until": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                },
            )
        transition_codex_auth_enrollment(
            session,
            enrollment_id=enrollment.enrollment_id,
            lease_owner="fixture",
            target_state="SUCCEEDED",
            transitioned_at=now,
            assignment_revision_id=assignment.assignment_revision_id,
        )
        record_capability_snapshot(
            session,
            document=control._self_hash(
                {
                    "schema_version": "codex-capability-snapshot/1.0",
                    "capability_snapshot_id": "capsnap_" + uuid4().hex,
                    "binding_id": binding_id,
                    "codex_cli_version": binding.codex_cli_version,
                    "source": "LOCAL_OBSERVATION",
                    "observed_at": now.isoformat().replace("+00:00", "Z"),
                    "valid_until": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "capabilities": [
                        {"model": model, "reasoning_efforts": ["high"], "state": "AVAILABLE"}
                        for model in sorted({IDENTITY.policy.model, "gpt-5.6-terra"})
                    ],
                    "snapshot_sha256": "sha256:" + "0" * 64,
                },
                "snapshot_sha256",
            ),
        )
        assert reserve_chat_slot(session)
        assert not reserve_chat_slot(session)
        document = build_codex_auth_enrollment_request(
            binding_id=binding_id,
            expected_binding_resource_version=binding.resource_version,
            slot_key="slot06",
            requested_account_label="synthetic-next-chat-slot",
            requested_by_operator_id=chat.actors[0],
            requested_by_api_session_id=api_session.api_session_id,
            requested_at=chat.now,
        )
    chat.execution.heartbeat(runtime_id=RUNTIME)
    try:
        yield chat, binding_id, document, plan, job_id
    finally:
        # Restore only this disposable fixture's mutable reservation. Never rewrite turns.
        with chat.repository.sessions.begin() as session:
            capacity = chat.repository.capacity(session, lock=True)
            capacity.worker_slot_id = None


def test_reserved_slot_excluded_from_original_released_policy_without_disabling(reserved):
    chat, binding_id, _, plan, job = reserved
    with chat.repository.sessions.begin() as session:
        assert session.get(CodexAuthBindingRecord, binding_id).state == "READY"
        with pytest.raises(ControlPlaneError, match="no eligible slot"):
            acquire_worker_lease(
                session,
                plan_id=plan,
                step_key="support",
                job_id=job,
                attempt=1,
                workload_class="CODEX",
                acquired_at=chat.now,
                ttl=timedelta(minutes=5),
            )


def test_claim_pins_assignment_blocks_login_and_preserves_expired_busy_state(reserved):
    chat, binding_id, document, _, _ = reserved
    chat.submit(chat.create())
    claim = chat.claim()
    with chat.repository.sessions.begin() as session:
        turn = session.get(GeneralChatTurnRecord, claim.turn_id)
        assert turn.worker_slot_id == "06" and turn.auth_binding_id == binding_id
        assert turn.auth_assignment_revision_id is not None
        capacity = chat.repository.capacity(session, lock=True)
        capacity.expires_at = chat.now - timedelta(seconds=1)
        assert held_lease_exists(session, binding_id=binding_id)
        with pytest.raises(ControlPlaneError, match="idle worker slot"):
            create_codex_auth_enrollment(
                session, document=document, idempotency_key="blocked-enrollment-" + uuid4().hex
            )
        # Only restore the synthetic test clock deadline; no execution recovery is fabricated.
        capacity.expires_at = chat.now + timedelta(minutes=30)
    with (
        chat.repository.sessions.begin() as session,
        pytest.raises(DBAPIError, match="immutable"),
        session.begin_nested(),
    ):
        session.get(GeneralChatTurnRecord, claim.turn_id).auth_assignment_revision_id = None
        session.flush()
    request = chat.execution.prepare(claim, identity=IDENTITY)
    chat.answer(claim, request)


def test_chat_claim_and_account_change_have_one_winner(reserved):
    chat, _, document, _, _ = reserved
    chat.submit(chat.create())
    barrier = Barrier(2)

    def chat_claim():
        barrier.wait(timeout=10)
        try:
            return ("chat", chat.execution.claim_next(runtime_id=RUNTIME))
        except ChatError as error:
            assert error.code == "GENERAL_CHAT_NOT_READY"
            return ("chat", None)

    def enroll():
        barrier.wait(timeout=10)
        try:
            with chat.repository.sessions.begin() as session:
                record = create_codex_auth_enrollment(
                    session, document=document, idempotency_key="race-enrollment-" + uuid4().hex
                )
                return ("enrollment", record.enrollment_id)
        except ControlPlaneError as error:
            assert error.code == "CODEX_AUTH_SLOT_BUSY"
            return ("enrollment", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(chat_claim), executor.submit(enroll)
        results = dict((first.result(timeout=15), second.result(timeout=15)))
    assert sum(value is not None for value in results.values()) == 1
    if results["chat"] is not None:
        claim = results["chat"]
        request = chat.execution.prepare(claim, identity=IDENTITY)
        chat.answer(claim, request)
    else:
        with chat.repository.sessions.begin() as session:
            claim_due_codex_auth_enrollment(session, lease_owner="fixture", claimed_at=chat.now)
            transition_codex_auth_enrollment(
                session,
                enrollment_id=results["enrollment"],
                lease_owner="fixture",
                target_state="FAILED",
                transitioned_at=chat.now,
                error_code="DISPOSABLE_FIXTURE_FINISHED",
            )


def test_ordinary_and_chat_share_host_ceiling_without_reassigning_reserved_slot(reserved):
    chat, _, _, _, _ = reserved
    roles = (WorkerRole.AUTHORING, WorkerRole.REVIEW, WorkerRole.ITEM_MANAGEMENT)
    with chat.repository.sessions.begin() as session:
        plan, workflow, _ = control._complete_control_plane(session, roles=roles)
        jobs = {
            role: control._job(session, workflow_id=workflow, role=role.value).job_id
            for role in roles
        }
        leases = [
            acquire_worker_lease(
                session,
                plan_id=plan,
                step_key=role.value,
                job_id=jobs[role],
                attempt=1,
                workload_class="CODEX",
                acquired_at=chat.now,
                ttl=timedelta(minutes=5),
            ).lease_id
            for role in roles
        ]
    try:
        chat.submit(chat.create())
        assert chat.execution.claim_next(runtime_id=RUNTIME) is None
        with chat.repository.sessions.begin() as session:
            terminalize_worker_lease(
                session,
                lease_id=leases[-1],
                terminal_state="RELEASED",
                reason_code="DISPOSABLE_FIXTURE_FINISHED",
                released_at=chat.now,
            )
            # A different job/step is necessary: released identity must not be reused.
            second_plan, second_workflow, _ = control._complete_control_plane(
                session, roles=(WorkerRole.ITEM_MANAGEMENT,)
            )
            second_job = control._job(
                session, workflow_id=second_workflow, role=WorkerRole.ITEM_MANAGEMENT.value
            ).job_id
        claim = chat.claim()
        with chat.repository.sessions.begin() as session:
            with pytest.raises(ControlPlaneError) as failure:
                acquire_worker_lease(
                    session,
                    plan_id=second_plan,
                    step_key="item_management",
                    job_id=second_job,
                    attempt=1,
                    workload_class="CODEX",
                    acquired_at=chat.now,
                    ttl=timedelta(minutes=5),
                )
            assert failure.value.code == "CONTROL_CAPACITY_EXHAUSTED"
        chat.answer(claim, chat.execution.prepare(claim, identity=IDENTITY))
    finally:
        with chat.repository.sessions.begin() as session:
            for lease_id in leases:
                terminalize_worker_lease(
                    session,
                    lease_id=lease_id,
                    terminal_state="RELEASED",
                    reason_code="DISPOSABLE_FIXTURE_FINISHED",
                    released_at=chat.now,
                )


def test_reservation_activation_and_ordinary_lease_have_one_winner(reserved):
    chat, _, _, plan, job = reserved
    # Put only the disposable activation fixture back before the first reservation.
    with chat.repository.sessions.begin() as session:
        chat.repository.capacity(session, lock=True).worker_slot_id = None
    barrier = Barrier(2)

    def activate():
        barrier.wait(timeout=10)
        try:
            with chat.repository.sessions.begin() as session:
                return ("reservation", reserve_chat_slot(session))
        except ChatError as error:
            assert error.code == "GENERAL_CHAT_SLOT_BUSY"
            return ("reservation", None)

    def ordinary():
        barrier.wait(timeout=10)
        try:
            with chat.repository.sessions.begin() as session:
                return (
                    "ordinary",
                    acquire_worker_lease(
                        session,
                        plan_id=plan,
                        step_key="support",
                        job_id=job,
                        attempt=1,
                        workload_class="CODEX",
                        acquired_at=chat.now,
                        ttl=timedelta(minutes=5),
                    ).lease_id,
                )
        except ControlPlaneError as error:
            assert error.code == "CONTROL_ELIGIBLE_SLOT_UNAVAILABLE"
            return ("ordinary", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(activate), executor.submit(ordinary)
        results = dict((first.result(timeout=15), second.result(timeout=15)))
    assert sum(value is not None for value in results.values()) == 1
    if results["ordinary"] is not None:
        with chat.repository.sessions.begin() as session:
            terminalize_worker_lease(
                session,
                lease_id=results["ordinary"],
                terminal_state="RELEASED",
                reason_code="DISPOSABLE_FIXTURE_FINISHED",
                released_at=chat.now,
            )
            assert reserve_chat_slot(session)


@pytest.mark.parametrize(
    "job_state,parent_state,step_state,allowed",
    [
        ("RUNNING", "FAILED", "FAILED", True),
        ("CLAIMED", "CANCELLED", "CANCELLED", True),
        ("RUNNING", "RUNNING", "FAILED", False),
        ("RUNNING", "FAILED", "RUNNING", False),
        ("VALIDATING_RESULT", "FAILED", "FAILED", False),
        ("COMMITTING", "FAILED", "FAILED", False),
    ],
)
def test_reservation_distinguishes_sealed_history_without_rewriting_job(
    reserved, job_state, parent_state, step_state, allowed
):
    chat, _, _, _, job_id = reserved
    with chat.repository.sessions.begin() as session:
        # Construct only a disposable historical shape, never repair a runtime row.
        chat.repository.capacity(session, lock=True).worker_slot_id = None
        job = session.get(JobRecord, job_id)
        job.status = job_state
        job.worker_slot_id = "06"
        session.get(WorkflowInstanceRecord, job.request["workflow_id"]).state = parent_state
        session.get(WorkflowStepRunRecord, job.request["step_run_id"]).state = step_state
        session.flush()
        before = (job.status, job.request, job.request_hash, job.updated_at)
    try:
        with chat.repository.sessions.begin() as session:
            if allowed:
                assert reserve_chat_slot(session)
            else:
                with pytest.raises(ChatError, match="GENERAL_CHAT_SLOT_BUSY"):
                    reserve_chat_slot(session)
            job = session.get(JobRecord, job_id)
            assert (job.status, job.request, job.request_hash, job.updated_at) == before
    finally:
        with chat.repository.sessions.begin() as session:
            transition_job(session, job_id, JobState.FAILED, "DISPOSABLE_FIXTURE_FINISHED")
