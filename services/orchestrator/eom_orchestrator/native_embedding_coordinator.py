"""Fixed checkpoint storage in the existing native Job history, never caller authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    LocalEmbeddingLaunchIntentV2,
    SupportedLocalEmbeddingLaunchIntent,
    parse_local_embedding_launch_intent_for_request,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorIndexPrepared,
    NativeCoordinatorPhase,
    NativeEmbeddingCoordinatorCheckpoint,
    parse_native_embedding_coordinator_checkpoint,
    validate_native_coordinator_history,
)
from eom_workflow.native_embedding_coordinator_v2 import (
    NativeCoordinatorIndexPreparedV2,
    NativeEmbeddingCoordinatorCheckpointV2,
    parse_native_embedding_coordinator_checkpoint_v2,
    validate_native_coordinator_history_v2,
)
from eom_workflow.schemas import (
    NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE,
    NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE,
    NativeEmbeddingContract,
)
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

type SupportedNativeCoordinatorCheckpoint = (
    NativeEmbeddingCoordinatorCheckpoint | NativeEmbeddingCoordinatorCheckpointV2
)


@dataclass(frozen=True, slots=True)
class NativeEmbeddingCoordinatorHistory:
    state: str
    records: tuple[SupportedNativeCoordinatorCheckpoint, ...]


def native_embedding_index_registration_key(
    intent: SupportedLocalEmbeddingLaunchIntent, index_id: str, revision_id: str
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
        self, intent: SupportedLocalEmbeddingLaunchIntent, request: SupportedLocalEmbeddingRequest
    ) -> None:
        self.request = parse_supported_local_embedding_request(request)
        self.intent = parse_local_embedding_launch_intent_for_request(intent, self.request)

    def _parse_checkpoint(self, value: object) -> SupportedNativeCoordinatorCheckpoint:
        if isinstance(self.intent, LocalEmbeddingLaunchIntentV2):
            return parse_native_embedding_coordinator_checkpoint_v2(value)
        return parse_native_embedding_coordinator_checkpoint(value)

    def checkpoint(
        self, phase: NativeCoordinatorPhase, payload: NativeEmbeddingContract
    ) -> SupportedNativeCoordinatorCheckpoint:
        """Build only this original intent's exact metadata family; no DB/effects."""
        body = {
            "schema_version": self._checkpoint_protocol()[0],
            "record_type": phase,
            "native_launch_job_id": self.intent.native_launch_job_id,
            "intent_sha256": self.intent.intent_sha256,
            "payload": raw_similarity_contract_value(payload),
        }
        return self._parse_checkpoint(body | {"checkpoint_sha256": content_sha256(body)})

    def _validate_history(self, records: tuple[SupportedNativeCoordinatorCheckpoint, ...]) -> None:
        if isinstance(self.intent, LocalEmbeddingLaunchIntentV2):
            if any(type(row) is not NativeEmbeddingCoordinatorCheckpointV2 for row in records):
                raise ValueError("mixed coordinator checkpoint family differs")
            validate_native_coordinator_history_v2(
                cast(tuple[NativeEmbeddingCoordinatorCheckpointV2, ...], records),
                self.intent,
            )
        else:
            if any(type(row) is not NativeEmbeddingCoordinatorCheckpoint for row in records):
                raise ValueError("legacy coordinator checkpoint family differs")
            validate_native_coordinator_history(
                cast(tuple[NativeEmbeddingCoordinatorCheckpoint, ...], records),
                self.intent,
            )

    def _checkpoint_protocol(self) -> tuple[str, str]:
        if isinstance(self.intent, LocalEmbeddingLaunchIntentV2):
            return (
                "native-embedding-coordinator/2.0",
                NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE[2],
            )
        return "native-embedding-coordinator/1.0", NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[2]

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
            records = tuple(self._parse_checkpoint(row.data) for row in rows)
            if records:
                version, expected_hash = self._checkpoint_protocol()
                protocol = session.get(
                    ProtocolVersionRecord,
                    version,
                    populate_existing=True,
                )
                if protocol is None or protocol.schema_sha256 != expected_hash:
                    raise ValueError("coordinator protocol registration differs")
            self._validate_history(records)
            for row, record in zip(rows, records, strict=True):
                start, end = _STAGES[record.record_type]
                if _EVENT_PHASES[row.event] != record.record_type or (
                    row.from_state,
                    row.to_state,
                ) != (start.value, end.value):
                    raise ValueError("coordinator event transition differs")
                if isinstance(
                    record.payload,
                    (NativeCoordinatorIndexPrepared, NativeCoordinatorIndexPreparedV2),
                ):
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
        self, session: Session, record: SupportedNativeCoordinatorCheckpoint
    ) -> NativeEmbeddingCoordinatorHistory:
        # Native/Workflow owner context is checked before any transition or protocol write.
        require_native_embedding_launch(session, self.intent, self.request)
        session.execute(
            select(JobRecord)
            .where(JobRecord.job_id == self.intent.native_launch_job_id)
            .with_for_update()
        ).scalar_one()
        record = self._parse_checkpoint(record)
        history = self.read(session)
        prior = {value.record_type: value for value in history.records}
        if record.record_type in prior:
            if prior[record.record_type] != record:
                raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_CHECKPOINT_CONFLICT")
            return history
        try:
            self._validate_history((*history.records, record))
        except (ValueError, TypeError):
            raise EmbeddingEncodingReservationError(
                "EMBEDDING_NATIVE_CHECKPOINT_ORDER_INVALID"
            ) from None
        if history.state != _STAGES[record.record_type][0].value:
            raise EmbeddingEncodingReservationError(
                "EMBEDDING_NATIVE_CHECKPOINT_TERMINAL_OR_FOREIGN"
            )
        version, expected_hash = self._checkpoint_protocol()
        if session.get_bind().dialect.name == "postgresql":
            # Different native Jobs may allocate concurrently before CPU capacity
            # admission. First-use schema registration must not race those roots.
            session.execute(
                insert(ProtocolVersionRecord)
                .values(
                    version=version,
                    schema_sha256=expected_hash,
                )
                .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
            )
        ensure_protocol_version(
            session,
            version,
            expected_hash,
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
