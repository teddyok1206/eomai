"""Fixed per-encoding Orchestrator owner, unavailable without actual trusted admission.

Every port implementation must capture the current authenticated caller/target scope,
not use a persisted actor audit. This module supplies no production composition,
permission grant, native launcher, worker database access or inference transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    SupportedEmbeddingCompletedEvent,
    SupportedEmbeddingIntent,
    SupportedEmbeddingReadResult,
    parse_supported_embedding_association,
    parse_supported_embedding_completed,
    parse_supported_embedding_intent,
    parse_supported_embedding_message,
    parse_supported_embedding_read,
    validate_supported_embedding_association,
    validate_supported_embedding_completions,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    LocalEmbeddingLaunchIntentV2,
)
from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingExecutablePolicy,
    parse_local_embedding_executable_policy,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    validate_supported_local_embedding_request_references,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import LocalEmbeddingSourcePlanV2
from eom_workflow.schemas import NativeEmbeddingContract
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.embedding_encoding_reservation_storage import (
    ASSOCIATION_EVENT,
    COMPLETED_EVENT,
    EmbeddingEncodingReservationError,
    EmbeddingEncodingReservationStorage,
    EncodingReservation,
)
from eom_orchestrator.state_machine import JobState


@dataclass(frozen=True, slots=True)
class ResolvedEncodingScope:
    workflow_request: SupportedLocalEmbeddingRequest
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2
    policy: LocalEmbeddingExecutablePolicy


@dataclass(frozen=True, slots=True)
class ResolvedEncodingLaunch:
    scope: ResolvedEncodingScope
    owned_input: IncrementalEmbeddingInput


@dataclass(frozen=True, slots=True)
class ResolvedEncodingCompletion:
    owned_input: IncrementalEmbeddingInput
    result: IncrementalEmbeddingResult


@dataclass(frozen=True, slots=True)
class EncodingReadTarget:
    owned_job: LocalEmbeddingOwnedJob
    owner_intent: SupportedEmbeddingIntent
    completion: SupportedEmbeddingCompletedEvent | None


@dataclass(frozen=True, slots=True)
class ObservedEncodingReads:
    """Trusted owner observations after fresh read admission, never an authority DTO."""

    current_intent: SupportedEmbeddingIntent | None
    uncertain_launch_job_ids: frozenset[str]


class EmbeddingEncodingOwnerAdmission(Protocol):
    """Mandatory official-owner seam; no default or activated implementation.

    Mutation resolution fences current caller/session, exact command token/generation,
    released native policy/runtime, and every selected source under the root transaction.
    The final fence repeats actual live-command/time-expiry checks immediately before
    commit. A saved operator ID/audit/generation is never authentication or a lease.
    Read reauthorizes the caller's explicit current target scope and canonical output;
    it must not require an expired historical command or grant the winner's full plan.
    All Artifact members/binary proof are resolved by the actual public owner boundaries.
    """

    def resolve_reservation(
        self,
        session: Session,
        requests: tuple[EmbeddingEncodingJobRequest, ...],
        intent: SupportedEmbeddingIntent,
    ) -> ResolvedEncodingScope: ...

    def resolve_launch(
        self,
        session: Session,
        association: SupportedEmbeddingAssociation,
    ) -> ResolvedEncodingLaunch: ...

    def resolve_completion(
        self,
        session: Session,
        association: SupportedEmbeddingAssociation,
        events: tuple[SupportedEmbeddingCompletedEvent, ...],
    ) -> ResolvedEncodingCompletion:
        """Prove committed/approved exact shared file set, raw/semantic pins and finite/L2 rows."""
        ...

    def reauthorize_read(
        self,
        session: Session,
        targets: tuple[EncodingReadTarget, ...],
    ) -> ObservedEncodingReads: ...

    def fence_read_scope(
        self,
        session: Session,
        references: tuple[EmbeddingEncodingJobReference, ...],
    ) -> None:
        """Fresh caller/explicit selected scope before existence or stale-reference errors."""
        ...

    def fence_mutation(self, session: Session, intent: SupportedEmbeddingIntent) -> None: ...


def _parse[Record: NativeEmbeddingContract](
    value: object, expected: type[Record] | tuple[type[Record], ...]
) -> Record:
    try:
        parsed = parse_supported_embedding_message(value)
        if not isinstance(parsed, expected):
            raise ValueError("wrong record")
        return parsed
    except (ValueError, TypeError):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_CONTRACT_INVALID") from None


def _batch(values: tuple[object, ...]) -> None:
    if type(values) is not tuple or not 1 <= len(values) <= 1024:
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")


def _intent(value: SupportedEmbeddingIntent) -> SupportedEmbeddingIntent:
    try:
        return parse_supported_embedding_intent(value)
    except (ValueError, TypeError):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_CONTRACT_INVALID") from None


def _scope(
    proof: ResolvedEncodingScope,
    intent: SupportedEmbeddingIntent,
    requests: tuple[EmbeddingEncodingJobRequest, ...],
) -> None:
    try:
        request = parse_supported_local_embedding_request(proof.workflow_request)
        plan = proof.plan
        policy = parse_local_embedding_executable_policy(proof.policy)
        validate_supported_local_embedding_request_references(request, plan, policy)
        planned = {demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands}
        if (
            intent.workflow_request_sha256 != request.request_sha256
            or intent.source_plan != request.source_plan
            or intent.source_plan_sha256 != request.source_plan_sha256
            or intent.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
            or any(
                row.space != request.space
                or planned.get(row.encoding.encoding_sha256) != row.encoding
                for row in requests
            )
        ):
            raise ValueError("different admitted control closure")
    except (ValueError, TypeError, AttributeError):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_SCOPE_MISMATCH") from None


def _references(
    values: tuple[EmbeddingEncodingJobReference, ...],
) -> tuple[EmbeddingEncodingJobReference, ...]:
    _batch(values)
    try:
        references = tuple(EmbeddingEncodingJobReference.model_validate(value) for value in values)
    except (ValueError, TypeError):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_CONTRACT_INVALID") from None
    ids = tuple(ref.job_id for ref in references)
    if ids != tuple(sorted(set(ids))):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
    return references


def _targets(records: tuple[EncodingReservation, ...]) -> tuple[EncodingReadTarget, ...]:
    return tuple(
        EncodingReadTarget(row.owned_job, row.owner.intent, row.completion) for row in records
    )


def _results(
    records: tuple[EncodingReservation, ...],
    observed: ObservedEncodingReads,
) -> tuple[SupportedEmbeddingReadResult, ...]:
    if type(
        observed.uncertain_launch_job_ids
    ) is not frozenset or not observed.uncertain_launch_job_ids.issubset(
        {row.owner.intent.native_launch_job_id for row in records}
    ):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_OBSERVATION_INVALID")
    current = None if observed.current_intent is None else _intent(observed.current_intent)
    values = []
    for row in records:
        if row.job.status == JobState.SUCCEEDED.value:
            status = "COMPLETED"
        elif row.job.status in {JobState.FAILED.value, JobState.CANCELLED.value}:
            status = row.job.status
        elif row.owner.intent.native_launch_job_id in observed.uncertain_launch_job_ids:
            status = "UNCERTAIN"
        else:
            status = "OWNED" if row.owner.intent == current else "BORROWED"
        body = {
            "schema_version": "embedding-encoding-ownership/2.0"
            if isinstance(row.owner.intent, LocalEmbeddingLaunchIntentV2)
            else "embedding-encoding-job/1.0",
            "record_type": "READ_RESULT",
            "owned_job": row.owned_job.model_dump(mode="json"),
            "owner_intent": row.owner.intent.model_dump(mode="json"),
            "status": status,
            "completion": None
            if row.completion is None
            else row.completion.model_dump(mode="json"),
        }
        values.append(parse_supported_embedding_read(body | {"read_sha256": content_sha256(body)}))
    return tuple(values)


class EmbeddingEncodingReservations:
    """Supported fixed-purpose public owner API; constructor never supplies admission."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        admission: EmbeddingEncodingOwnerAdmission,
    ) -> None:
        if admission is None:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_OWNER_UNAVAILABLE")
        self._sessions = session_factory
        self._admission = admission
        self._storage = EmbeddingEncodingReservationStorage()

    def reserve_and_attach(
        self,
        requests: tuple[EmbeddingEncodingJobRequest, ...],
        intent: SupportedEmbeddingIntent,
    ) -> tuple[SupportedEmbeddingReadResult, ...]:
        _batch(requests)
        requests = tuple(_parse(row, EmbeddingEncodingJobRequest) for row in requests)
        keys = tuple(row.encoding.encoding_sha256 for row in requests)
        if keys != tuple(sorted(set(keys))):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        intent = _intent(intent)
        with self._sessions.begin() as session:
            proof = self._admission.resolve_reservation(session, requests, intent)
            _scope(proof, intent, requests)
            self._storage.require_protocol(session)
            self._storage.lock_launch(session, intent.native_launch_job_id)
            existing = self._storage.association(session, intent.native_launch_job_id)
            if existing is not None and existing.intent != intent:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_INTENT_CONFLICT")
            jobs, created = self._storage.reserve(session, requests)
            if existing is not None and created:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_LAUNCH_CONFLICT")
            self._storage.attach(session, jobs, created, intent)
            records = self._storage.reservations(session, jobs)
            observed = self._admission.reauthorize_read(session, _targets(records))
            result = _results(records, observed)
            self._admission.fence_mutation(session, intent)
            return result

    def retry_known_failed(
        self,
        requests: tuple[EmbeddingEncodingJobRequest, ...],
        intent: SupportedEmbeddingIntent,
    ) -> tuple[SupportedEmbeddingReadResult, ...]:
        """Fresh admitted successor producer only after an official known-failure record.

        This does not mark old work failed, accept a claimed root proof, refresh a
        lease, restart a worker or choose another device. The old Job remains
        FAILED; its pinned reference never redirects to the successor.
        """
        _batch(requests)
        requests = tuple(_parse(row, EmbeddingEncodingJobRequest) for row in requests)
        keys = tuple(row.encoding.encoding_sha256 for row in requests)
        if keys != tuple(sorted(set(keys))):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        intent = _intent(intent)
        with self._sessions.begin() as session:
            proof = self._admission.resolve_reservation(session, requests, intent)
            _scope(proof, intent, requests)
            self._storage.require_protocol(session)
            self._storage.lock_launch(session, intent.native_launch_job_id)
            if self._storage.association(session, intent.native_launch_job_id) is not None:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_LAUNCH_CONFLICT")
            jobs, created = self._storage.retry_known_failed(session, requests)
            self._storage.attach(session, jobs, created, intent)
            records = self._storage.reservations(session, jobs)
            observed = self._admission.reauthorize_read(session, _targets(records))
            result = _results(records, observed)
            self._admission.fence_mutation(session, intent)
            return result

    def bind_launch(self, association: SupportedEmbeddingAssociation) -> None:
        association = parse_supported_embedding_association(association)
        with self._sessions.begin() as session:
            proof = self._admission.resolve_launch(session, association)
            _scope(
                proof.scope,
                association.intent,
                tuple(job.request for job in association.owned_jobs),
            )
            try:
                validate_supported_embedding_association(
                    association,
                    proof.scope.plan,
                    proof.owned_input,
                    proof.scope.workflow_request.resource_profile,
                    proof.scope.workflow_request.request_sha256,
                )
            except (ValueError, TypeError, JsonSchemaValidationError):
                raise EmbeddingEncodingReservationError(
                    "EMBEDDING_ENCODING_LAUNCH_INVALID"
                ) from None
            launch = self._storage.lock_launch(session, association.intent.native_launch_job_id)
            existing = self._storage.association(session, launch.job_id)
            if existing is not None and existing != association:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_LAUNCH_CONFLICT")
            # The whole persisted winner set is selected by this exact launch identity.
            plan_keys = tuple(
                sorted(
                    {
                        "embedding-encode:" + demand.encoding.encoding_sha256
                        for demand in proof.scope.plan.demands
                    }
                )
            )
            all_owned = self._storage.owned_launch_references(session, launch.job_id, plan_keys)
            expected = {job.job_reference for job in association.owned_jobs}
            if set(all_owned) != expected or len(all_owned) != len(expected):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_OWNED_SUBSET_MISMATCH")
            jobs = self._storage.lock_references(
                session, tuple(sorted(expected, key=lambda ref: ref.job_id)), lock=True
            )
            records = self._storage.reservations(session, jobs)
            if any(row.owner.intent != association.intent for row in records):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN")
            if existing is not None:
                self._admission.fence_mutation(session, association.intent)
                return
            if any(row.job.status != JobState.CLAIMED.value for row in records):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN")
            sequences = self._storage.sequences(session, (*jobs, launch))
            self._storage.append(
                session, launch, sequences, ASSOCIATION_EVENT, association.model_dump(mode="json")
            )
            for job in jobs:
                self._storage.append(
                    session,
                    job,
                    sequences,
                    "EMBEDDING_ENCODING_BOUND",
                    {"association_sha256": association.association_sha256},
                    target=JobState.RUNNING,
                )
            session.flush()
            self._admission.fence_mutation(session, association.intent)

    def complete(
        self,
        events: tuple[SupportedEmbeddingCompletedEvent, ...],
    ) -> tuple[SupportedEmbeddingReadResult, ...]:
        _batch(events)
        events = tuple(parse_supported_embedding_completed(event) for event in events)
        keys = tuple(event.owned_job.request.encoding.encoding_sha256 for event in events)
        if keys != tuple(sorted(set(keys))) or len({event.intent for event in events}) != 1:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        intent = events[0].intent
        with self._sessions.begin() as session:
            self._admission.fence_mutation(session, intent)
            # Required resolution includes initial current command fencing before writes.
            launch = self._storage.lock_launch(session, intent.native_launch_job_id)
            association = self._storage.association(session, launch.job_id)
            if (
                association is None
                or association.intent != intent
                or tuple(event.owned_job for event in events) != association.owned_jobs
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_OWNED_SUBSET_MISMATCH")
            proof = self._admission.resolve_completion(session, association, events)
            try:
                validate_supported_embedding_completions(
                    events, association, proof.owned_input, proof.result
                )
            except (ValueError, TypeError, JsonSchemaValidationError):
                raise EmbeddingEncodingReservationError(
                    "EMBEDDING_ENCODING_COMPLETION_INVALID"
                ) from None
            references = tuple(
                sorted(
                    (event.owned_job.job_reference for event in events), key=lambda ref: ref.job_id
                )
            )
            jobs = self._storage.lock_references(session, references, lock=True)
            records = self._storage.reservations(session, jobs)
            by_id = {row.job.job_id: row for row in records}
            if any(
                by_id[event.owned_job.job_reference.job_id].owner.intent != intent
                for event in events
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_INTENT_CONFLICT")
            prior = tuple(
                by_id[event.owned_job.job_reference.job_id].completion for event in events
            )
            if any(value is not None for value in prior):
                if prior != events:
                    raise EmbeddingEncodingReservationError(
                        "EMBEDDING_ENCODING_COMPLETION_CONFLICT"
                    )
            else:
                if any(job.status != JobState.RUNNING.value for job in jobs):
                    raise EmbeddingEncodingReservationError(
                        "EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN"
                    )
                sequences = self._storage.sequences(session, jobs)
                for event in events:
                    job = by_id[event.owned_job.job_reference.job_id].job
                    self._storage.append(
                        session,
                        job,
                        sequences,
                        "EMBEDDING_ENCODING_RESULT_VALIDATED",
                        {},
                        target=JobState.VALIDATING_RESULT,
                    )
                    self._storage.append(
                        session,
                        job,
                        sequences,
                        "EMBEDDING_ENCODING_RESULT_COMMIT_VERIFIED",
                        {},
                        target=JobState.COMMITTING,
                    )
                    self._storage.append(
                        session,
                        job,
                        sequences,
                        COMPLETED_EVENT,
                        event.model_dump(mode="json"),
                        target=JobState.SUCCEEDED,
                    )
                session.flush()
                records = self._storage.reservations(session, jobs)
            observed = self._admission.reauthorize_read(session, _targets(records))
            result = _results(records, observed)
            self._admission.fence_mutation(session, intent)
            return result

    def read(
        self,
        references: tuple[EmbeddingEncodingJobReference, ...],
    ) -> tuple[SupportedEmbeddingReadResult, ...]:
        references = _references(references)
        with self._sessions.begin() as session:
            return self.read_in_session(session, references)

    def read_in_session(
        self, session: Session, references: tuple[EmbeddingEncodingJobReference, ...]
    ) -> tuple[SupportedEmbeddingReadResult, ...]:
        """Supported same-root read for atomic receipt verification; no inference/write."""
        if session.get_transaction() is None or session.in_nested_transaction():
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_OWNER_ROOT_REQUIRED")
        references = _references(references)
        self._admission.fence_read_scope(session, references)
        jobs = self._storage.lock_references(session, references, lock=False)
        records = self._storage.reservations(session, jobs)
        observed = self._admission.reauthorize_read(session, _targets(records))
        by_id = {
            value.owned_job.job_reference.job_id: value for value in _results(records, observed)
        }
        return tuple(by_id[reference.job_id] for reference in references)
