"""Read the exact native coordinator Job; not allocation, source authority or a launcher."""

from __future__ import annotations

from dataclasses import dataclass

from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingAssociation
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    SupportedLocalEmbeddingLaunchIntent,
    local_embedding_launch_protocol,
    parse_local_embedding_launch_intent_for_request,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.embedding_encoding_reservation_storage import (
    ENCODING_PROTOCOL_VERSION,
    EmbeddingEncodingReservationError,
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job

NATIVE_LAUNCH_TASK_TYPE = "native_embedding_launch"
NATIVE_INTENT_EVENT = "EMBEDDING_NATIVE_LAUNCH_INTENT"


def _require_owner_root(session: Session) -> None:
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_OWNER_ROOT_REQUIRED")


@dataclass(frozen=True, slots=True)
class NativeEmbeddingLaunchObservation:
    state: str
    intent: SupportedLocalEmbeddingLaunchIntent


def _require_launch_protocol(session: Session, request: SupportedLocalEmbeddingRequest) -> None:
    # Numerical encoding1 remains separately prepared even when launch metadata is2.
    EmbeddingEncodingReservationStorage.require_protocol(session)
    version, expected = local_embedding_launch_protocol(request)
    if version != ENCODING_PROTOCOL_VERSION:
        record = session.get(ProtocolVersionRecord, version, populate_existing=True)
        if record is None or record.schema_sha256 != expected:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE")


def native_embedding_launch_key(workflow_id: str, step_run_id: str, request_sha256: str) -> str:
    # Context is validated by the typed intent/request before this key is used.
    digest = content_sha256(
        {
            "workflow_id": workflow_id,
            "step_run_id": step_run_id,
            "attempt": 1,
            "request_sha256": request_sha256,
        }
    )
    # The existing Job key column is128 characters: pin the tuple by its hash.
    return "native-embedding-launch:" + digest.removeprefix("sha256:")


def read_native_embedding_launch(
    session: Session,
    *,
    request: SupportedLocalEmbeddingRequest,
    workflow_id: str,
    step_run_id: str,
) -> NativeEmbeddingLaunchObservation | None:
    """Read one pinned coordinator context; caller fences current authority BEFORE this read."""
    _require_owner_root(session)
    request = parse_supported_local_embedding_request(request)
    _require_launch_protocol(session, request)
    row = session.scalar(
        select(JobRecord).where(
            JobRecord.idempotency_key
            == native_embedding_launch_key(workflow_id, step_run_id, request.request_sha256)
        )
    )
    if row is None:
        return None
    events = tuple(
        session.scalars(
            select(JobEventRecord).where(
                JobEventRecord.job_id == row.job_id, JobEventRecord.event == NATIVE_INTENT_EVENT
            )
        )
    )
    if len(events) != 1:
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_INTENT_INVALID")
    intent = parse_local_embedding_launch_intent_for_request(events[0].data, request)
    return require_native_embedding_launch(session, intent, request)


def read_native_embedding_launch_association(
    session: Session,
    intent: SupportedLocalEmbeddingLaunchIntent,
    request: SupportedLocalEmbeddingRequest,
) -> SupportedEmbeddingAssociation | None:
    """Exact owner association, not a source or current lease grant."""
    require_native_embedding_launch(session, intent, request)
    association = EmbeddingEncodingReservationStorage.association(
        session, intent.native_launch_job_id
    )
    if association is not None and association.intent != intent:
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_INTENT_INVALID")
    return association


def create_native_embedding_launch(
    session: Session,
    *,
    request: SupportedLocalEmbeddingRequest,
    workflow_id: str,
    step_run_id: str,
    command_id: str,
    runner_id: str,
    lease_generation: int,
) -> NativeEmbeddingLaunchObservation:
    """Allocate/read one coordinator inside the caller's CURRENT fenced root.

    Workflow→command locks are already held by the actual Runner/source owner.
    Reentry returns original intent, not a new Job or rewritten lease audit.
    This primitive grants neither source permission nor permission to start a unit.
    """
    _require_owner_root(session)
    request = parse_supported_local_embedding_request(request)
    _require_launch_protocol(session, request)
    key = native_embedding_launch_key(workflow_id, step_run_id, request.request_sha256)
    existing = session.scalar(
        select(JobRecord)
        .where(JobRecord.idempotency_key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        events = tuple(
            session.scalars(
                select(JobEventRecord).where(
                    JobEventRecord.job_id == existing.job_id,
                    JobEventRecord.event == NATIVE_INTENT_EVENT,
                )
            )
        )
        if len(events) != 1:
            raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_INTENT_INVALID")
        intent = parse_local_embedding_launch_intent_for_request(events[0].data, request)
        return require_native_embedding_launch(session, intent, request)
    body = {
        "workflow_id": workflow_id,
        "step_run_id": step_run_id,
        "step_key": "encode_batch",
        "attempt": 1,
        "native_launch_job_id": new_job_id(),
        "workflow_request_sha256": request.request_sha256,
        "source_plan": request.source_plan.model_dump(mode="json"),
        "source_plan_sha256": request.source_plan_sha256,
        "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
        "command_id": command_id,
        "runner_id": runner_id,
        "lease_generation": lease_generation,
    }
    intent = parse_local_embedding_launch_intent_for_request(
        body | {"intent_sha256": content_sha256(body)}, request
    )
    protocol_version, _schema_hash = local_embedding_launch_protocol(request)
    job, created = submit_structured_job(
        session,
        job_id=intent.native_launch_job_id,
        protocol_version=protocol_version,
        idempotency_key=key,
        task_type=NATIVE_LAUNCH_TASK_TYPE,
        request=request.model_dump(mode="json"),
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    if not created:
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_RACE_UNRECONCILED")
    for state, event in (
        (JobState.VALIDATED, "EMBEDDING_NATIVE_REQUEST_VALIDATED"),
        (JobState.QUEUED, "EMBEDDING_NATIVE_COORDINATOR_QUEUED"),
        (JobState.CLAIMED, NATIVE_INTENT_EVENT),
    ):
        transition_job(
            session,
            job.job_id,
            state,
            event,
            data=intent.model_dump(mode="json") if event == NATIVE_INTENT_EVENT else {},
        )
    return require_native_embedding_launch(session, intent, request)


def require_native_embedding_launch(
    session: Session,
    intent: SupportedLocalEmbeddingLaunchIntent,
    request: SupportedLocalEmbeddingRequest,
) -> NativeEmbeddingLaunchObservation:
    """Check owner-selected request/key/task and allocations, never trust Job existence."""
    _require_owner_root(session)
    request = parse_supported_local_embedding_request(request)
    intent = parse_local_embedding_launch_intent_for_request(intent, request)
    _require_launch_protocol(session, request)
    protocol_version, _schema_hash = local_embedding_launch_protocol(request)
    row = session.scalar(
        select(JobRecord)
        .where(JobRecord.job_id == intent.native_launch_job_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    payload = request.model_dump(mode="json")
    expected_hash = content_sha256(
        {
            "protocol_version": protocol_version,
            "task_type": NATIVE_LAUNCH_TASK_TYPE,
            "request": payload,
        }
    )
    if (
        row is None
        or row.protocol_version != protocol_version
        or row.task_type != NATIVE_LAUNCH_TASK_TYPE
        or row.worker_slot_id is not None
        or row.idempotency_key
        != native_embedding_launch_key(
            intent.workflow_id, intent.step_run_id, request.request_sha256
        )
        or row.request != payload
        or row.request_hash != expected_hash
        or intent.workflow_request_sha256 != request.request_sha256
        or intent.source_plan != request.source_plan
        or intent.source_plan_sha256 != request.source_plan_sha256
        or intent.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
    ):
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_CONTEXT_INVALID")
    events = tuple(
        session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == row.job_id, JobEventRecord.event == NATIVE_INTENT_EVENT)
            .order_by(JobEventRecord.sequence)
        )
    )
    if (
        len(events) != 1
        or parse_local_embedding_launch_intent_for_request(events[0].data, request) != intent
    ):
        raise EmbeddingEncodingReservationError("EMBEDDING_NATIVE_LAUNCH_INTENT_INVALID")
    return NativeEmbeddingLaunchObservation(row.status, intent)
