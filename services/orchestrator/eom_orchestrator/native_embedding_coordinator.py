"""Fixed checkpoint storage in the existing native Job history, never caller authority."""

from __future__ import annotations

from dataclasses import dataclass

from eom_identifiers import content_sha256
from eom_workflow.local_embedding_encoding_job import LocalEmbeddingLaunchIntent
from eom_workflow.local_embedding_request import LocalEmbeddingExecutableRequest
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorIndexPrepared,
    NativeCoordinatorPhase,
    NativeEmbeddingCoordinatorCheckpoint,
    parse_native_embedding_coordinator_checkpoint,
    validate_native_coordinator_history,
)
from eom_workflow.schemas import NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationError,
)
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_embedding_launch_identity import require_native_embedding_launch
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.state_machine import JobState, transition_job

_STAGES: dict[NativeCoordinatorPhase, tuple[JobState, JobState]] = {
    "ALLOCATION": (JobState.CLAIMED, JobState.RUNNING),
    "INDEX_PREPARED": (JobState.RUNNING, JobState.VALIDATING_RESULT),
    "REGISTERED": (JobState.VALIDATING_RESULT, JobState.COMMITTING),
    "COMPLETED": (JobState.COMMITTING, JobState.SUCCEEDED),
}
_EVENT_PHASES = {"EMBEDDING_NATIVE_" + phase: phase for phase in _STAGES}


@dataclass(frozen=True, slots=True)
class NativeEmbeddingCoordinatorHistory:
    state: str
    records: tuple[NativeEmbeddingCoordinatorCheckpoint, ...]


def native_embedding_index_registration_key(
    intent: LocalEmbeddingLaunchIntent, index_id: str, revision_id: str
) -> str:
    return "native-index-register:" + content_sha256(
        {
            "intent_sha256": intent.intent_sha256,
            "index_id": index_id,
            "index_revision_id": revision_id,
        }
    ).removeprefix("sha256:")


class NativeEmbeddingCoordinator:
    """Caller retains fresh Workflow/command/source fences in each non-savepoint root."""

    def __init__(
        self, intent: LocalEmbeddingLaunchIntent, request: LocalEmbeddingExecutableRequest
    ) -> None:
        self.intent, self.request = intent, request

    def read(self, session: Session) -> NativeEmbeddingCoordinatorHistory:
        observation = require_native_embedding_launch(session, self.intent, self.request)
        rows = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(
                    JobEventRecord.job_id == self.intent.native_launch_job_id,
                    JobEventRecord.event.in_(tuple(_EVENT_PHASES)),
                )
                .order_by(JobEventRecord.sequence)
            )
        )
        try:
            records = tuple(parse_native_embedding_coordinator_checkpoint(row.data) for row in rows)
            if records:
                protocol = session.get(
                    ProtocolVersionRecord,
                    "native-embedding-coordinator/1.0",
                    populate_existing=True,
                )
                if (
                    protocol is None
                    or protocol.schema_sha256 != NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[2]
                ):
                    raise ValueError("coordinator protocol registration differs")
            validate_native_coordinator_history(records, self.intent)
            for row, record in zip(rows, records, strict=True):
                start, end = _STAGES[record.record_type]
                if _EVENT_PHASES[row.event] != record.record_type or (
                    row.from_state,
                    row.to_state,
                ) != (start.value, end.value):
                    raise ValueError("coordinator event transition differs")
                if isinstance(record.payload, NativeCoordinatorIndexPrepared):
                    command, request = record.payload.registration_command, self.request
                    if (
                        command.corpus_id != request.corpus_id
                        or command.namespace != request.namespace
                        or command.graph_snapshot != request.graph_snapshot
                        or command.policy_revision_id != request.access_policy_revision_id
                        or command.policy_sha256 != request.access_policy_sha256
                        or command.operation_key
                        != native_embedding_index_registration_key(
                            self.intent, command.index_id, command.index_revision_id
                        )
                    ):
                        raise ValueError("prepared registration differs from original request")
            expected = JobState.CLAIMED if not records else _STAGES[records[-1].record_type][1]
            if observation.state not in {
                expected.value,
                JobState.FAILED.value,
                JobState.CANCELLED.value,
            }:
                raise ValueError("coordinator state differs from contiguous checkpoint history")
            return NativeEmbeddingCoordinatorHistory(observation.state, records)
        except (ValueError, TypeError, KeyError):
            raise EmbeddingEncodingReservationError(
                "EMBEDDING_NATIVE_CHECKPOINT_HISTORY_INVALID"
            ) from None

    def append(
        self, session: Session, record: NativeEmbeddingCoordinatorCheckpoint
    ) -> NativeEmbeddingCoordinatorHistory:
        # Native/Workflow owner context is checked before any transition or protocol write.
        require_native_embedding_launch(session, self.intent, self.request)
        session.execute(
            select(JobRecord)
            .where(JobRecord.job_id == self.intent.native_launch_job_id)
            .with_for_update()
        ).scalar_one()
        record = parse_native_embedding_coordinator_checkpoint(record)
        history = self.read(session)
        prior = {value.record_type: value for value in history.records}
        if record.record_type in prior:
            if prior[record.record_type] != record:
                raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_CHECKPOINT_CONFLICT")
            return history
        try:
            validate_native_coordinator_history((*history.records, record), self.intent)
        except (ValueError, TypeError):
            raise EmbeddingEncodingReservationError(
                "EMBEDDING_NATIVE_CHECKPOINT_ORDER_INVALID"
            ) from None
        if history.state != _STAGES[record.record_type][0].value:
            raise EmbeddingEncodingReservationError(
                "EMBEDDING_NATIVE_CHECKPOINT_TERMINAL_OR_FOREIGN"
            )
        if session.get_bind().dialect.name == "postgresql":
            # Different native Jobs may allocate concurrently before CPU capacity
            # admission. First-use schema registration must not race those roots.
            session.execute(
                insert(ProtocolVersionRecord)
                .values(
                    version="native-embedding-coordinator/1.0",
                    schema_sha256=NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[2],
                )
                .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
            )
        ensure_protocol_version(
            session,
            "native-embedding-coordinator/1.0",
            NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[2],
        )
        transition_job(
            session,
            self.intent.native_launch_job_id,
            _STAGES[record.record_type][1],
            "EMBEDDING_NATIVE_" + record.record_type,
            data=record.model_dump(mode="json"),
        )
        session.flush()
        return self.read(session)
