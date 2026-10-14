"""Synthetic application boundary checks; not real authentication/source/Artifact admission."""

from __future__ import annotations

from dataclasses import replace
from inspect import Parameter, signature
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_encoding_reservation_storage import (
    COMPLETED_EVENT,
    ENCODING_PROTOCOL_VERSION,
    ENCODING_TASK_TYPE,
    EmbeddingEncodingReservationError,
    EmbeddingEncodingReservationStorage,
    EncodingReservation,
    _is_key_race,
    owned_job,
)
from eom_orchestrator.embedding_encoding_reservations import (
    EmbeddingEncodingOwnerAdmission,
    EmbeddingEncodingReservations,
    EncodingReadTarget,
    ObservedEncodingReads,
    ResolvedEncodingCompletion,
    ResolvedEncodingLaunch,
    ResolvedEncodingScope,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingAttachedEvent,
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.embedding_encoding_reservation_fixtures import (
    references,
    requests,
    reservation_fixture,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import NativeAdmissionFixture


class SyntheticAdmission:
    def __init__(self, fixture: NativeAdmissionFixture) -> None:
        self.fixture = fixture
        self.calls: list[str] = []
        self.denied: str | None = None
        self.observed = ObservedEncodingReads(fixture.association.intent, frozenset())

    def check(self, name: str) -> None:
        self.calls.append(name)
        if self.denied == name:
            raise EmbeddingEncodingReservationError("SYNTHETIC_CURRENT_OWNER_DENIED")

    def resolve_reservation(
        self,
        session: Session,
        rows: tuple[EmbeddingEncodingJobRequest, ...],
        intent: LocalEmbeddingLaunchIntent,
    ) -> ResolvedEncodingScope:
        self.check("reserve_current")
        return ResolvedEncodingScope(self.fixture.request, self.fixture.plan, self.fixture.policy)

    def resolve_launch(
        self, session: Session, association: LocalEmbeddingLaunchAssociation
    ) -> ResolvedEncodingLaunch:
        self.check("launch_current")
        return ResolvedEncodingLaunch(
            ResolvedEncodingScope(self.fixture.request, self.fixture.plan, self.fixture.policy),
            self.fixture.native_input,
        )

    def resolve_completion(
        self,
        session: Session,
        association: LocalEmbeddingLaunchAssociation,
        events: tuple[EmbeddingEncodingCompletedEvent, ...],
    ) -> ResolvedEncodingCompletion:
        self.check("completion_current")
        return ResolvedEncodingCompletion(self.fixture.native_input, self.fixture.result)

    def reauthorize_read(
        self, session: Session, targets: tuple[EncodingReadTarget, ...]
    ) -> ObservedEncodingReads:
        self.check("read_current")
        return self.observed

    def fence_mutation(self, session: Session, intent: LocalEmbeddingLaunchIntent) -> None:
        self.check("mutation_current")
        if self.denied == "late_mutation" and self.calls.count("mutation_current") == 2:
            raise EmbeddingEncodingReservationError("SYNTHETIC_CURRENT_OWNER_DENIED")

    def fence_read_scope(
        self, session: Session, refs: tuple[EmbeddingEncodingJobReference, ...]
    ) -> None:
        self.check("read_scope_current")


def _records(
    fixture: NativeAdmissionFixture, status: JobState = JobState.CLAIMED
) -> tuple[EncodingReservation, ...]:
    records = []
    for index, original in enumerate(fixture.association.owned_jobs):
        reference, request = original.job_reference, original.request
        job = JobRecord(
            job_id=reference.job_id,
            protocol_version=ENCODING_PROTOCOL_VERSION,
            idempotency_key=request.idempotency_key,
            request_hash=content_sha256(
                {
                    "protocol_version": ENCODING_PROTOCOL_VERSION,
                    "task_type": ENCODING_TASK_TYPE,
                    "request": request.model_dump(mode="json"),
                }
            ),
            task_type=ENCODING_TASK_TYPE,
            request=request.model_dump(mode="json"),
            status=status.value,
            logical_artifact_id=reference.allocated_artifact_id,
            revision_id=reference.allocated_artifact_revision_id,
            worker_slot_id=None,
        )
        owner = EmbeddingEncodingAttachedEvent.model_validate(
            seal(
                {
                    "schema_version": ENCODING_PROTOCOL_VERSION,
                    "record_type": "ATTACHED",
                    "owned_job": original.model_dump(mode="json"),
                    "intent": fixture.association.intent.model_dump(mode="json"),
                },
                "event_sha256",
            )
        )
        records.append(
            EncodingReservation(
                job,
                original,
                owner,
                fixture.completions[index] if status == JobState.SUCCEEDED else None,
            )
        )
    return tuple(records)


def _owner(
    fixture: NativeAdmissionFixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[EmbeddingEncodingReservations, SyntheticAdmission, Mock, Mock, Mock]:
    session = Mock(spec=Session)
    session.in_nested_transaction.return_value = False
    session.get_transaction.return_value = object()
    context = MagicMock()
    context.__enter__.return_value = session
    factory = Mock(spec=sessionmaker)
    factory.begin.return_value = context
    admission = SyntheticAdmission(fixture)
    owner = EmbeddingEncodingReservations(cast(sessionmaker[Session], factory), admission)
    storage = Mock(spec=EmbeddingEncodingReservationStorage)
    records = _records(fixture)
    storage.reserve.return_value = (tuple(row.job for row in records), frozenset())
    storage.reservations.return_value = records
    storage.lock_references.return_value = tuple(row.job for row in records)
    storage.lock_launch.return_value = JobRecord(
        job_id=fixture.association.intent.native_launch_job_id, status=JobState.RUNNING.value
    )
    storage.association.return_value = None
    storage.owned_launch_references.return_value = references(fixture)
    storage.sequences.return_value = {row.job.job_id: 4 for row in records}
    monkeypatch.setattr(owner, "_storage", storage)
    return owner, admission, storage, session, factory


def test_required_owner_admission_has_no_default_or_null_fallback() -> None:
    factory = cast(sessionmaker[Session], Mock(spec=sessionmaker))
    with pytest.raises(EmbeddingEncodingReservationError, match="OWNER_UNAVAILABLE"):
        EmbeddingEncodingReservations(factory, cast(EmbeddingEncodingOwnerAdmission, None))
    assert (
        signature(EmbeddingEncodingReservations).parameters["admission"].default is Parameter.empty
    )


@pytest.mark.parametrize("fault", ["no_root", "inactive_root", "savepoint", "dialect", "owner"])
def test_protocol_preparation_refuses_nonowner_or_nonroot_before_insert(fault: str) -> None:
    session = Mock(spec=Session)
    session.get_transaction.return_value = (
        None if fault == "no_root" else SimpleNamespace(is_active=fault != "inactive_root")
    )
    session.in_nested_transaction.return_value = fault == "savepoint"
    session.get_bind.return_value.dialect.name = "sqlite" if fault == "dialect" else "postgresql"
    session.scalar.return_value = fault != "owner"
    with pytest.raises(EmbeddingEncodingReservationError, match="PROTOCOL_OWNER_REQUIRED"):
        EmbeddingEncodingReservationStorage.prepare_protocol(session)
    session.execute.assert_not_called()


def test_reservation_fences_exact_scope_before_writes_and_late_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    result = owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    assert all(row.status == "OWNED" for row in result)
    assert admission.calls == ["reserve_current", "read_current", "mutation_current"]
    assert storage.attach.call_count == 1


@pytest.mark.parametrize("denied", ["reserve_current", "read_current", "mutation_current"])
def test_current_owner_or_late_time_expiry_refusal_rolls_back_call(
    monkeypatch: pytest.MonkeyPatch, denied: str
) -> None:
    fixture = reservation_fixture("a")
    owner, admission, storage, _session, factory = _owner(fixture, monkeypatch)
    admission.denied = denied
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    assert (
        factory.begin.return_value.__exit__.call_args.args[0] is EmbeddingEncodingReservationError
    )
    if denied == "reserve_current":
        storage.reserve.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["empty", "oversized", "duplicate", "reverse", "copied", "foreign_scope"]
)
def test_bad_computational_request_or_source_plan_is_not_admitted(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, _admission, storage, _session, factory = _owner(fixture, monkeypatch)
    batch = requests(fixture)
    if failure == "empty":
        batch = ()
    elif failure == "oversized":
        batch = (batch[0],) * 1025
    elif failure == "duplicate":
        batch = (batch[0], batch[0])
    elif failure == "reverse":
        batch = tuple(reversed(batch))
    elif failure == "copied":
        batch = (batch[0].model_copy(update={"request_sha256": "sha256:" + "0" * 64}), batch[1])
    else:
        batch = requests(reservation_fixture("c"))
    with pytest.raises(EmbeddingEncodingReservationError):
        owner.reserve_and_attach(batch, fixture.association.intent)
    storage.reserve.assert_not_called()
    if failure != "foreign_scope":
        factory.begin.assert_not_called()


def test_binding_exact_replay_and_changed_association_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.association.return_value = fixture.association
    owner.bind_launch(fixture.association)
    storage.append.assert_not_called()
    assert admission.calls == ["launch_current", "mutation_current"]
    storage.association.return_value = fixture.association.model_copy(
        update={"association_sha256": "sha256:" + "0" * 64}
    )
    with pytest.raises(EmbeddingEncodingReservationError, match="LAUNCH_CONFLICT"):
        owner.bind_launch(fixture.association)


def test_binding_missing_owned_key_or_borrowed_key_cannot_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, _admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.owned_launch_references.return_value = references(fixture)[:1]
    with pytest.raises(EmbeddingEncodingReservationError, match="OWNED_SUBSET_MISMATCH"):
        owner.bind_launch(fixture.association)
    storage.append.assert_not_called()


def test_completion_exact_replay_rechecks_actual_owner_and_never_appends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.association.return_value = fixture.association
    storage.reservations.return_value = _records(fixture, JobState.SUCCEEDED)
    result = owner.complete(fixture.completions)
    assert all(row.status == "COMPLETED" for row in result)
    assert admission.calls == [
        "mutation_current",
        "completion_current",
        "read_current",
        "mutation_current",
    ]
    storage.append.assert_not_called()


def test_completion_requires_whole_set_and_runs_single_batch_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a", "b")
    owner, _admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.association.return_value = fixture.association
    with pytest.raises(EmbeddingEncodingReservationError, match="OWNED_SUBSET_MISMATCH"):
        owner.complete(fixture.completions[:1])
    records = _records(fixture, JobState.RUNNING)
    completed = tuple(
        replace(row, completion=event)
        for row, event in zip(records, fixture.completions, strict=True)
    )
    storage.lock_references.return_value = tuple(row.job for row in records)
    storage.reservations.side_effect = (records, completed)

    def append(
        session: Session,
        job: JobRecord,
        sequences: dict[str, int],
        event: str,
        data: dict[str, Any],
        *,
        target: JobState | None = None,
    ) -> None:
        if target is not None:
            job.status = target.value

    storage.append.side_effect = append
    result = owner.complete(fixture.completions)
    assert all(row.status == "COMPLETED" for row in result)
    assert sum(call.args[3] == COMPLETED_EVENT for call in storage.append.call_args_list) == 2


@pytest.mark.parametrize("status", [JobState.FAILED, JobState.CANCELLED])
def test_terminal_jobs_never_reset_or_complete(
    monkeypatch: pytest.MonkeyPatch, status: JobState
) -> None:
    fixture = reservation_fixture("a")
    owner, _admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.association.return_value = fixture.association
    records = _records(fixture, status)
    storage.lock_references.return_value = tuple(row.job for row in records)
    storage.reservations.return_value = records
    assert owner.read(references(fixture))[0].status == status.value
    with pytest.raises(EmbeddingEncodingReservationError, match="TERMINAL_OR_FOREIGN"):
        owner.complete(fixture.completions)
    storage.append.assert_not_called()


def test_historical_read_uses_fresh_explicit_scope_not_winner_old_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    storage.reservations.return_value = _records(fixture, JobState.SUCCEEDED)
    admission.observed = ObservedEncodingReads(None, frozenset())
    assert owner.read(references(fixture))[0].status == "COMPLETED"
    assert admission.calls == ["read_scope_current", "read_current"]
    admission.denied = "read_current"
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        owner.read(references(fixture))


def test_read_scope_denial_precedes_existence_or_reference_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    admission.denied = "read_scope_current"
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        owner.read(references(fixture))
    storage.lock_references.assert_not_called()


def test_uncertain_expired_launch_keeps_original_job_without_reencoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reservation_fixture("a")
    owner, admission, storage, _session, _factory = _owner(fixture, monkeypatch)
    admission.observed = ObservedEncodingReads(
        None, frozenset({fixture.association.intent.native_launch_job_id})
    )
    result = owner.read(references(fixture))
    assert (
        result[0].status == "UNCERTAIN" and result[0].owned_job == fixture.association.owned_jobs[0]
    )
    storage.reserve.assert_not_called()
    storage.append.assert_not_called()


@pytest.mark.parametrize("failure", ["request_hash", "allocation", "task", "slot"])
def test_original_structured_job_identity_and_allocations_are_not_reinterpreted(
    failure: str,
) -> None:
    fixture = reservation_fixture("a")
    record = _records(fixture)[0]
    if failure == "request_hash":
        record.job.request_hash = record.owned_job.request.request_sha256
    elif failure == "allocation":
        record.job.revision_id = "bad"
    elif failure == "task":
        record.job.task_type = "legacy"
    else:
        record.job.worker_slot_id = "A1"
    with pytest.raises(EmbeddingEncodingReservationError):
        owned_job(record.job)


@pytest.mark.parametrize(
    "state,name,expected",
    [
        ("23505", "jobs_idempotency_key_key", True),
        ("23505", "jobs_pkey", False),
        ("23505", "uq_job_events_sequence", False),
        ("23503", "jobs_idempotency_key_key", False),
    ],
)
def test_only_exact_postgresql_encoding_key_unique_race_is_retriable(
    state: str, name: str, expected: bool
) -> None:
    original = Mock(sqlstate=state, diag=Mock(constraint_name=name))
    assert _is_key_race(IntegrityError(None, None, original)) is expected
