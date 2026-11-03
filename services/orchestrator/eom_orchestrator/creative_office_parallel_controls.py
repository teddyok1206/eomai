"""Four native Office reports using the existing capacity/preset lifecycle owners."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import content_sha256, new_capacity_policy_id, new_capacity_policy_revision_id
from eom_workflow.control_plane import ExecutionPresetRevision, WorkerCapacityPolicyV6
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
)
from eom_orchestrator.creative_parallel_controls import _release_preset, parallel_role_policies
from eom_orchestrator.preset_model_selection import (
    resolve_released_capacity_policy,
    validated_preset,
)

CAPACITY_KEY = "creative-native-office-backfill-four"


@dataclass(frozen=True, slots=True)
class CreativeOfficeParallelControls:
    capacity: WorkerCapacityPolicyV6
    extraction: ExecutionPresetRevision
    analysis: ExecutionPresetRevision


def creative_office_report_capacity_document(*, created_at: datetime) -> dict[str, object]:
    body = {
        "schema_version": "worker-capacity-policy/1.5",
        "capacity_policy_id": new_capacity_policy_id(),
        "capacity_policy_revision_id": new_capacity_policy_revision_id(),
        "revision_number": 1,
        "state": "RELEASED",
        "purpose": "OFFICE_CREATIVE_REPORT_BACKFILL",
        "max_configured_slots": 6,
        "max_active_codex": 4,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 4,
        "pools": [
            {
                "pool_key": "support",
                "roles": ["support"],
                "slot_keys": ["slot03", "slot04", "slot05", "slot06"],
                "max_active": 4,
            }
        ],
        "delegated_slot_roles": [
            {
                "pool_key": "support",
                "slot_key": "slot03",
                "native_role": "image",
                "execution_role": "support",
            },
            {
                "pool_key": "support",
                "slot_key": "slot04",
                "native_role": "item_management",
                "execution_role": "support",
            },
        ],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    return {**body, "content_sha256": content_sha256(body)}


def release_creative_office_parallel_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    extraction_revision_id: str,
    analysis_revision_id: str,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> CreativeOfficeParallelControls:
    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        baselines = []
        for revision_id, expected_key in (
            (extraction_revision_id, "creative-office-learning"),
            (analysis_revision_id, "creative-knowledge-analysis-parallel"),
        ):
            row = session.get(ExecutionPresetRevisionRecord, revision_id)
            baseline = validated_preset(row) if row else None
            logical = session.get(ExecutionPresetRecord, baseline.preset_id) if baseline else None
            if (
                not isinstance(baseline, ExecutionPresetRevision)
                or logical is None
                or logical.state != "ACTIVE"
                or logical.preset_key != expected_key
            ):
                raise ControlPlaneError("CONTROL_CREATIVE_OFFICE_BASE_INVALID", "purpose differs")
            parallel_role_policies(baseline)
            baselines.append(baseline)
        if (
            baselines[0].compatible_workflow_protocols != ("workflow-role/1.36.0",)
            or baselines[0].general_knowledge_policy != "DENY"
            or "workflow-role/1.6.0" not in baselines[1].compatible_workflow_protocols
            or baselines[0].capacity_policy_revision_id != baselines[1].capacity_policy_revision_id
        ):
            raise ControlPlaneError("CONTROL_CREATIVE_OFFICE_BASE_INVALID", "family differs")
        logical_capacity = session.scalar(
            select(WorkerCapacityPolicyRecord)
            .where(WorkerCapacityPolicyRecord.policy_key == CAPACITY_KEY)
            .with_for_update()
        )
        if logical_capacity is None:
            capacity_row = record_capacity_policy_revision(
                session,
                policy_key=CAPACITY_KEY,
                document=creative_office_report_capacity_document(created_at=datetime.now(UTC)),
                created_by=operator_id,
            )
            publish_capacity_policy_revision(
                session,
                capacity_policy_id=capacity_row.capacity_policy_id,
                capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
            )
            capacity_id = capacity_row.capacity_policy_revision_id
        else:
            if logical_capacity.state != "ACTIVE" or logical_capacity.current_revision_id is None:
                raise ControlPlaneError(
                    "CONTROL_CAPACITY_POINTER_INVALID", "Office purpose retired"
                )
            capacity_id = logical_capacity.current_revision_id
        capacity = resolve_released_capacity_policy(session, capacity_id)
        if not isinstance(capacity, WorkerCapacityPolicyV6):
            raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "Office schema differs")
    extraction = _release_preset(
        sessions,
        publisher,
        baseline=baselines[0],
        purpose="office-source",
        capacity=capacity,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    analysis = _release_preset(
        sessions,
        publisher,
        baseline=baselines[1],
        purpose="office-analysis",
        capacity=capacity,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    return CreativeOfficeParallelControls(capacity, extraction, analysis)
