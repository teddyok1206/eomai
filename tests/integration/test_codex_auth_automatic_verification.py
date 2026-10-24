"""Account boundaries and enrollment contention in marker-guarded disposable PG only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_orchestrator.auth_enrollment import (
    build_codex_auth_enrollment_request,
    claim_due_codex_auth_enrollment,
    create_codex_auth_enrollment,
    transition_codex_auth_enrollment,
)
from eom_orchestrator.capability_snapshot_queries import (
    current_assignment_snapshot_clause,
    latest_binding_snapshot_clause,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, record_capability_snapshot
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration import test_control_plane_persistence as control_fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def current_fixture_clock(monkeypatch):
    # Committed fixtures must have current health when later concurrency suites reuse slots.
    monkeypatch.setattr(control_fixture, "NOW", datetime.now(UTC) - timedelta(seconds=3))


def _enrollment_document(engine):
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        control_fixture._complete_control_plane(session)
        binding = session.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
        )
        operator_id, session_id = "operator_" + uuid4().hex, "apisession_" + uuid4().hex
        session.add(
            OperatorRecord(
                operator_id=operator_id,
                username="disposable-" + uuid4().hex[:12],
                normalized_username="disposable-" + uuid4().hex,
                display_name="Disposable enrollment contention",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-auth-test",
            )
        )
        session.flush()
        session.add(
            ApiSessionRecord(
                api_session_id=session_id,
                operator_id=operator_id,
                token_family_id="tokenfamily_" + uuid4().hex,
                client_name="Disposable fixture, no credentials",
                authenticated_at=now,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now + timedelta(days=1),
                idle_expires_at=now + timedelta(hours=1),
                refresh_generation=1,
                lock_version=1,
            )
        )
        session.flush()
        document = build_codex_auth_enrollment_request(
            binding_id=binding.binding_id,
            expected_binding_resource_version=binding.resource_version,
            slot_key="slot01",
            requested_account_label="disposable-new-account",
            requested_by_operator_id=operator_id,
            requested_by_api_session_id=session_id,
            requested_at=now,
        )
    return document, now


def test_concurrent_enrollment_creation_and_claim_have_one_owner(guarded_engine):
    document, now = _enrollment_document(guarded_engine)
    gate = Barrier(2)

    def create():
        gate.wait(timeout=10)
        try:
            with Session(guarded_engine) as session, session.begin():
                row = create_codex_auth_enrollment(
                    session, document=document, idempotency_key="disposable-" + uuid4().hex
                )
                return row.enrollment_id
        except ControlPlaneError as error:
            assert error.code == "CODEX_AUTH_ENROLLMENT_ALREADY_ACTIVE"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = tuple(executor.map(lambda _: create(), range(2)))
    assert sum(value is not None for value in created) == 1
    enrollment_id = next(value for value in created if value is not None)

    def claim(runner):
        gate.wait(timeout=10)
        with Session(guarded_engine) as session, session.begin():
            row = claim_due_codex_auth_enrollment(session, lease_owner=runner, claimed_at=now)
            return None if row is None else (row.enrollment_id, runner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = tuple(executor.map(claim, ("disposable-runner-a", "disposable-runner-b")))
    assert sum(value is not None for value in claimed) == 1
    result = next(value for value in claimed if value is not None)
    assert result[0] == enrollment_id
    with Session(guarded_engine) as session, session.begin():
        assert (
            session.scalar(
                select(func.count())
                .select_from(CodexAuthEnrollmentRecord)
                .where(CodexAuthEnrollmentRecord.enrollment_id == enrollment_id)
            )
            == 1
        )
        transition_codex_auth_enrollment(
            session,
            enrollment_id=enrollment_id,
            lease_owner=result[1],
            target_state="FAILED",
            error_code="DISPOSABLE_FIXTURE_FINISHED",
            transitioned_at=now + timedelta(seconds=1),
        )


def test_extended_verification_claim_cannot_be_reclaimed_after_polling_ttl(guarded_engine):
    document, now = _enrollment_document(guarded_engine)
    with Session(guarded_engine) as session, session.begin():
        row = create_codex_auth_enrollment(
            session, document=document, idempotency_key="disposable-" + uuid4().hex
        )
        enrollment_id = row.enrollment_id
        assert (
            claim_due_codex_auth_enrollment(
                session, lease_owner="disposable-verifier", claimed_at=now
            )
            is row
        )
        # Same persisted lease extension as the processor, not a runtime row repair.
        row.lease_expires_at = row.expires_at
        deadline = row.expires_at
    with Session(guarded_engine) as session, session.begin():
        assert (
            claim_due_codex_auth_enrollment(
                session, lease_owner="disposable-contender", claimed_at=now + timedelta(seconds=31)
            )
            is None
        )
    with Session(guarded_engine) as session, session.begin():
        claimed = claim_due_codex_auth_enrollment(
            session, lease_owner="disposable-recovery", claimed_at=deadline + timedelta(seconds=1)
        )
        assert claimed.enrollment_id == enrollment_id
        transition_codex_auth_enrollment(
            session,
            enrollment_id=enrollment_id,
            lease_owner="disposable-recovery",
            target_state="FAILED",
            error_code="DISPOSABLE_FIXTURE_FINISHED",
            transitioned_at=deadline + timedelta(seconds=1),
        )


def test_current_account_and_latest_model_predicates_execute_on_postgresql(guarded_engine):
    with guarded_engine.connect() as connection, connection.begin() as outer:
        with Session(bind=connection) as session:
            # Reuses official assignment transitions and checks the immutable trigger too.
            control_fixture.test_codex_auth_enrollment_is_idempotent_credential_free_and_assignment_immutable(
                session
            )
            binding = session.scalar(
                select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
            )
            query = (
                select(CodexCapabilityEntryRecord.model)
                .join(
                    CodexCapabilitySnapshotRecord,
                    CodexCapabilitySnapshotRecord.capability_snapshot_id
                    == CodexCapabilityEntryRecord.capability_snapshot_id,
                )
                .join(
                    CodexAuthBindingRecord,
                    CodexAuthBindingRecord.binding_id == CodexCapabilitySnapshotRecord.binding_id,
                )
                .where(
                    CodexAuthBindingRecord.binding_id == binding.binding_id,
                    current_assignment_snapshot_clause(),
                    latest_binding_snapshot_clause(),
                )
            )
            assert session.scalars(query).all() == []
            for offset, model in ((41, "previously-verified"), (42, "currently-verified")):
                at = control_fixture.NOW + timedelta(minutes=offset)
                snapshot = control_fixture._self_hash(
                    {
                        "schema_version": "codex-capability-snapshot/1.0",
                        "capability_snapshot_id": "capsnap_" + uuid4().hex,
                        "binding_id": binding.binding_id,
                        "codex_cli_version": binding.codex_cli_version,
                        "source": "LOCAL_OBSERVATION",
                        "snapshot_sha256": "sha256:" + "0" * 64,
                        "capabilities": [
                            {"model": model, "reasoning_efforts": ["medium"], "state": "AVAILABLE"}
                        ],
                        "observed_at": at.isoformat().replace("+00:00", "Z"),
                        "valid_until": (at + timedelta(minutes=15))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                    "snapshot_sha256",
                )
                record_capability_snapshot(session, document=snapshot)
            assert session.scalars(query).all() == ["currently-verified"]
            assert (
                session.scalars(
                    query.where(CodexCapabilityEntryRecord.model == "previously-verified")
                ).all()
                == []
            )
        outer.rollback()
