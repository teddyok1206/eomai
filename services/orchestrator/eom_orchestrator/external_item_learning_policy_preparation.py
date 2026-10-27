"""Compose initial creative controls without starting or observing any worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.control_plane import ExecutionPresetRevision, ModelCandidate
from eom_workflow.schemas import role_schema_bundle_hash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID, ControlPlaneError
from eom_orchestrator.external_item_learning_control_release import (
    ReleasedExternalItemLearningControls,
    release_external_item_learning_controls,
)
from eom_orchestrator.external_item_learning_controls import (
    prepare_external_item_learning_control_draft,
    publish_external_item_learning_instruction_bundle,
    resolve_external_item_learning_control_policy,
)
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.repository import ensure_protocol_version


@dataclass(frozen=True, slots=True)
class ExternalItemLearningControlInputs:
    definition: CompiledWorkflowDefinition
    platform_payload: bytes = field(repr=False)
    role_payload: bytes = field(repr=False)
    source_commit: str
    reviewed_at: datetime
    capacity_revision_id: str
    candidate: ModelCandidate


def prepare_external_item_learning_execution_policy(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    inputs: ExternalItemLearningControlInputs,
    operator_id: str,
    authorize_control_change: Callable[[str], None],
) -> ReleasedExternalItemLearningControls:
    """Initialize once or replay exact initial pins; never edit a released predecessor."""

    from eom_workflow_runner.external_item_learning_admission import (
        validate_external_item_learning_definition,
    )
    from eom_workflow_runner.repository import import_workflow_definition

    authorize_control_change(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        definition, _created = import_workflow_definition(session, inputs.definition)
        validate_external_item_learning_definition(definition)
        ensure_protocol_version(
            session, "workflow-role/1.33.0", role_schema_bundle_hash("workflow-role/1.33.0")
        )
        authorize_control_change(operator_id)
    instruction = publish_external_item_learning_instruction_bundle(
        sessions,
        publisher,
        platform_payload=inputs.platform_payload,
        role_payload=inputs.role_payload,
        source_commit=inputs.source_commit,
        operator_id=operator_id,
        created_at=inputs.reviewed_at,
        authorize_control_change=authorize_control_change,
    )
    with sessions.begin() as session:
        authorize_control_change(operator_id)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "external-item-learning"
            )
        )
        if logical is None or logical.current_revision_id is None:
            draft = prepare_external_item_learning_control_draft(
                session,
                instruction=instruction,
                capacity_revision_id=inputs.capacity_revision_id,
                candidate=inputs.candidate,
                operator_id=operator_id,
                created_at=inputs.reviewed_at,
                authorize_control_change=authorize_control_change,
            )
        else:
            row = session.scalar(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id == logical.preset_id,
                    ExecutionPresetRevisionRecord.revision_number == 1,
                )
            )
            original = validated_preset(row) if row is not None else None
            role = resolve_external_item_learning_control_policy(
                session,
                instruction=instruction,
                capacity_revision_id=inputs.capacity_revision_id,
                candidate=inputs.candidate,
            )
            if (
                not isinstance(original, ExecutionPresetRevision)
                or original.state != "DRAFT"
                or original.role_policies != (role,)
                or original.capacity_policy_revision_id != inputs.capacity_revision_id
                or original.created_at != inputs.reviewed_at
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT", "creative initial policy differs"
                )
            draft = original
    return release_external_item_learning_controls(
        sessions,
        publisher,
        draft=draft,
        operator_id=operator_id,
        source_commit=inputs.source_commit,
        authorize_control_change=authorize_control_change,
    )
